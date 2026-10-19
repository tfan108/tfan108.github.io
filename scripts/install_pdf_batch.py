"""Install a reviewed PDF batch locally after independent all-page checks."""
import argparse
import datetime
import json
import shutil
from pathlib import Path

from prepare_pdf_downloads import ROOT, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    args = parser.parse_args()
    approval = json.loads((args.review / '核验通过.json').read_text('utf-8'))['approved']
    qa = json.loads((args.review / '逐页压缩核验.json').read_text('utf-8'))
    if qa['flagged_ids'] or qa['papers'] != len(approval):
        raise ValueError('All-page PDF verification is incomplete')
    checks = {r['library_id']:r for r in qa['results']}
    catalog = {r['id']:r for r in json.loads((args.library / '00_索引/论文元数据.json').read_text('utf-8'))}
    path = ROOT / 'data/pdf_downloads.json'
    before = path.read_bytes()
    manifest = json.loads(before)
    backup = args.review / '主页下载更新前.json'
    if not backup.exists():
        backup.write_bytes(before)
    for entry in manifest['downloads'].values():
        current = ROOT / 'static' / entry['path'].lstrip('/')
        if sha256(current) != entry['sha256']:
            raise ValueError('Current website PDF changed: '+entry['library_id'])
    replacements = {}
    for entry in manifest['downloads'].values():
        pid = entry['library_id']
        if pid not in approval:
            continue
        new = json.loads((ROOT / '.venv/pdf-work/results' / (pid+'.json')).read_text('utf-8'))
        candidate = ROOT / '.venv/pdf-work/compressed' / (pid+'.pdf')
        if (new['source_sha256'] != approval[pid]['sha256']
                or sha256(candidate) != new['sha256']
                or checks[pid]['output_sha256'] != new['sha256']
                or checks[pid]['source_sha256'] != new['source_sha256']
                or checks[pid]['pages_checked'] != new['pages']
                or sha256(args.library / catalog[pid]['local_file']) != new['source_sha256']):
            raise ValueError('Staged PDF no longer matches review: '+pid)
        new['verification']['poppler_all_pages'] = {
            'pages_checked':checks[pid]['pages_checked'], 'dpi':60,
            'no_new_renderer_warnings':True, 'max_mean_pixel_difference':checks[pid]['max_mad']}
        new['version_evidence'] = approval[pid]['evidence']
        replacements[new['paper_id']] = new
    if len(replacements) != len(approval) or path.read_bytes() != before:
        raise ValueError('Manifest or target set changed during review')
    for paper_id, entry in replacements.items():
        shutil.copyfile(ROOT / '.venv/pdf-work/compressed' / (entry['library_id']+'.pdf'),
                        ROOT / 'static' / entry['path'].lstrip('/'))
        manifest['downloads'][paper_id] = entry
    rows = list(manifest['downloads'].values())
    source_bytes = sum(r['source_bytes'] for r in rows)
    total = sum(r['bytes'] for r in rows)
    manifest['summary'] = dict(count=len(rows), pages=sum(r['pages'] for r in rows),
            source_bytes=source_bytes, bytes=total,
            reduction_percent=round((1-total/source_bytes)*100,1))
    date = json.loads((args.review / '核验通过.json').read_text('utf-8')).get('checked_on') or datetime.date.today().isoformat()
    previous = manifest.get('formal_version_update', {})
    updated_ids = sorted(set(previous.get('updated_ids', [])) | set(approval))
    pending_ids = sorted(r['id'] for r in catalog.values() if r.get('included', True)
                         and r.get('formal_fulltext_status') == 'preprint_only')
    manifest['generated_on'] = date
    manifest['formal_version_update'] = dict(date=date, updated=len(updated_ids),
            pending=len(pending_ids), updated_ids=updated_ids, pending_ids=pending_ids)
    manifest.setdefault('formal_version_batches', []).append(dict(date=date, ids=sorted(approval),
            review_folder=args.review.relative_to(args.library).as_posix()))
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n','utf-8')
    new_batch_bytes = sum(r['bytes'] for r in replacements.values())
    new_batch_source = sum(r['source_bytes'] for r in replacements.values())
    summary = dict(updated=len(replacements), cumulative_formal_updated=len(updated_ids), pending=len(pending_ids),
            formal_source_bytes=new_batch_source, formal_compressed_bytes=new_batch_bytes,
            formal_reduction_percent=round((1-new_batch_bytes/new_batch_source)*100,1),
            all_downloads=manifest['summary'])
    (args.review / '更新统计.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n','utf-8')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()

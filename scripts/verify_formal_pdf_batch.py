"""Independently render every staged page with Poppler before website updates."""
import argparse
import concurrent.futures
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT.parent.parent
REVIEW = None
WORK = None


def check(job):
    entry, source = job
    pid = entry['library_id']
    folder = WORK / pid
    folder.mkdir(parents=True, exist_ok=True)
    cache = folder / 'result.json'
    if cache.exists():
        saved = json.loads(cache.read_text('utf-8'))
        if (saved.get('output_sha256') == entry['sha256']
                and saved.get('source_sha256') == entry['source_sha256']):
            return saved
    messages = {}
    target = ROOT / '.venv/pdf-work/compressed' / (pid + '.pdf')
    for kind, path in [('original', source), ('output', target)]:
        run = subprocess.run(['pdftoppm', '-r', '60', '-png', str(path), str(folder / kind)],
                             capture_output=True, timeout=240)
        if run.returncode:
            raise ValueError(f'{pid} {kind}: {run.stderr.decode("utf-8", "replace")[:400]}')
        messages[kind] = run.stderr.decode('utf-8', 'replace').strip()
    before, after = sorted(folder.glob('original-*.png')), sorted(folder.glob('output-*.png'))
    assert len(before) == len(after) == entry['pages'], pid
    pages = []
    for n, (a, b) in enumerate(zip(before, after), 1):
        with Image.open(a) as ai, Image.open(b) as bi:
            ai, bi = ai.convert('RGB'), bi.convert('RGB')
            assert ai.size == bi.size, (pid, n)
            diff = ImageChops.difference(ai, bi)
            mad = sum(ImageStat.Stat(diff).mean) / 3
            channels = diff.split()
            peak = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
            fraction = sum(peak.histogram()[51:]) / (ai.width * ai.height)
        pages.append(dict(page=n, mad=round(mad, 4), large_change_fraction=round(fraction, 5)))
    flags = [p for p in pages if p['mad'] > 2 or p['large_change_fraction'] > .02]
    warnings = bool(set(messages['output'].splitlines()) - set(messages['original'].splitlines()))
    result = dict(library_id=pid, source_sha256=entry['source_sha256'], output_sha256=entry['sha256'],
                  pages_checked=len(pages), flagged=flags, new_output_warnings=warnings,
                  renderer_messages=messages, pages=pages, first_page_png=str(after[0]),
                  max_mad=max(p['mad'] for p in pages))
    cache.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    if not flags and not warnings:
        for a, b in zip(before, after):
            a.unlink()
            if b != after[0]:
                b.unlink()
    return result


def main():
    global LIBRARY, REVIEW, WORK
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', nargs='*')
    parser.add_argument('--library', type=Path, default=LIBRARY)
    parser.add_argument('--review', type=Path, required=True)
    args = parser.parse_args()
    LIBRARY = args.library.resolve()
    REVIEW = args.review.resolve()
    WORK = REVIEW / '页面核验'
    approved = json.loads((REVIEW / '核验通过.json').read_text('utf-8'))['approved']
    records = {p['id']: p for p in json.loads((LIBRARY / '00_索引/论文元数据.json').read_text('utf-8'))}
    jobs = []
    for pid in approved:
        if args.only and pid not in args.only:
            continue
        entry = json.loads((ROOT / '.venv/pdf-work/results' / (pid + '.json')).read_text('utf-8'))
        jobs.append((entry, LIBRARY / records[pid]['local_file']))
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for r in pool.map(check, jobs):
            results.append(r)
            print(f"{len(results)}/{len(jobs)} {r['library_id']} pages={r['pages_checked']} "
                  f"MAD={r['max_mad']:.3f} flags={len(r['flagged'])} "
                  f"new_warnings={r['new_output_warnings']}", flush=True)
    summary = dict(papers=len(results), pages=sum(r['pages_checked'] for r in results),
                   flagged_ids=[r['library_id'] for r in results if r['flagged'] or r['new_output_warnings']],
                   results=results)
    if not args.only:
        (REVIEW / '逐页压缩核验.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n','utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k != 'results'}), flush=True)


if __name__ == '__main__':
    main()

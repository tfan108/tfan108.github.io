"""Prepare a reviewed formal-version batch at readable web resolution.

This stages outputs only. Independent all-page rendering must pass before a
caller replaces website files or the manifest. Original PDFs remain read-only.
"""
import argparse
import json
from pathlib import Path

import prepare_pdf_downloads as pdf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--only', nargs='*')
    parser.add_argument('--review', type=Path, required=True, help='Folder containing the reviewed batch manifest')
    parser.add_argument('--conservative', action='store_true',
                        help='Preserve image color spaces for visually sensitive PDFs')
    args = parser.parse_args()
    library = args.library.resolve()
    review = args.review / '核验通过.json'
    approved = json.loads(review.read_text('utf-8'))['approved']
    catalog = json.loads((library / '00_索引/论文元数据.json').read_text('utf-8'))
    active = {pdf.build.norm_title(p['title']): p for p in catalog if p.get('included', True)}
    report = pdf.build.Report()
    site = pdf.build.load_site(report)
    _, venues = pdf.build.load_venues(report)
    papers = pdf.build.load_papers(report, site, venues)
    if report.errors:
        raise ValueError(report.errors)
    if not args.conservative:
        pdf.PROFILE = {'strategy': 'publication_images', 'dpi_threshold': 240,
                       'dpi_target': 180, 'quality': 85}
        pdf.VALIDATION_POLICY = 4

        def rewrite(doc):
            doc.rewrite_images(dpi_threshold=240, dpi_target=180, quality=85)

        pdf.optimize_embedded_images = rewrite
    jobs = [(active[pdf.build.norm_title(p['title'])], p, str(library)) for p in papers
            if active[pdf.build.norm_title(p['title'])]['id'] in approved]
    if args.only:
        jobs = [j for j in jobs if j[0]['id'] in args.only]
    for index, job in enumerate(jobs, 1):
        result = pdf.prepare_one(job)
        print(f"{index}/{len(jobs)} {result['library_id']}: "
              f"{result['source_bytes']/1e6:.2f} -> {result['bytes']/1e6:.2f} MB "
              f"({result['method']})", flush=True)


if __name__ == '__main__':
    main()

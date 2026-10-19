"""Create verified, smaller PDF copies from the separate research library.

Original files are read-only inputs. Outputs are staged until every displayed
paper has passed page, text, link and render checks. PyMuPDF uses processes,
not threads, so each worker has its own document objects.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pymupdf
from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build

STAGE = ROOT / ".venv" / "pdf-work"
PROFILE = {"strategy": "embedded_images", "max_dimension": 2200, "quality": 92, "subsampling": 0}
VALIDATION_POLICY = 3
VERSION_LABELS = {
    "arxiv_preprint": "arXiv preprint",
    "conference_published": "Published conference version",
    "publisher_pdf": "Publisher version",
    "author_hosted": "Author-hosted version",
    "user_supplied_fulltext": "Archived full text",
    "unknown": "Archived copy (version not confirmed)",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(doc):
    pages = []
    for page in doc:
        text = " ".join(page.get_text().split())
        pages.append({
            "text": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "box": list(page.rect), "rotation": page.rotation,
            "links": len(page.get_links()),
            "annotations": sum(1 for _ in page.annots()),
        })
    # Object streams may raise the PDF container version from 1.4 to 1.5.
    # That is separate from the document's bibliographic metadata and content.
    metadata = {k: v for k, v in doc.metadata.items() if k != "format"}
    return {"pages": pages, "toc": doc.get_toc(), "metadata": metadata}


def image_page(doc):
    return max(range(len(doc)), key=lambda n: sum(x[2] * x[3] for x in doc[n].get_images(full=True)))


def rendered_image(page):
    pix = page.get_pixmap(dpi=96, colorspace=pymupdf.csRGB, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def verify(source, candidate: Path, expected, selected):
    with pymupdf.open(candidate) as output:
        if snapshot(output) != expected:
            raise ValueError("Page geometry, text, links, annotations or metadata changed")
        comparisons = []
        for number in selected:
            before = rendered_image(source[number])
            after = rendered_image(output[number])
            if before.size != after.size:
                raise ValueError("Rendered page dimensions changed")
            mad = sum(ImageStat.Stat(ImageChops.difference(before, after)).mean) / 3
            if mad > 4.0:
                raise ValueError(f"Page {number + 1} render difference too large: {mad:.3f}")
            comparisons.append({"page": number + 1, "mean_absolute_pixel_difference": round(mad, 4)})
        return comparisons


def save_document(doc, target: Path):
    doc.save(target, garbage=4, deflate=True, deflate_images=True,
             deflate_fonts=True, use_objstms=1, compression_effort=80,
             no_new_id=True, preserve_metadata=True)


def optimize_embedded_images(doc):
    """Replace photo streams while preserving page drawing instructions.

    Leave transparency, ICC/CMYK colors and small/palette images intact. Unlike
    rewriting the page display list, this preserves complex pattern resources.
    """
    seen = set()
    for page in doc:
        for info in page.get_images(full=True):
            xref, mask, width, height, depth, colorspace = info[:6]
            if xref in seen:
                continue
            seen.add(xref)
            if mask or depth != 8 or colorspace not in {"DeviceRGB", "DeviceGray"} or max(width, height) < 300:
                continue
            image_data = doc.extract_image(xref)
            if not image_data:
                continue
            with Image.open(io.BytesIO(image_data["image"])) as image:
                if image.mode not in {"RGB", "L"} or image.getcolors(257) is not None:
                    continue
                image.thumbnail((PROFILE["max_dimension"], PROFILE["max_dimension"]), Image.Resampling.LANCZOS)
                stream = io.BytesIO()
                image.save(stream, format="JPEG", quality=PROFILE["quality"], subsampling=PROFILE["subsampling"], optimize=True)
            jpeg = stream.getvalue()
            if len(jpeg) < len(doc.xref_stream_raw(xref)) * 0.95:
                page.replace_image(xref, stream=jpeg)


def prepare_one(job):
    item, paper, library = job
    library = Path(library)
    source = (library / item["local_file"]).resolve()
    source.relative_to(library.resolve())
    original_hash = sha256(source)
    recorded_hash = item.get("pdf_validation", {}).get("sha256")
    if recorded_hash != original_hash:
        raise ValueError(f"{item['id']}: original checksum differs from the library record")
    out = STAGE / "compressed" / f"{item['id']}.pdf"
    result_path = STAGE / "results" / f"{item['id']}.json"
    if result_path.exists() and out.exists():
        cached = json.loads(result_path.read_text(encoding="utf-8"))
        if (cached["source_sha256"] == original_hash and cached["profile"] == PROFILE
                and cached.get("validation_policy") == VALIDATION_POLICY and cached["sha256"] == sha256(out)):
            cached['version'] = item.get('download_version', 'unknown')
            cached['version_label'] = item.get('web_version_label') or VERSION_LABELS.get(cached['version'], 'Archived full text')
            cached['source_kind'] = 'user_supplied' if item.get('source_discovery') == 'user_supplied_formal_pdf' else 'downloaded'
            cached['source_url'] = item.get('download_url') if cached['source_kind'] == 'user_supplied' else item.get('download_url') or item.get('source')
            cached['publication_locator'] = ('https://doi.org/' + item['doi']) if item.get('doi') else None
            result_path.write_text(json.dumps(cached, ensure_ascii=False, indent=2) + '\n', 'utf-8')
            return cached
    errors = []
    with pymupdf.open(source) as original:
        if original.is_encrypted or len(original) != item["pdf_validation"]["pages"]:
            raise ValueError(f"{item['id']}: source page validation failed")
        expected = snapshot(original)
        selected = sorted({0, image_page(original), len(original) - 1})
        candidates = [(source, "already_optimized", [])]
        for method in ("image_optimized", "lossless_optimized"):
            candidate = STAGE / f"{item['id']}-{method}.pdf"
            try:
                with pymupdf.open(source) as doc:
                    if method == "image_optimized":
                        optimize_embedded_images(doc)
                    save_document(doc, candidate)
                if candidate.stat().st_size < source.stat().st_size:
                    comparisons = verify(original, candidate, expected, selected)
                    candidates.append((candidate, method, comparisons))
            except Exception as error:
                errors.append(f"{method}: {error}")
            # A successful smaller image rewrite already includes lossless cleanup.
            if len(candidates) > 1:
                break
        best, method, comparisons = min(candidates, key=lambda row: row[0].stat().st_size)
        shutil.copyfile(best, out)
        if not comparisons:
            comparisons = verify(original, out, expected, selected)
        with pymupdf.open(out) as compressed:
            for number in selected:
                rendered_image(compressed[number]).save(STAGE / "qa" / f"{item['id']}-p{number + 1}.png")
        if sha256(source) != original_hash:
            raise ValueError(f"{item['id']}: original file changed during processing")
        result = {
            "library_id": item["id"], "paper_id": paper["id"], "title": item["title"],
            "path": f"/files/papers/{item['id']}.pdf",
            "pages": len(original), "bytes": out.stat().st_size,
            "source_bytes": source.stat().st_size, "source_sha256": original_hash,
            "sha256": sha256(out), "source_url": item.get("download_url") if item.get("source_discovery") == "user_supplied_formal_pdf" else item.get("download_url") or item.get("source"),
            "source_kind": "user_supplied" if item.get("source_discovery") == "user_supplied_formal_pdf" else "downloaded",
            "publication_locator": ("https://doi.org/" + item["doi"]) if item.get("doi") else None,
            "version": item.get("download_version", "unknown"),
            "version_label": item.get("web_version_label") or VERSION_LABELS.get(item.get("download_version"), "Archived full text"),
            "method": method, "profile": PROFILE, "validation_policy": VALIDATION_POLICY,
            "verification": {"all_page_text_and_structure_unchanged": True,
                             "original_unchanged": True, "render_comparisons": comparisons},
            "optimization_notes": errors,
        }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for method in ("image_optimized", "lossless_optimized"):
        (STAGE / f"{item['id']}-{method}.pdf").unlink(missing_ok=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--only", nargs="*", help="Prepare a sample without publishing the manifest")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    library = args.library.resolve()
    catalog = json.loads((library / "00_索引" / "论文元数据.json").read_text(encoding="utf-8"))
    active = {build.norm_title(p["title"]): p for p in catalog if p.get("included", True)}
    report = build.Report()
    site = build.load_site(report)
    _, lookup = build.load_venues(report)
    papers = build.load_papers(report, site, lookup)
    if report.errors:
        raise ValueError(report.errors)
    if {build.norm_title(p["title"]) for p in papers} != set(active):
        raise ValueError("Displayed papers and active local library do not match")
    jobs = [(active[build.norm_title(p["title"])], p, str(library)) for p in papers]
    if args.only:
        jobs = [j for j in jobs if j[0]["id"] in args.only]
    for folder in (STAGE / "compressed", STAGE / "results", STAGE / "qa"):
        folder.mkdir(parents=True, exist_ok=True)
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(prepare_one, job): job[0]["id"] for job in jobs}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"{len(results)}/{len(jobs)} {result['library_id']}: "
                  f"{result['source_bytes'] / 1e6:.2f} -> {result['bytes'] / 1e6:.2f} MB "
                  f"({result['method']})", flush=True)
    results.sort(key=lambda r: r["library_id"])
    summary = {"count": len(results), "pages": sum(r["pages"] for r in results),
               "source_bytes": sum(r["source_bytes"] for r in results),
               "bytes": sum(r["bytes"] for r in results)}
    print(json.dumps(summary), flush=True)
    if args.finalize:
        if args.only or len(results) != len(papers):
            raise ValueError("Partial batches cannot become the public download manifest")
        target = (ROOT / "static" / "files" / "papers").resolve()
        target.relative_to(ROOT.resolve())
        if target.exists():
            raise ValueError("Download directory already exists; inspect it before replacing files")
        target.parent.mkdir(parents=True, exist_ok=True)
        (STAGE / "compressed").resolve().relative_to(ROOT.resolve())
        (STAGE / "compressed").rename(target)
        manifest = {"generated_on": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat(),
                    "summary": summary, "downloads": {r["paper_id"]: r for r in results}}
        (ROOT / "data" / "pdf_downloads.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

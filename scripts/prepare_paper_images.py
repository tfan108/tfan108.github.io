"""Reproduce publication thumbnails from reviewed local figures/PDF regions.

The website build only needs static/images/papers; this optional maintenance
script reads the private research library and never changes its originals.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path

from PIL import Image, ImageOps

REPO = Path(__file__).resolve().parents[1]
SIZE = (640, 480)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_source(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"Missing or invalid library source: {relative}")
    return path


def read_source(entry: dict, library: Path) -> Image.Image:
    if entry.get("source_asset"):
        path = local_source(library, entry["source_asset"])
        if digest(path) != entry["source_asset_sha256"]:
            raise ValueError(f"{entry['id']}: source figure changed; review crops again")
        with Image.open(path) as image:
            return ImageOps.exif_transpose(image).convert("RGB")
    import pymupdf

    path = local_source(library, entry["source_pdf"])
    if digest(path) != entry["source_pdf_sha256"]:
        raise ValueError(f"{entry['id']}: source PDF changed; review its page again")
    with pymupdf.open(path) as document:
        page = document[entry["page"] - 1]
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2.5, 2.5), alpha=False)
        return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def make_image(entry: dict, source: Image.Image) -> bytes:
    regions = entry["regions"]
    columns = entry.get("columns", 1)
    if not regions or not 1 <= columns <= len(regions):
        raise ValueError(f"{entry['id']}: invalid image layout")
    rows = math.ceil(len(regions) / columns)
    gap = 4 if len(regions) > 1 else 0
    canvas = Image.new("RGB", SIZE, "white")
    cell_w = (SIZE[0] - gap * (columns - 1)) // columns
    cell_h = (SIZE[1] - gap * (rows - 1)) // rows
    for index, region in enumerate(regions):
        left, top, right, bottom = region
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError(f"{entry['id']}: invalid normalized crop {region}")
        patch = source.crop((round(left * source.width), round(top * source.height),
                             round(right * source.width), round(bottom * source.height)))
        cell = (cell_w, cell_h)
        if entry.get("fit", "contain") == "cover":
            patch = ImageOps.fit(patch, cell, method=Image.Resampling.LANCZOS)
        else:
            patch = ImageOps.contain(patch, cell, method=Image.Resampling.LANCZOS)
        x = index % columns * (cell_w + gap) + (cell_w - patch.width) // 2
        y = index // columns * (cell_h + gap) + (cell_h - patch.height) // 2
        canvas.paste(patch, (x, y))
    stream = io.BytesIO()
    canvas.save(stream, "JPEG", quality=92, optimize=True, progressive=True)
    return stream.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-root", type=Path, default=REPO.parents[1])
    parser.add_argument("--check", action="store_true", help="verify reproducibility without writing")
    args = parser.parse_args()
    manifest = json.loads((REPO / "data/paper_images.json").read_text(encoding="utf-8"))
    entries = manifest["papers"]
    ids = [entry["id"] for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate paper image IDs")
    prepared = []
    for entry in entries:
        output = (REPO / "static" / entry["image"].lstrip("/")).resolve()
        if output.parent != (REPO / "static/images/papers").resolve():
            raise ValueError(f"Invalid output path: {entry['image']}")
        prepared.append((output, make_image(entry, read_source(entry, args.library_root))))
    changed = 0
    for output, content in prepared:
        if not output.exists() or output.read_bytes() != content:
            if args.check:
                raise ValueError(f"Thumbnail needs regeneration: {output.name}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
            changed += 1
    print(f"{len(prepared)} publication images verified; {changed} updated; "
          f"{sum(len(content) for _, content in prepared):,} bytes")


if __name__ == "__main__":
    main()

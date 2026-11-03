"""Reproduce publication thumbnails from reviewed regions of the archived paper PDFs.

The website build only needs static/images/papers; this optional maintenance
script reads the private research library and never changes its originals.

Every thumbnail is rendered straight from the paper PDF (vector figures stay
sharp). Each listed region is a complete figure or a complete sub-image of one,
and regions are never cropped to fill the frame:

* ``pack``    - regions are laid out in the listed rows (each row justified to
                the same width), then the whole block is fitted into 640x480 on
                white, so every sub-image stays whole.
* ``contain`` - one region (usually a diagram) is fitted into 640x480 on the
                figure's own background colour.

Region coordinates are fractions of the PDF page: [left, top, right, bottom].
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
SIZE = (640, 480)
PACK_WIDTH = 2000   # working width of the packed block before it is fitted
PACK_GAP = 12       # gap between sub-images at the working width (about 4px final)
CONTAIN_MARGIN = 24


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_source(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"Missing or invalid library source: {relative}")
    return path


def render_region(document, entry: dict, region: dict, need: tuple[int, int]) -> Image.Image:
    import pymupdf

    page = document[region["page"] - 1]
    left, top, right, bottom = region["rect"]
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError(f"{entry['id']}: invalid normalized region {region['rect']}")
    box = page.rect
    clip = pymupdf.Rect(box.x0 + left * box.width, box.y0 + top * box.height,
                        box.x0 + right * box.width, box.y0 + bottom * box.height)
    zoom = max(need[0] / clip.width, need[1] / clip.height) * 1.6
    zoom = min(max(zoom, 2.0), 14.0)
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def same_image(path: Path, content: bytes) -> bool:
    """Compare decoded pixels, so metadata added to a JPEG later does not count as a change."""
    if not path.exists():
        return False
    if path.read_bytes() == content:
        return True
    try:
        with Image.open(path) as current, Image.open(io.BytesIO(content)) as fresh:
            return (current.size == fresh.size
                    and current.convert("RGB").tobytes() == fresh.convert("RGB").tobytes())
    except OSError:
        return False


def fit_onto(canvas: Image.Image, block: Image.Image, margin: int = 0) -> None:
    scale = min((SIZE[0] - margin) / block.width, (SIZE[1] - margin) / block.height)
    block = block.resize((round(block.width * scale), round(block.height * scale)),
                         Image.Resampling.LANCZOS)
    canvas.paste(block, ((SIZE[0] - block.width) // 2, (SIZE[1] - block.height) // 2))


def make_pack(document, entry: dict) -> Image.Image:
    rows = []
    for row in entry["rows"]:
        if not row:
            raise ValueError(f"{entry['id']}: empty row")
        images = [render_region(document, entry, region, (1400, 1000)) for region in row]
        aspect = sum(image.width / image.height for image in images)
        height = round((PACK_WIDTH - PACK_GAP * (len(images) - 1)) / aspect)
        strip = Image.new("RGB", (PACK_WIDTH, height), "white")
        x = 0
        for index, image in enumerate(images):
            width = (round(image.width * height / image.height) if index < len(images) - 1
                     else PACK_WIDTH - x)
            strip.paste(image.resize((width, height), Image.Resampling.LANCZOS), (x, 0))
            x += width + PACK_GAP
        rows.append(strip)
    block = Image.new("RGB", (PACK_WIDTH, sum(r.height for r in rows) + PACK_GAP * (len(rows) - 1)),
                      "white")
    y = 0
    for strip in rows:
        block.paste(strip, (0, y))
        y += strip.height + PACK_GAP
    canvas = Image.new("RGB", SIZE, "white")
    fit_onto(canvas, block)
    return canvas


def make_contain(document, entry: dict) -> Image.Image:
    if len(entry["rows"]) != 1 or len(entry["rows"][0]) != 1:
        raise ValueError(f"{entry['id']}: contain layout takes exactly one region")
    figure = render_region(document, entry, entry["rows"][0][0], SIZE)
    corners = sorted(figure.getpixel((x, y)) for x in (0, figure.width - 1)
                     for y in (0, figure.height - 1))
    canvas = Image.new("RGB", SIZE, tuple(corners[1]))
    fit_onto(canvas, figure, CONTAIN_MARGIN)
    return canvas


def make_image(entry: dict, library: Path) -> bytes:
    import pymupdf

    path = local_source(library, entry["source_pdf"])
    if digest(path) != entry["source_pdf_sha256"]:
        raise ValueError(f"{entry['id']}: source PDF changed; review its figure again")
    layouts = {"pack": make_pack, "contain": make_contain}
    if entry.get("layout") not in layouts or not entry.get("rows"):
        raise ValueError(f"{entry['id']}: invalid image layout")
    with pymupdf.open(path) as document:
        canvas = layouts[entry["layout"]](document, entry)
    stream = io.BytesIO()
    canvas.save(stream, "JPEG", quality=92, optimize=True, progressive=True)
    return stream.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--library-root", type=Path, default=REPO.parents[1])
    parser.add_argument("--check", action="store_true", help="verify reproducibility without writing")
    parser.add_argument("--only", nargs="*", default=None, help="limit to these paper IDs, e.g. FT001")
    args = parser.parse_args()
    manifest = json.loads((REPO / "data/paper_images.json").read_text(encoding="utf-8"))
    entries = manifest["papers"]
    ids = [entry["id"] for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate paper image IDs")
    if args.only:
        entries = [entry for entry in entries if entry["id"] in set(args.only)]
    prepared = []
    for entry in entries:
        output = (REPO / "static" / entry["image"].lstrip("/")).resolve()
        if output.parent != (REPO / "static/images/papers").resolve():
            raise ValueError(f"Invalid output path: {entry['image']}")
        prepared.append((output, make_image(entry, args.library_root)))
    changed = 0
    for output, content in prepared:
        if not same_image(output, content):
            if args.check:
                raise ValueError(f"Thumbnail needs regeneration: {output.name}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
            changed += 1
    print(f"{len(prepared)} publication images verified; {changed} updated; "
          f"{sum(len(content) for _, content in prepared):,} bytes")


if __name__ == "__main__":
    main()

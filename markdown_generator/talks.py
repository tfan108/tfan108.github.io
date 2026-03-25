#!/usr/bin/env python3
"""
Talks markdown generator for AcademicPages.

Reads a TSV with talk metadata and writes one Markdown file per talk into
`../_talks/` (relative to this script's directory), matching the template's
expected front matter.
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Any, Dict, List


HTML_ESCAPE_TABLE = {
    "&": "&amp;",
    '"': "&quot;",
    "'": "&apos;"
    }

def html_escape(text):
    if isinstance(text, str):
        return "".join(HTML_ESCAPE_TABLE.get(c, c) for c in text)
    return ""


REQUIRED_COLUMNS = ["title", "url_slug", "date"]
ALL_COLUMNS = [
    "title",
    "type",
    "url_slug",
    "venue",
    "date",
    "location",
    "talk_url",
    "description",
]


def read_tsv(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if reader.fieldnames is None:
            raise SystemExit("TSV has no header row.")

        missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise SystemExit(f"Missing required columns in TSV header: {missing}")

        rows: List[Dict[str, Any]] = []
        for row in reader:
            # Normalize expected keys
            norm = {k: (row.get(k, "") or "") for k in ALL_COLUMNS}
            rows.append(norm)
        return rows


def write_talk_md(row: Dict[str, Any], output_dir: Path) -> Path:
    title = row["title"]
    url_slug = row["url_slug"]
    date = row["date"]
    talk_type = row.get("type") or "Talk"
    venue = row.get("venue", "")
    location = row.get("location", "")
    talk_url = row.get("talk_url", "")
    description = row.get("description", "")

    md_filename = f"{date}-{url_slug}.md"
    html_filename = f"{date}-{url_slug}"

    md = "---\n"
    md += f'title: "{title}"\n'
    md += "collection: talks\n"
    md += f'type: "{talk_type if len(str(talk_type)) > 0 else "Talk"}"\n'
    md += f"permalink: /talks/{html_filename}\n"

    if len(str(venue)) > 0:
        md += f'venue: "{venue}"\n'
    if len(str(date)) > 0:
        md += f"date: {date}\n"
    if len(str(location)) > 0:
        md += f'location: "{location}"\n'
    md += "---\n"

    if len(str(talk_url)) > 0:
        md += f"\n[More information here]({talk_url})\n"
    if len(str(description)) > 0:
        md += "\n" + html_escape(description) + "\n"

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / os.path.basename(md_filename)
    out_path.write_text(md, encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate _talks/*.md from a TSV file")
    parser.add_argument(
        "tsv",
        nargs="?",
        default="talks.tsv",
        help="Input TSV file (default: talks.tsv in current working directory)",
    )
    parser.add_argument(
        "--out",
        default=str((Path(__file__).resolve().parent / "../_talks").resolve()),
        help="Output directory for generated markdown files (default: ../_talks relative to script)",
    )
    args = parser.parse_args()

    rows = read_tsv(Path(args.tsv))
    out_dir = Path(args.out)

    for row in rows:
        if not row["title"] or not row["url_slug"] or not row["date"]:
            # Skip incomplete lines (keeps behavior forgiving)
            continue
        write_talk_md(row, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# Publications markdown generator for AcademicPages
# 
# Takes a TSV / CSV of publications with metadata and converts them for use with [academicpages.github.io](academicpages.github.io). 
# Can be called via the command prompt by using `python3 publications.py [filename]`.

# Data format
# 
# The file needs to have the following columns as a header at the top:
# pub_date, title, venue, excerpt, citation, url_slug, paper_url, slides_url
# - `excerpt`, `paper_url`, and slides_url can be blank, but the others must have values. 
# - `pub_date` must be formatted as YYYY-MM-DD.
# - `url_slug` will be the descriptive part of the .md file and the permalink URL for the page about the paper. 
#    The .md file will be `YYYY-MM-DD-[url_slug].md` and the permalink will be `https://[yourdomain]/publications/YYYY-MM-DD-[url_slug]`
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

# Flag to indicate an error occurred
EXIT_ERROR = 0

# The expected layout of the CSV / TSV file
HEADER_LEGACY  = ['pub_date', 'title', 'venue', 'excerpt', 'citation', 'url_slug', 'paper_url', 'slides_url']
HEADER_UPDATED = ['pub_date', 'title', 'venue', 'excerpt', 'citation', 'url_slug', 'paper_url', 'slides_url', 'category']

# YAML is very picky about how it takes a valid string, so we are replacing single and double quotes (and ampersands)
# with their HTML encoded equivalents. This makes them look not so readable in raw format, but they are parsed and
# rendered nicely.
HTML_ESCAPE_TABLE = {
    "&": "&amp;",
    '"': "&quot;",
    "'": "&apos;"
    }

# This is where the heavy lifting is done. This loops through all the rows in the TSV dataframe, then starts to
# concatenate a big string (```md```) that contains the markdown for each type. It does the YAML metadata first, then
# does the description for the individual page.
REPO_ROOT = (Path(__file__).resolve().parent / "..").resolve()
DEFAULT_OUT_DIR = REPO_ROOT / "_publications"


def create_md(lines: Sequence[Sequence[str]], layout: Sequence[str], out_dir: Path = DEFAULT_OUT_DIR) -> None:
    for item in lines:
        # Parse the filename information
        md_filename = f"{item[layout.index('pub_date')]}-{item[layout.index('url_slug')]}.md"
        html_filename = str(item[layout.index('pub_date')]) + "-" + item[layout.index('url_slug')]
        
        # Parse the YAML variables
        md = f"---\ntitle: \"{item[layout.index('title')]}\"\n"
        md += "collection: publications"
        if len(layout) == len(HEADER_UPDATED):
            md += f"\ncategory: {item[layout.index('category')]}"
        else:
            md += "\ncategory: manuscripts"
        md += f"\npermalink: /publication/{html_filename}"
        if len(str(item[layout.index('excerpt')])) > 5:
            md += f"\nexcerpt: '{html_escape(item[layout.index('excerpt')])}'"
        md += f"\ndate: {item[layout.index('pub_date')]}"
        md += f"\nvenue: '{html_escape(item[layout.index('venue')])}'"
        if len(str(item[layout.index('paper_url')])) > 5:
            md += f"\npaperurl: '{item[layout.index('paper_url')]}'"
        md += f"\ncitation: '{html_escape(item[layout.index('citation')])}'"
        md += "\n---"
        
        # Markdown description for individual page
        if len(str(item[layout.index('paper_url')])) > 5:
            md += f"\n<a href='{item[layout.index('paper_url')]}'>Download paper here</a>\n"
        if len(str(item[layout.index('excerpt')])) > 5:
            md += f"\n{html_escape(item[layout.index('excerpt')])}\n"
        md += f"\nRecommended citation: {item[layout.index('citation')]}"
        
        # Write the file
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / os.path.basename(md_filename)
        out_path.write_text(md, encoding="utf-8")

def html_escape(text: str) -> str:
    """Produce entities within text."""
    return "".join(HTML_ESCAPE_TABLE.get(c,c) for c in text)

def read(filename: str) -> Tuple[List[List[str]], List[str]]:
    '''Read the contents of the file, check the header and return the parsed line along with the file type.'''

    # Read the contents of the file
    lines: List[List[str]] = []
    with open(filename, 'r', encoding="utf-8", newline="") as file:
        delimiter = ',' if filename.endswith('.csv') else '\t'
        reader = csv.reader(file, delimiter=delimiter)
        for row in reader:
            lines.append(row)

    # Verify the file format makes sense
    if len(lines) <= 1:
        print(f'Not enough lines in the file to process, found {len(lines)}', file=sys.stderr)
        sys.exit(EXIT_ERROR)

    # Verify the header, remove it once checked
    layout = HEADER_UPDATED
    if HEADER_LEGACY == lines[0]:
        layout = HEADER_LEGACY
    elif HEADER_UPDATED != lines[0]:
        print(lines[0])
        print('The header of the file does not match the expected format', file=sys.stderr)
        sys.exit(EXIT_ERROR)
    lines = lines[1:]
    
    # Return the lines and format
    return lines, layout


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate _publications/*.md from a CSV/TSV file")
    parser.add_argument("input", help="Input .csv or .tsv file")
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT_DIR),
        help="Output directory for generated markdown files (default: repo/_publications)",
    )
    args = parser.parse_args(argv)

    filename = args.input
    if not (filename.endswith(".csv") or filename.endswith(".tsv")):
        print(f"Expected a TSV or CSV file, got {filename}", file=sys.stderr)
        return EXIT_ERROR

    lines, layout = read(filename)
    create_md(lines, layout, out_dir=Path(args.out))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

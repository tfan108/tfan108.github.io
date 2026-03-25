#!/usr/bin/env python3
# coding: utf-8

# # Publications markdown generator for academicpages
# 
# Takes a set of bibtex of publications and converts them for use with [academicpages.github.io](academicpages.github.io). This is an interactive Jupyter notebook ([see more info here](http://jupyter-notebook-beginner-guide.readthedocs.io/en/latest/what_is_jupyter.html)). 
# 
# The core python code is also in `pubsFromBibs.py`. 
# Run either from the `markdown_generator` folder after replacing updating the publist dictionary with:
# * bib file names
# * specific venue keys based on your bib file preferences
# * any specific pre-text for specific files
# * Collection Name (future feature)
# 
# TODO: Make this work with other databases of citations, 
# TODO: Merge this with the existing TSV parsing solution
#
# Features: fetches Semantic Scholar ID, arXiv, GitHub links; embeds BibTeX for download.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import strptime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from pybtex.database import BibliographyData
from pybtex.database.input import bibtex

REPO_ROOT = (Path(__file__).resolve().parent / "..").resolve()
SCRIPT_DIR = Path(__file__).resolve().parent
CORRESPONDING_AUTHORS_PATH = REPO_ROOT / "_data" / "corresponding_authors.yml"
PUBLICATIONS_DIR = REPO_ROOT / "_publications"
BIBTEX_OUT_DIR = REPO_ROOT / "files" / "bibtex"

def load_corresponding_authors(path: Path = CORRESPONDING_AUTHORS_PATH) -> Dict[str, List[str]]:
    """Load existing corresponding_authors.yml, preserving user edits."""
    if not path.exists():
        return {}
    result: Dict[str, List[str]] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if ':' in line:
                key, val = line.split(':', 1)
                key = key.strip()
                val = val.strip()
                if val == '[]':
                    result[key] = []
                else:
                    inner = val.strip('[]').split(',')
                    result[key] = [a.strip() for a in inner if a.strip()]
    return result


def save_corresponding_authors(
    data: Dict[str, List[str]],
    slugs_in_order: Iterable[str],
    path: Path = CORRESPONDING_AUTHORS_PATH,
) -> None:
    """Write corresponding_authors.yml, preserving order by date."""
    header = """# 通讯作者列表：在每篇论文下添加对应作者名（需与 citation 中的格式一致，如 "Fan Tang", "Tong-Yee Lee"）
# 无通讯作者的论文可保留空数组 [] 或整行删除

"""
    lines = [header]
    for slug in sorted(slugs_in_order):
        authors = data.get(slug, [])
        if authors:
            authors_str = ", ".join(authors)
            lines.append(f"{slug}: [{authors_str}]\n")
        else:
            lines.append(f"{slug}: []\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.writelines(lines)
    n: Optional[int] = None
    if hasattr(slugs_in_order, "__len__"):
        try:
            n = len(slugs_in_order)  # type: ignore[arg-type]
        except Exception:
            n = None
    if n is None:
        print(f"Updated {path}")
    else:
        print(f"Updated {path} with {n} entries")

#todo: incorporate different collection types rather than a catch all publications, requires other changes to template
publist = {
    "proceeding": {
        "file" : "proceedings.bib",
        "venuekey": "booktitle",
        "venue-pretext": "In ",
        "collection" : {"name":"publications",
                        "permalink":"/publication/"}
        
    },
    "journal":{
        "file": "publications.bib",
        "venuekey" : "journal",
        "venue-pretext" : "",
        "collection" : {"name":"publications",
                        "permalink":"/publication/"}
    } 
}

HTML_ESCAPE_TABLE = {
    "&": "&amp;",
    '"': "&quot;",
    "'": "&apos;"
    }

def html_escape(text: str) -> str:
    """Produce entities within text."""
    return "".join(HTML_ESCAPE_TABLE.get(c, c) for c in text)


def _clean_title(title: str) -> str:
    """Strip leading/trailing whitespace and normalize spaces for search."""
    s = title.strip()
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def search_semantic_scholar(title: str, year: Optional[str] = None) -> Dict[str, Any]:
    """
    Search Semantic Scholar for a paper by title (no year filter).
    Returns dict with: paperId (semantic_scholar_id), arxiv_url, open_access_pdf.
    Returns {} on failure. Does not raise.
    """
    query = _clean_title(title).replace("-", " ")
    params = urllib.parse.urlencode({
        "query": query[:200],  # S2 truncates at 100 chars, be safe
        "limit": 5,
        "fields": "paperId,externalIds,openAccessPdf,url,title,year"
    })
    headers = {"User-Agent": USER_AGENT}
    api_key = os.environ.get("S2_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    req = urllib.request.Request(
        f"https://api.semanticscholar.org/graph/v1/paper/search?{params}",
        headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise
        return {}
    except Exception:
        return {}
    results = data.get("data", [])
    if not results:
        return {}
    # Pick best match by title similarity (normalize and compare)
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())
    t_norm = norm(query)
    best = None
    best_score = 0
    for p in results:
        p_title = p.get("title", "")
        p_norm = norm(p_title)
        if t_norm in p_norm or p_norm in t_norm or t_norm[:20] in p_norm:
            overlap = len(set(t_norm) & set(p_norm))
            if overlap > best_score:
                best_score = overlap
                best = p
    if best is None:
        best = results[0]
    out = {"paperId": best.get("paperId"), "url": best.get("url", "")}
    ext = best.get("externalIds") or {}
    if "ArXiv" in ext:
        arxiv_id = ext["ArXiv"]
        if not arxiv_id.startswith("http"):
            arxiv_id = f"https://arxiv.org/abs/{arxiv_id}"
        out["arxiv_url"] = arxiv_id
    oa = best.get("openAccessPdf")
    if oa and isinstance(oa, dict) and oa.get("url"):
        out["open_access_pdf"] = oa["url"]
    return out


def search_arxiv(title: str) -> Optional[str]:
    """Search arXiv by title. Returns arxiv URL if found."""
    try:
        query = _clean_title(title).replace("-", " ")
        q = urllib.parse.quote(f"ti:{query[:200]}")
        req = urllib.request.Request(
            f"http://export.arxiv.org/api/query?search_query={q}&start=0&max_results=5",
            headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            tree = ET.parse(resp)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = tree.getroot().findall("atom:entry", ns)
        for entry in entries:
            ti = entry.find("atom:title", ns)
            if ti is not None and ti.text:
                t = ti.text.replace("\n", " ").strip()
                def norm(s: str) -> str:
                    return re.sub(r"[^a-z0-9]", "", s.lower())
                if norm(t)[:30] in norm(query) or norm(query)[:30] in norm(t):
                    id_e = entry.find("atom:id", ns)
                    if id_e is not None and id_e.text:
                        return id_e.text.strip()
        return None
    except Exception as e:
        print(f"  [arXiv] {e}")
        return None


def search_github(title: str) -> Optional[str]:
    """Search GitHub for repositories matching paper title. Returns top repo URL or None."""
    try:
        query = _clean_title(title).replace("-", " ")
        q = urllib.parse.quote(query[:100])
        req = urllib.request.Request(
            f"https://api.github.com/search/repositories?q={q}+in:name,description&sort=stars&per_page=5",
            headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github.v3+json"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        items = data.get("items", [])
        if not items:
            return None
        # Prefer repos with high stars and name/description containing key terms
        top = items[0]
        return top.get("html_url")
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print("  [GitHub] Rate limited; skipping GitHub search")
        else:
            print(f"  [GitHub] {e}")
        return None
    except Exception as e:
        print(f"  [GitHub] {e}")
        return None


def get_bibtex_string(bibdata: Any, bib_id: str) -> str:
    """Export single bibtex entry as string."""
    try:
        entry = bibdata.entries.get(bib_id)
        if entry is None:
            return ""
        single = BibliographyData({bib_id: entry})
        return single.to_string("bibtex").strip()
    except Exception as e:
        print(f"  [BibTeX] {e}")
        return ""


def _compute_pub_date(fields: Dict[str, Any]) -> str:
    pub_year = "1900"
    pub_month = "01"
    pub_day = "01"
    pub_year = f'{fields["year"]}'
    if "month" in fields.keys():
        if len(fields["month"]) < 3:
            pub_month = ("0" + fields["month"])[-2:]
        elif fields["month"] not in range(12):
            tmnth = strptime(fields["month"][:3], "%b").tm_mon
            pub_month = "{:02d}".format(tmnth)
        else:
            pub_month = str(fields["month"])
    if "day" in fields.keys():
        pub_day = str(fields["day"])
    return pub_year + "-" + pub_month + "-" + pub_day


def _make_slugs(pub_date: str, title: str) -> Tuple[str, str]:
    clean_title_slug = title.replace("{", "").replace("}", "").replace("\\", "").replace(" ", "-")
    url_slug = re.sub("\\[.*\\]|[^a-zA-Z0-9_-]", "", clean_title_slug).replace("--", "-")
    md_filename = os.path.basename((str(pub_date) + "-" + url_slug + ".md").replace("--", "-"))
    html_filename = (str(pub_date) + "-" + url_slug).replace("--", "-")
    return md_filename, html_filename


def _format_authors(entry: Any) -> List[str]:
    authors: List[str] = []
    for author in entry.persons["author"]:
        authors.append(author.first_names[0] + " " + author.last_names[0])
    return authors


def _build_citation(authors: List[str], title: str, venue: str, year: str) -> str:
    citation = ", ".join(authors) + "; "
    citation += "\"" + html_escape(title) + ".\""
    citation += " " + html_escape(venue) + ", " + year + "."
    return citation


def _maybe_fetch_links(title: str, *, skip_api: bool, s2_delay: float) -> Tuple[Dict[str, Any], Optional[str], Optional[str]]:
    if skip_api:
        return {}, None, None

    s2: Dict[str, Any] = {}
    arxiv_url: Optional[str] = None
    github_url: Optional[str] = None

    try:
        s2 = search_semantic_scholar(title)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"  [S2] 429 rate limit for \"{title[:50]}...\" - skipped. Tip: set S2_API_KEY or increase S2_DELAY.")
        else:
            print(f"  [S2] {e.code} for \"{title[:50]}...\"")
    except Exception as e:
        print(f"  [S2] {e} for \"{title[:50]}...\"")

    if not s2.get("paperId"):
        print(f"  [S2] No semantic_scholar_id found: \"{title[:60]}{'...' if len(title) > 60 else ''}\"")

    arxiv_url = s2.get("arxiv_url")
    if not arxiv_url:
        arxiv_url = search_arxiv(title)
    github_url = search_github(title)
    time.sleep(s2_delay)
    return s2, arxiv_url, github_url


def _write_bibtex_file(html_filename: str, bibtex_str: str) -> Optional[str]:
    if not bibtex_str:
        return None
    BIBTEX_OUT_DIR.mkdir(parents=True, exist_ok=True)
    bibtex_filename = html_filename + ".bib"
    bibtex_path = BIBTEX_OUT_DIR / bibtex_filename
    bibtex_path.write_text(bibtex_str, encoding="utf-8")
    return "/files/bibtex/" + bibtex_filename


def generate_from_bibs(
    *,
    skip_api: bool,
    s2_delay: float,
    publist_cfg: Dict[str, Any] = publist,
) -> List[str]:
    existing_corresponding = load_corresponding_authors()
    # When a paper's permalink slug changes (e.g. punctuation tweaks), preserve
    # the corresponding-author annotations by using a canonical lookup.
    def canonical_slug(slug: str) -> str:
        # Keep only alphanumerics for matching; this is intentionally lossy.
        return re.sub(r"[^a-z0-9]", "", slug.lower())

    existing_canonical: Dict[str, List[str]] = {}
    for k, v in existing_corresponding.items():
        existing_canonical.setdefault(canonical_slug(k), v)
    all_slugs: List[str] = []

    for pubsource in publist_cfg:
        parser = bibtex.Parser()
        bib_path = (SCRIPT_DIR / publist_cfg[pubsource]["file"]).resolve()
        bibdata = parser.parse_file(str(bib_path))

        for bib_id in bibdata.entries:
            b = bibdata.entries[bib_id].fields
            try:
                pub_date = _compute_pub_date(b)
                raw_title = b["title"].replace("{", "").replace("}", "").replace("\\", "")
                md_filename, html_filename = _make_slugs(pub_date, raw_title)

                authors = _format_authors(bibdata.entries[bib_id])
                venue = publist_cfg[pubsource]["venue-pretext"] + b[publist_cfg[pubsource]["venuekey"]].replace("{", "").replace("}", "").replace("\\", "")
                citation = _build_citation(authors, raw_title, venue, str(b["year"]))

                note = bool("note" in b.keys() and len(str(b["note"])) > 5)

                s2, arxiv_url, github_url = _maybe_fetch_links(raw_title, skip_api=skip_api, s2_delay=s2_delay)

                # Build and write md
                md = "---\ntitle: \"" + html_escape(raw_title) + '"\n'
                md += "collection: " + publist_cfg[pubsource]["collection"]["name"]
                md += "\npermalink: " + publist_cfg[pubsource]["collection"]["permalink"] + html_filename

                if note:
                    md += "\nexcerpt: '" + html_escape(b["note"]) + "'"
                md += "\ndate: " + pub_date
                md += "\nvenue: '" + html_escape(venue) + "'"

                paperurl: Optional[str] = None
                if "url" in b.keys() and len(str(b["url"])) > 5:
                    paperurl = b["url"]
                if arxiv_url:
                    paperurl = arxiv_url
                elif not paperurl and s2.get("open_access_pdf"):
                    paperurl = s2["open_access_pdf"]
                if paperurl:
                    md += "\npaperurl: '" + paperurl + "'"

                if s2.get("paperId"):
                    md += "\nsemantic_scholar_id: '" + s2["paperId"] + "'"
                if arxiv_url:
                    md += "\narxiv: '" + arxiv_url + "'"
                if github_url:
                    md += "\ngithub: '" + github_url + "'"

                md += "\ncitation: '" + html_escape(citation) + "'"

                bibtex_str = get_bibtex_string(bibdata, bib_id)
                bibtexurl = _write_bibtex_file(html_filename, bibtex_str)
                if bibtexurl:
                    md += "\nbibtexurl: '" + bibtexurl + "'"

                md += "\n---"
                if note:
                    md += "\n" + html_escape(b["note"]) + "\n"

                PUBLICATIONS_DIR.mkdir(parents=True, exist_ok=True)
                (PUBLICATIONS_DIR / md_filename).write_text(md, encoding="utf-8")
                all_slugs.append(html_filename)
                print(f'SUCCESSFULLY PARSED {bib_id}: "{b["title"][:60]}{"..." if len(b["title"]) > 60 else ""}"')

            except KeyError as e:
                print(f'WARNING Missing Expected Field {e} from entry {bib_id}: "{b.get("title","")[:30]}..."')
                continue

    # Deduplicate slugs (same paper may appear in both proceedings and journal)
    all_slugs = list(dict.fromkeys(all_slugs))
    merged: Dict[str, List[str]] = {}
    for slug in all_slugs:
        authors = existing_corresponding.get(slug)
        if authors is None:
            authors = existing_canonical.get(canonical_slug(slug), [])
        merged[slug] = authors
    save_corresponding_authors(merged, all_slugs)
    return all_slugs


# Set SKIP_API=1 to skip Semantic Scholar/arXiv/GitHub lookups (faster run)
SKIP_API = os.environ.get("SKIP_API", "0") == "1"

# S2 rate limit: without API key = 100 req/5min (~3.5s between requests)
# https://api.semanticscholar.org/ - use S2_API_KEY env for higher limits
S2_DELAY = float(os.environ.get("S2_DELAY", "4"))  # seconds between requests (>=3.5 to avoid 429)

# User-Agent for API requests; set USER_AGENT env to override
USER_AGENT = os.environ.get(
    "USER_AGENT",
    "Mozilla/5.0 (compatible; AcademicPages/1.0; +https://github.com/academicpages)",
)


def main() -> int:
    generate_from_bibs(skip_api=SKIP_API, s2_delay=S2_DELAY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
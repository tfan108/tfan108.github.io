#!/usr/bin/env python3
"""
个人主页生成器
==============

    python build.py            # 生成网站到 _site/
    python build.py --serve    # 生成并在 http://localhost:8000 预览，改数据文件后自动重建

日常更新只需要改 data/ 目录下的 YAML / Markdown 文件，本文件一般不用动。
依赖：pip install -r requirements.txt  （PyYAML、Jinja2、Markdown，可选 Pillow）
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import shutil
import sys
import threading
import time
import unicodedata
from pathlib import Path

import markdown as _markdown
import yaml
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

try:  # Pillow 可选：用于自动裁剪/压缩成员照片和论文缩略图
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    Image = None

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"
OUT = ROOT / "_site"

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


# =============================================================================
#  错误收集
# =============================================================================
class Report:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def error(self, where: str, msg: str):
        self.errors.append(f"✗ {where}: {msg}")

    def warn(self, where: str, msg: str):
        self.warnings.append(f"! {where}: {msg}")

    def info(self, msg: str):
        self.infos.append(msg)


class BuildError(Exception):
    pass


# =============================================================================
#  YAML 读取（带行号，便于报错定位）
# =============================================================================
class _LineLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader, node, deep=False):
    mapping = yaml.SafeLoader.construct_mapping(loader, node, deep=deep)
    mapping["__line__"] = node.start_mark.line + 1
    return mapping


_LineLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def load_yaml(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise BuildError(f"找不到文件 {path.relative_to(ROOT)}")
    try:
        return yaml.load(text, Loader=_LineLoader)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        pos = f"第 {mark.line + 1} 行" if mark else ""
        raise BuildError(
            f"{path.relative_to(ROOT)} {pos} YAML 格式错误：{getattr(e, 'problem', e)}\n"
            "  常见原因：缩进不对齐（只能用空格，不能用 Tab）；标题里有英文冒号却没加双引号；列表的 - 后面少了空格。"
        )


def strip_lines(obj):
    """去掉 _LineLoader 附加的 __line__ 字段。"""
    if isinstance(obj, dict):
        return {k: strip_lines(v) for k, v in obj.items() if k != "__line__"}
    if isinstance(obj, list):
        return [strip_lines(v) for v in obj]
    return obj


def check_keys(rep: Report, where: str, obj: dict, allowed: set[str]):
    for k in obj:
        if k != "__line__" and k not in allowed:
            rep.warn(where, f"未知字段 “{k}”（是不是拼写错了？可用字段：{', '.join(sorted(allowed))}）")


# =============================================================================
#  文本工具
# =============================================================================
_md = _markdown.Markdown(extensions=["extra", "sane_lists", "smarty"], output_format="html")


_EMOJI_START = re.compile(r"<li>\s*[\u2190-\u2BFF\U0001F000-\U0001FAFF]")


def md(text: str | None) -> Markup:
    if not text:
        return Markup("")
    _md.reset()
    out = _md.convert(str(text))

    # 每一项都以 emoji 开头的列表，不再显示圆点
    def _plain(m):
        block = m.group(0)
        lis = block.count("<li>")
        return block.replace("<ul>", '<ul class="plain">', 1) if lis and len(_EMOJI_START.findall(block)) == lis else block
    out = re.sub(r"<ul>.*?</ul>", _plain, out, flags=re.S)
    return Markup(out)


def md_inline(text: str | None) -> Markup:
    s = str(md(text)).strip()
    if s.startswith("<p>") and s.endswith("</p>") and s.count("<p>") == 1:
        s = s[3:-4]
    return Markup(s)


def norm_title(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").lower()
    return re.sub(r"[^a-z0-9]", "", s)


def slugify(s: str, maxlen: int = 48) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:maxlen].strip("-") or "item"


def paper_slug(title: str) -> str:
    """论文锚点：冒号前的简称（如 tag-moe），否则取标题前几个词。"""
    head = title.split(":")[0].strip()
    if 2 <= len(head) <= 24 and ":" in title:
        return slugify(head)
    out = []
    for w in slugify(title, 200).split("-"):
        if out and len("-".join(out + [w])) > 34:
            break
        out.append(w)
    return "-".join(out)


def as_list(v) -> list:
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in re.split(r",|\band\b", str(v)) if x.strip()]


# =============================================================================
#  BibTeX：解析（用于自动补全字段）与生成
# =============================================================================
_LATEX = {
    r'\"a': "ä", r'\"o': "ö", r'\"u': "ü", r'\"A': "Ä", r'\"O': "Ö", r'\"U': "Ü", r"\'e": "é", r"\'a": "á",
    r"\'o": "ó", r"\'i": "í", r"\'u": "ú", r"\`e": "è", r"\`a": "à", r"\^o": "ô", r"\~n": "ñ", r"\c{c}": "ç",
    r"\ss": "ß", r"\&": "&", r"\%": "%", r"\_": "_", "--": "–",
}


def _delatex(s: str) -> str:
    for k, v in _LATEX.items():
        s = s.replace("{" + k + "}", v).replace(k, v)
    s = re.sub(r"\\[a-zA-Z]+\s*", "", s)
    return re.sub(r"\s+", " ", s.replace("{", "").replace("}", "")).strip()


def parse_bibtex(text: str) -> dict | None:
    m = re.search(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text)
    if not m:
        return None
    out = {"_type": m.group(1).lower(), "_key": m.group(2)}
    i, n = m.end(), len(text)
    while i < n:
        fm = re.compile(r"\s*([A-Za-z_\-]+)\s*=\s*").match(text, i)
        if not fm:
            break
        name, i = fm.group(1).lower(), fm.end()
        if i < n and text[i] == "{":
            depth, j = 0, i
            while j < n:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            val, i = text[i + 1:j], j + 1
        elif i < n and text[i] == '"':
            j = i + 1
            depth = 0
            while j < n and not (text[j] == '"' and depth == 0):
                depth += {"{": 1, "}": -1}.get(text[j], 0)
                j += 1
            val, i = text[i + 1:j], j + 1
        else:
            vm = re.compile(r"[^,}\s]+").match(text, i)
            val, i = (vm.group(0), vm.end()) if vm else ("", i)
        out[name] = _delatex(val)
        cm = re.compile(r"\s*,").match(text, i)
        if cm:
            i = cm.end()
    return out


def bib_authors(s: str) -> list[str]:
    names = []
    for a in re.split(r"\s+and\s+", s):
        a = a.strip()
        if not a or a.lower() == "others":
            continue
        if "," in a:
            last, first = a.split(",", 1)
            a = f"{first.strip()} {last.strip()}"
        names.append(a)
    return names


def make_bibtex(p: dict) -> str:
    def last_first(name: str) -> str:
        parts = name.split()
        return f"{parts[-1]}, {' '.join(parts[:-1])}" if len(parts) > 1 else name

    first_last = p["authors"][0].split()[-1].lower() if p["authors"] else "anon"
    word = next((w for w in re.findall(r"[A-Za-z0-9]+", p["title"]) if w.lower() not in {"a", "an", "the", "on", "of"}), "paper")
    key = re.sub(r"[^a-z0-9]", "", f"{first_last}{p['year']}{word.lower()}")
    v = p["venue_info"]
    fields = [("title", p["title"]), ("author", " and ".join(last_first(a) for a in p["authors"]))]
    if v["type"] == "journal":
        kind = "article"
        fields.append(("journal", v["name"]))
    elif v["type"] == "preprint":
        kind = "article"
        arx = re.search(r"(\d{4}\.\d{4,5})", p["links"].get("arxiv", ""))
        fields.append(("journal", f"arXiv preprint arXiv:{arx.group(1)}" if arx else v["name"]))
    else:
        kind = "inproceedings"
        fields.append(("booktitle", v["name"]))
    fields.append(("year", str(p["year"])))
    body = ",\n".join(f"  {k:<9} = {{{val}}}" for k, val in fields)
    return f"@{kind}{{{key},\n{body}\n}}"


# =============================================================================
#  数据加载与校验
# =============================================================================
VENUE_TYPES = {"conference", "journal", "preprint", "poster", "workshop", "book", "other"}
LINK_META = {  # key: (显示文字, 图标)
    "pdf": ("PDF", "file-pdf"), "paper": ("Paper", "file-pdf"), "arxiv": ("arXiv", "file-lines"),
    "code": ("Code", "github"), "project": ("Project", "globe"), "video": ("Video", "circle-play"),
    "demo": ("Demo", "circle-play"), "slides": ("Slides", "images"), "poster": ("Poster", "images"),
    "doi": ("DOI", "link"), "dataset": ("Dataset", "book"), "huggingface": ("Hugging Face", "link"),
    "openreview": ("OpenReview", "link"), "supp": ("Supp.", "file-lines"), "blog": ("Blog", "newspaper"),
}
PAPER_KEYS = {"title", "authors", "corresponding", "equal", "venue", "year", "note", "links", "scholar",
              "image", "bibtex", "hidden", "id", "abstract"}


def load_site(rep: Report) -> dict:
    site = load_yaml(DATA / "site.yml") or {}
    for k in ("title", "url", "author", "nav"):
        if not site.get(k):
            rep.error("site.yml", f"缺少必填字段 {k}")
    site = strip_lines(site)
    site["me"] = as_list(site.get("me")) or [site.get("author", {}).get("name", "")]
    site.setdefault("home", {})
    site.setdefault("publications", {})
    site.setdefault("team", {})
    return site


def load_venues(rep: Report) -> tuple[dict, dict]:
    raw = load_yaml(DATA / "venues.yml") or {}
    venues, lookup = {}, {}
    for order, (key, v) in enumerate((k, v) for k, v in raw.items() if k != "__line__"):
        where = f"venues.yml 第 {v.get('__line__', '?')} 行 “{key}”" if isinstance(v, dict) else f"venues.yml “{key}”"
        if not isinstance(v, dict):
            rep.error(where, "格式应为 “键名:” 下面缩进写 name / type / rank")
            continue
        check_keys(rep, where, v, {"name", "type", "rank", "aliases", "label"})
        if not v.get("name"):
            rep.error(where, "缺少 name（全称）")
        vtype = str(v.get("type") or "").strip().lower()
        if vtype not in VENUE_TYPES:
            rep.error(where, f"type 应为 {' / '.join(sorted(VENUE_TYPES))} 之一，当前为 “{v.get('type')}”")
        info = {"key": str(key), "label": str(v.get("label") or key), "name": str(v.get("name") or key),
                "type": vtype, "rank": str(v.get("rank") or "").strip(), "order": order}
        venues[str(key)] = info
        for alias in [key] + as_list(v.get("aliases")):
            a = str(alias).strip().lower()
            if a in lookup and lookup[a]["key"] != info["key"]:
                rep.warn(where, f"别名 “{alias}” 与 “{lookup[a]['key']}” 重复")
            lookup[a] = info
    return venues, lookup


def load_papers(rep: Report, site: dict, venue_lookup: dict) -> list[dict]:
    raw = load_yaml(DATA / "papers.yml") or []
    if not isinstance(raw, list):
        raise BuildError("papers.yml 应该是一个列表（每篇论文以 “- title:” 开头）")
    papers, seen_titles, seen_ids = [], {}, set()
    for idx, r in enumerate(raw):
        if not isinstance(r, dict):
            rep.error(f"papers.yml 第 {idx + 1} 篇", "格式错误，每篇论文应以 “- title: ...” 开头，其余字段缩进两个空格")
            continue
        line = r.get("__line__", "?")
        bib = parse_bibtex(r["bibtex"]) if r.get("bibtex") else None
        if r.get("bibtex") and not bib:
            rep.warn(f"papers.yml 第 {line} 行", "bibtex 无法解析，已原样保留")
        title = str(r.get("title") or (bib or {}).get("title") or "").strip()
        where = f"papers.yml 第 {line} 行《{title[:50] or '无标题'}》"
        check_keys(rep, where, r, PAPER_KEYS)
        if r.get("hidden"):
            continue
        if not title:
            rep.error(where, "缺少 title（或在 bibtex 中提供 title）")
        authors = as_list(r.get("authors")) or (bib_authors(bib["author"]) if bib and bib.get("author") else [])
        if not authors:
            rep.error(where, "缺少 authors（作者列表），格式如 authors: [Zhang San, Fan Tang]")
        year = r.get("year") or (bib or {}).get("year")
        try:
            year = int(str(year)[:4])
        except (TypeError, ValueError):
            rep.error(where, f"year 应为四位年份，当前为 “{year}”")
            year = 0
        vkey = str(r.get("venue") or "").strip()
        vinfo = venue_lookup.get(vkey.lower())
        if not vkey:
            rep.error(where, "缺少 venue（会议/期刊名，需在 venues.yml 中存在）")
        elif not vinfo:
            rep.error(where, f"venue “{vkey}” 不在 venues.yml 中。请先在 data/venues.yml 里添加这个会议/期刊，"
                             f"或改用已有名字（如 {', '.join(list(dict.fromkeys(v['key'] for v in venue_lookup.values()))[:8])} …）")
        corresponding = as_list(r.get("corresponding"))
        equal = as_list(r.get("equal"))
        for label, names in (("corresponding", corresponding), ("equal", equal)):
            for nme in names:
                if nme not in authors:
                    rep.error(where, f"{label} 里的 “{nme}” 不在 authors 中（名字写法必须完全一致）")
        links_raw = r.get("links") or {}
        links = {}
        if not isinstance(links_raw, dict):
            rep.error(where, "links 格式应为缩进的 “名称: 网址” 列表")
        else:
            for k, v in links_raw.items():
                if k == "__line__" or v in (None, ""):
                    continue
                v = str(v).strip()
                if not (v.startswith("http://") or v.startswith("https://") or v.startswith("/")):
                    rep.error(where, f"links.{k} 应该是以 http(s):// 或 / 开头的网址，当前为 “{v}”")
                links[str(k).lower()] = v
        repo = None
        if links.get("code"):
            gm = re.match(r"https?://github\.com/([^/\s]+/[^/\s#?]+)", links["code"])
            if gm:
                repo = gm.group(1).removesuffix(".git")
        pid = str(r.get("id") or "") or f"{paper_slug(title)}-{year}"
        base, k = pid, 2
        while pid in seen_ids:
            pid, k = f"{base}-{k}", k + 1
        seen_ids.add(pid)
        nt = norm_title(title)
        if nt and nt in seen_titles:
            rep.warn(where, f"与第 {seen_titles[nt]} 行的论文标题重复")
        seen_titles[nt] = line
        p = {
            "id": pid, "title": title, "authors": authors, "corresponding": corresponding, "equal": equal,
            "venue_key": vinfo["key"] if vinfo else vkey, "venue_info": vinfo or {"key": vkey, "label": vkey, "name": vkey, "type": "other", "rank": "", "order": 999},
            "year": year, "note": str(r.get("note") or "").strip(), "links": links, "repo": repo,
            "scholar": str(r.get("scholar") or "").split(":")[-1].strip(), "image": r.get("image"),
            "abstract": r.get("abstract"), "index": idx, "line": line,
            "is_mine": any(m in corresponding for m in site["me"]),
        }
        p["bibtex"] = (r.get("bibtex") or "").strip() or make_bibtex(p)
        papers.append(p)
    return papers


def load_news(rep: Report) -> list[dict]:
    raw = load_yaml(DATA / "news.yml") or []
    items = []
    for i, r in enumerate(raw):
        where = f"news.yml 第 {r.get('__line__', '?') if isinstance(r, dict) else i + 1} 行"
        if not isinstance(r, dict):
            rep.error(where, "每条新闻应以 “- date: ...” 开头")
            continue
        check_keys(rep, where, r, {"date", "text", "icon", "link", "pin"})
        d = r.get("date")
        if isinstance(d, (dt.date, dt.datetime)):
            date, precision = dt.date(d.year, d.month, d.day), "day"
        else:
            m = re.fullmatch(r"\s*(\d{4})[-./](\d{1,2})(?:[-./](\d{1,2}))?\s*", str(d or ""))
            if not m:
                rep.error(where, f"date 格式应为 2026-09-25 或 2026-09，当前为 “{d}”")
                continue
            try:
                date = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
            except ValueError:
                rep.error(where, f"date “{d}” 不是有效日期")
                continue
            precision = "day" if m.group(3) else "month"
        if not r.get("text"):
            rep.error(where, "缺少 text（新闻内容）")
            continue
        text = str(r["text"])
        if r.get("link"):
            text += f" [→]({r['link']})"
        items.append({"date": date, "precision": precision, "icon": r.get("icon") or "",
                      "html": md_inline(text), "pin": bool(r.get("pin"))})
    items.sort(key=lambda x: x["date"], reverse=True)
    return items


DEFAULT_SINGULAR = {"faculty": "Faculty", "postdoc": "Postdoctoral Researcher", "phd": "Ph.D. Student",
                    "master": "Master Student", "intern": "Research Intern", "alumni": "Alumni"}


def load_members(rep: Report, site: dict) -> list[dict]:
    raw = load_yaml(DATA / "members.yml") or []
    groups = {g["key"]: g for g in site["team"].get("groups", [])}
    out = []
    for i, r in enumerate(raw):
        where = f"members.yml 第 {r.get('__line__', '?') if isinstance(r, dict) else i + 1} 行"
        if not isinstance(r, dict):
            rep.error(where, "每位成员应以 “- name: ...” 开头")
            continue
        check_keys(rep, where, r, {"name", "name_zh", "role", "photo", "since", "title", "research", "experience",
                                   "links", "bio", "graduated", "destination", "hidden"})
        if r.get("hidden"):
            continue
        if not r.get("name"):
            rep.error(where, "缺少 name")
            continue
        role = str(r.get("role") or "").strip().lower()
        if role not in groups:
            rep.error(where, f"role “{r.get('role')}” 无效，应为 {' / '.join(groups)} 之一（在 site.yml → team.groups 定义）")
            continue
        m = strip_lines(r)
        m["role"] = role
        m["research"] = as_list(m.get("research"))
        m["experience"] = [str(x) for x in (m.get("experience") or [])]
        m["links"] = m.get("links") or {}
        m["initials"] = "".join(w[0] for w in str(m["name"]).split()[:2]).upper()
        if not m.get("title"):
            singular = groups[role].get("singular") or DEFAULT_SINGULAR.get(role, groups[role]["title"])
            since = f" · since {m['since']}" if m.get("since") and role != "alumni" else ""
            m["title"] = singular + since
        out.append(m)
    return out


def load_cv(rep: Report) -> list[dict]:
    raw = load_yaml(DATA / "cv.yml") or []
    out = []
    for s in raw:
        where = f"cv.yml 第 {s.get('__line__', '?')} 行"
        check_keys(rep, where, s, {"section", "icon", "items"})
        sec = {"section": s.get("section", ""), "icon": s.get("icon"), "items": []}
        for it in s.get("items") or []:
            check_keys(rep, f"cv.yml 第 {it.get('__line__', '?')} 行", it, {"title", "role", "org", "date", "badge", "details"})
            it = strip_lines(it)
            it["details"] = [md_inline(d) for d in (it.get("details") or [])]
            sec["items"].append(it)
        out.append(sec)
    return out


def load_metrics(rep: Report) -> dict:
    p = DATA / "metrics.json"
    if not p.exists():
        rep.warn("metrics.json", "不存在，引用数和 star 数暂不显示（会由 GitHub Actions 每天自动生成）")
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        rep.warn("metrics.json", f"格式损坏（{e}），引用数和 star 数暂不显示")
        return {}


# =============================================================================
#  引用数匹配（按 Scholar id 或标题）
# =============================================================================
def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", s.lower())))


def attach_metrics(rep: Report, papers: list[dict], metrics: dict, site: dict):
    sch = metrics.get("scholar") or {}
    rows = sch.get("papers") or []
    by_id = {r["id"]: r for r in rows if r.get("id")}
    by_title = {norm_title(r.get("title", "")): r for r in rows}
    stars = (metrics.get("github") or {}).get("stars") or {}
    stars_ci = {k.lower(): v for k, v in stars.items()}
    used = set()
    unmatched = []
    for p in papers:
        row = by_id.get(p["scholar"]) if p["scholar"] else None
        if not row:
            row = by_title.get(norm_title(p["title"]))
        if not row and rows:
            tp = _tokens(p["title"])
            best, score = None, 0.0
            for r in rows:
                tr = _tokens(r.get("title", ""))
                if not tp or not tr:
                    continue
                j = len(tp & tr) / len(tp | tr)
                if j > score:
                    best, score = r, j
            if best and score >= 0.8:
                row = best
        if row:
            used.add(row.get("id"))
            p["cites"] = int(row.get("cites") or 0)
            pid = sch.get("profile_id") or site.get("scholar_id")
            p["scholar_url"] = f"https://scholar.google.com/citations?view_op=view_citation&hl=en&user={pid}&citation_for_view={pid}:{row['id']}" if pid and row.get("id") else None
        else:
            p["cites"], p["scholar_url"] = None, None
            if rows and p["venue_info"]["type"] != "poster":
                unmatched.append(p)
        p["stars"] = stars_ci.get(p["repo"].lower()) if p["repo"] else None
    if unmatched:
        rep.info("以下论文没在 Google Scholar 数据里匹配到引用数（标题差异较大时，可在 papers.yml 里给它加 scholar: <id>）：")
        for p in unmatched:
            rep.info(f"    · papers.yml 第 {p['line']} 行  {p['title'][:80]}")
    extra = [r for r in rows if r.get("id") not in used]
    if extra and rows:
        rep.info(f"Google Scholar 上有 {len(extra)} 篇论文不在 papers.yml 中（可能需要补录，也可能是你不想列出的）：")
        for r in sorted(extra, key=lambda r: -int(r.get("year") or 0))[:40]:
            rep.info(f"    · {r.get('year') or '    '}  {r.get('title', '')[:90]}")


# =============================================================================
#  论文页分组
# =============================================================================
def group_papers(papers: list[dict], site: dict) -> list[dict]:
    merge_before = int(site["publications"].get("merge_before") or 0)
    sort_key = lambda p: (p["venue_info"]["order"], 0 if p["is_mine"] else 1, p["index"])
    groups = []
    pre = sorted([p for p in papers if p["venue_info"]["type"] == "preprint"], key=lambda p: (-p["year"], sort_key(p)))
    if pre:
        groups.append({"title": "Preprints", "id": "preprints", "papers": pre})
    pubs = [p for p in papers if p["venue_info"]["type"] != "preprint"]
    years = sorted({p["year"] for p in pubs}, reverse=True)
    for y in years:
        if merge_before and y <= merge_before:
            continue
        groups.append({"title": str(y), "id": f"y{y}", "papers": sorted([p for p in pubs if p["year"] == y], key=sort_key)})
    old = [p for p in pubs if merge_before and p["year"] <= merge_before]
    if old:
        groups.append({"title": f"{merge_before} and earlier", "id": f"y{merge_before}-", "papers": sorted(old, key=lambda p: (-p["year"], sort_key(p)))})
    return groups


def find_papers(papers: list[dict], queries: list[str], rep: Report, where: str) -> list[dict]:
    out = []
    for q in queries:
        nq = norm_title(q)
        hit = next((p for p in papers if norm_title(p["title"]).startswith(nq)), None) or \
            next((p for p in papers if nq in norm_title(p["title"])), None)
        if hit:
            out.append(hit)
        else:
            rep.warn(where, f"找不到标题以 “{q}” 开头的论文")
    return out


# =============================================================================
#  图片处理（自动裁剪/压缩）
# =============================================================================
def make_thumb(src_url: str | None, size: tuple[int, int], rep: Report, where: str, square: bool = False) -> str | None:
    if not src_url:
        return None
    if src_url.startswith("http"):
        return src_url
    src = STATIC / src_url.lstrip("/")
    if not src.exists():
        rep.warn(where, f"图片不存在：static{src_url}")
        return None
    if Image is None:
        return src_url
    h = hashlib.md5(f"{src_url}{src.stat().st_mtime}{size}{square}".encode()).hexdigest()[:8]
    rel = f"images/_thumbs/{src.stem}-{h}.jpg"
    dst = OUT / rel
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
            if square:
                w, hgt = im.size
                side = min(w, hgt)
                left = (w - side) // 2
                # 竖幅照片取景偏上，保留头部
                top = int((hgt - side) * 0.2) if hgt > w else (hgt - side) // 2
                im = im.crop((left, top, left + side, top + side)).resize(size, Image.LANCZOS)
            else:
                im.thumbnail(size, Image.LANCZOS)
            im.save(dst, "JPEG", quality=86, optimize=True, progressive=True)
        except Exception as e:  # pragma: no cover
            rep.warn(where, f"图片处理失败（{e}），使用原图")
            return src_url
    return "/" + rel


# =============================================================================
#  渲染
# =============================================================================
def icon(name: str, cls: str = "") -> Markup:
    return Markup(f'<svg class="icon {cls}" aria-hidden="true"><use href="#i-{html.escape(name)}"/></svg>')


def fmt_num(n) -> str:
    if n is None:
        return ""
    n = int(n)
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def exp_split(line: str) -> tuple[str, str]:
    """把 “2022–now  Associate Professor” 拆成 (时间, 内容)。"""
    m = re.match(r"^\s*([\d][\d.\-–—~ /]*(?:now|present|至今|今)?)\s+(.+)$", str(line), re.I)
    return (m.group(1).strip(), m.group(2).strip()) if m else ("", str(line))


def build(serve_mode: bool = False) -> Report:
    rep = Report()
    site = load_site(rep)
    venues, vlookup = load_venues(rep)
    papers = load_papers(rep, site, vlookup)
    news = load_news(rep)
    members = load_members(rep, site)
    cv = load_cv(rep)
    metrics = load_metrics(rep)
    attach_metrics(rep, papers, metrics, site)

    if rep.errors:
        return rep

    if OUT.exists():
        for child in OUT.iterdir():
            if child.name == "images":
                for sub in child.iterdir():
                    if sub.name != "_thumbs":
                        shutil.rmtree(sub) if sub.is_dir() else sub.unlink()
            else:
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    OUT.mkdir(exist_ok=True)
    shutil.copytree(STATIC, OUT, dirs_exist_ok=True)

    # 衍生数据
    groups = group_papers(papers, site)
    for p in papers:
        p["thumb"] = make_thumb(p["image"], (480, 360), rep, f"papers.yml 第 {p['line']} 行")
        p["primary"] = next((p["links"][k] for k in ("pdf", "paper", "doi", "arxiv", "project") if p["links"].get(k)), None)
    team_groups = []
    for g in site["team"].get("groups", []):
        ms = [m for m in members if m["role"] == g["key"]]
        for m in ms:
            m["thumb"] = make_thumb(m.get("photo"), (360, 360), rep, f"members.yml {m['name']}", square=True)
            m["paper_count"] = sum(1 for p in papers if m["name"] in p["authors"])
        if ms:
            team_groups.append({**g, "members": ms})
    reps = []
    for r in site["home"].get("representative") or []:
        reps.append({**r, "text_html": md(r.get("text")),
                     "paper_objs": find_papers(papers, [str(x) for x in (r.get("papers") or [])], rep, f"site.yml 代表性工作 “{r.get('title')}”")})
    pinned = [n for n in news if n["pin"]]
    home_news = (pinned + [n for n in news if not n["pin"]])[: int(site["home"].get("news_count") or 8)]
    counted = [p for p in papers if p["venue_info"]["type"] in ("conference", "journal")]
    stats = {
        "papers": len(papers),
        "peer_reviewed": len(counted),
        "ccf_a": sum(1 for p in counted if p["venue_info"]["rank"].upper() == "CCF-A"),
        'trans': sum(1 for p in counted if p['venue_info']['name'].startswith(('IEEE Transactions', 'ACM Transactions'))),
        "with_code": sum(1 for p in papers if p["repo"]),
        "stars": sum(p["stars"] or 0 for p in papers),
    }
    scholar = metrics.get("scholar") or {}
    today = dt.date.today()

    # 资源版本号（避免浏览器缓存旧 CSS/JS）
    def asset(path: str) -> str:
        f = STATIC / path.lstrip("/")
        v = hashlib.md5(f.read_bytes()).hexdigest()[:8] if f.exists() else "0"
        return f"{path}?v={v}"

    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.filters.update(md=md, md_inline=md_inline, num=fmt_num, exp_split=exp_split)
    env.globals.update(icon=icon, asset=asset, site=site, scholar=scholar, metrics=metrics, stats=stats,
                       build_date=today, serve_mode=serve_mode, link_meta=LINK_META,
                       icons_svg=Markup((TEMPLATES / "partials" / "icons.svg").read_text(encoding="utf-8")))

    def render(tpl: str, out: str, **ctx):
        dst = OUT / out
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(env.get_template(tpl).render(page_url="/" + out.removesuffix("index.html"), **ctx), encoding="utf-8")

    intro = md((DATA / "pages" / "intro.md").read_text(encoding="utf-8")) if (DATA / "pages" / "intro.md").exists() else ""
    join = md((DATA / "pages" / "join-us.md").read_text(encoding="utf-8")) if (DATA / "pages" / "join-us.md").exists() else ""

    render("index.html", "index.html", page="home", title=None, intro=intro, join=join, news=home_news,
           news_total=len(news), reps=reps)
    render("publications.html", "publications/index.html", page="publications", title="Publications",
           groups=groups, papers=papers)
    render("team.html", "team/index.html", page="team", title="Team", team_groups=team_groups, join=join)
    render("news.html", "news/index.html", page="news", title="News", news=news)
    render("cv.html", "cv/index.html", page="cv", title="CV", cv=cv)
    render("404.html", "404.html", page="404", title="Page not found")

    # 旧网址跳转（保证以前被收录/分享的链接不失效）
    redirects = {"about": "/", "about.html": "/", "resume": "/cv/"}
    legacy = DATA / "legacy_redirects.yml"
    if legacy.exists():
        by_title = {norm_title(p["title"]): p for p in papers}
        for old, t in (strip_lines(load_yaml(legacy)) or {}).items():
            p = by_title.get(norm_title(t))
            redirects[old] = f"/publications/#{p['id']}" if p else "/publications/"
    for old, new in redirects.items():
        old = old.strip("/")
        targets = [OUT / old] if old.endswith(".html") else [OUT / f"{old}.html", OUT / old / "index.html"]
        for dst in targets:
            if dst.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(env.get_template("redirect.html").render(target=new), encoding="utf-8")

    # sitemap / robots
    base = site["url"].rstrip("/")
    urls = ["/", "/publications/", "/team/", "/news/", "/cv/"]
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{base}{u}</loc><lastmod>{today.isoformat()}</lastmod></url>\n" for u in urls)
        + "</urlset>\n", encoding="utf-8")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n", encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    if serve_mode:
        (OUT / "__build_id").write_text(str(time.time()), encoding="utf-8")
    rep.info(f"论文 {len(papers)} 篇（含 {len(papers) - len(counted)} 篇预印本/海报等）· 新闻 {len(news)} 条 · 成员 {len(members)} 人")
    return rep


def print_report(rep: Report, quiet: bool = False) -> bool:
    for line in rep.infos:
        if quiet and line.startswith("    ·"):
            continue
        print(line)
    for line in rep.warnings:
        print(line)
    if rep.errors:
        print("\n构建失败，请修正以下问题：")
        for line in rep.errors:
            print("  " + line)
        return False
    print(f"✓ 已生成网站 → {OUT.relative_to(ROOT)}/")
    return True


def run_build(serve_mode=False, quiet=False) -> bool:
    try:
        return print_report(build(serve_mode), quiet)
    except BuildError as e:
        print(f"\n构建失败：{e}")
        return False
    except Exception:
        import traceback
        traceback.print_exc()
        print("\n构建失败：出现了未预料的错误（见上方信息）。如果刚改过 data/ 里的文件，请先检查格式。")
        return False


# =============================================================================
#  本地预览
# =============================================================================
def serve(port: int, open_browser: bool = False):
    import functools
    import http.server
    import socketserver

    def snapshot():
        files = [p for d in (DATA, STATIC, TEMPLATES) for p in d.rglob("*") if p.is_file()]
        return {str(p): p.stat().st_mtime for p in files}

    def watcher():
        last = snapshot()
        while True:
            time.sleep(1)
            cur = snapshot()
            if cur != last:
                last = cur
                print(f"\n[{dt.datetime.now():%H:%M:%S}] 检测到修改，重新生成…")
                run_build(serve_mode=True, quiet=True)

    OUT.mkdir(exist_ok=True)
    threading.Thread(target=watcher, daemon=True).start()
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(QuietHandler, directory=str(OUT))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), handler) as httpd:
        print(f"\n预览地址：http://localhost:{port}   （修改 data/ 下的文件会自动重新生成并刷新页面，Ctrl+C 退出）")
        if open_browser:
            import webbrowser
            threading.Timer(0.8, lambda: webbrowser.open(f"http://localhost:{port}")).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


def main():
    ap = argparse.ArgumentParser(description="生成个人主页")
    ap.add_argument("--serve", action="store_true", help="生成后启动本地预览服务器，并在文件修改后自动重建")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--open", action="store_true", help="预览时自动打开浏览器")
    args = ap.parse_args()
    ok = run_build(serve_mode=args.serve)
    if args.serve:
        serve(args.port, args.open)
    elif not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()

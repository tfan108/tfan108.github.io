#!/usr/bin/env python3
"""
更新 data/metrics.json：Google Scholar 引用数 + GitHub star 数
================================================================

GitHub Actions 每天自动运行，一般不需要手动执行。手动运行：

    python scripts/update_metrics.py                # 全部更新
    python scripts/update_metrics.py --only github  # 只更新 star 数
    python scripts/update_metrics.py --only scholar # 只更新引用数

数据来源与容错：
  * Scholar：直接读取 Google Scholar 个人主页（site.yml → scholar_id）。
    GitHub 的服务器偶尔会被 Google 拦截；这时如果配置了 SERPAPI_KEY 环境变量，
    会改用 SerpAPI（serpapi.com，免费额度每月 100 次，足够每天一次）。
    都失败时保留上一次的数据，网站照常显示，不会清空。
  * GitHub：用 GitHub API 读取 papers.yml 中 links.code 指向的仓库 star 数。
    设置 GITHUB_TOKEN 环境变量可提高频率上限（Actions 里会自动提供）。
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "data" / "metrics.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0.0.0 Safari/537.36")

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def today() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()  # 北京时间


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# ---------------------------------------------------------------------------
#  Google Scholar
# ---------------------------------------------------------------------------
class Blocked(Exception):
    pass


def parse_scholar_page(text: str) -> tuple[list[dict], list[int]]:
    """解析 Scholar 个人主页 HTML，返回 (论文列表, [总引用, 近五年引用, h, 近五年h, i10, 近五年i10])。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(text, "html.parser")
    rows = []
    for tr in soup.select("tr.gsc_a_tr"):
        a = tr.select_one("a.gsc_a_at")
        if not a:
            continue
        for svg in a.find_all("svg"):  # 标题里的公式（如 A²Pt）以 SVG 显示，取其 aria-label
            svg.replace_with(re.sub(r"[{}^_\\]", "", svg.get("aria-label", "")))
        m = re.search(r"citation_for_view=[^:&]+:([^&]+)", a.get("href", "") or a.get("data-href", ""))
        cites_el = tr.select_one("a.gsc_a_ac")
        year_el = tr.select_one(".gsc_a_h")
        cites_txt = (cites_el.get_text(strip=True) if cites_el else "").replace(",", "").replace("*", "")
        year_txt = year_el.get_text(strip=True) if year_el else ""
        rows.append({
            "id": m.group(1) if m else "",
            "title": re.sub(r"\s+", " ", a.get_text("")).strip(),
            "cites": int(cites_txt) if cites_txt.isdigit() else 0,
            "year": int(year_txt) if year_txt.isdigit() else None,
        })
    stats = []
    for td in soup.select("#gsc_rsb_st td.gsc_rsb_std"):
        t = td.get_text(strip=True).replace(",", "")
        stats.append(int(t) if t.isdigit() else 0)
    return rows, stats


def fetch_scholar_direct(profile_id: str) -> dict:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    rows, stats, start = [], [], 0
    while True:
        url = f"https://scholar.google.com/citations?user={profile_id}&hl=en&cstart={start}&pagesize=100"
        r = s.get(url, timeout=30)
        low = r.text.lower()
        if r.status_code != 200 or "gs_captcha" in low or "unusual traffic" in low or "/sorry/" in r.url:
            raise Blocked(f"HTTP {r.status_code}，可能被 Google 拦截")
        page_rows, page_stats = parse_scholar_page(r.text)
        if start == 0:
            if not page_stats:
                raise Blocked("页面里没有找到引用统计，可能被拦截或页面结构变化")
            stats = page_stats
        rows += page_rows
        if len(page_rows) < 100:
            break
        start += 100
        time.sleep(random.uniform(2, 5))
    return {"papers": rows, "stats": stats, "source": "scholar.google.com"}


def fetch_scholar_serpapi(profile_id: str, key: str) -> dict:
    rows, stats, start = [], [], 0
    while True:
        r = requests.get("https://serpapi.com/search.json", timeout=60, params={
            "engine": "google_scholar_author", "author_id": profile_id, "hl": "en",
            "num": 100, "start": start, "api_key": key})
        r.raise_for_status()
        j = r.json()
        if j.get("error"):
            raise RuntimeError(j["error"])
        if start == 0:
            table = (j.get("cited_by") or {}).get("table") or []
            flat = {}
            for item in table:
                for k, v in item.items():
                    flat[k] = v
            def pair(k):
                v = flat.get(k) or {}
                vals = list(v.values())
                return [int(vals[0]) if vals else 0, int(vals[1]) if len(vals) > 1 else 0]
            stats = pair("citations") + pair("h_index") + pair("i10_index")
        arts = j.get("articles") or []
        for a in arts:
            cid = (a.get("citation_id") or "").split(":")[-1]
            year = str(a.get("year") or "")
            rows.append({"id": cid, "title": a.get("title", ""),
                         "cites": int((a.get("cited_by") or {}).get("value") or 0),
                         "year": int(year) if year.isdigit() else None})
        if len(arts) < 100:
            break
        start += 100
    return {"papers": rows, "stats": stats, "source": "serpapi.com"}


def update_scholar(metrics: dict, profile_id: str) -> tuple[bool, str]:
    old = metrics.get("scholar") or {}
    data, errors = None, []
    try:
        data = fetch_scholar_direct(profile_id)
    except Exception as e:
        errors.append(f"直接抓取失败：{e}")
        key = os.environ.get("SERPAPI_KEY")
        if key:
            try:
                data = fetch_scholar_serpapi(profile_id, key)
            except Exception as e2:
                errors.append(f"SerpAPI 失败：{e2}")
        else:
            errors.append("未配置 SERPAPI_KEY，跳过备用来源")
    if not data:
        return False, "；".join(errors) + "。保留上次的数据。"
    st = data["stats"] + [0] * 6
    if not data["papers"] or st[0] <= 0:
        return False, "抓到的数据为空，保留上次的数据。"
    if old.get("citations") and st[0] < old["citations"] * 0.7:
        return False, f"新数据总引用 {st[0]} 远低于上次的 {old['citations']}，疑似抓取不完整，保留上次的数据。"
    new = {
        "updated": today(), "fetched_at": now_iso(), "source": data["source"], "profile_id": profile_id,
        "citations": st[0], "citations_recent": st[1], "h_index": st[2], "h_index_recent": st[3],
        "i10_index": st[4], "i10_index_recent": st[5],
        "papers": sorted(data["papers"], key=lambda r: (-r["cites"], r["title"])),
    }
    changed = {k: v for k, v in new.items() if k not in ("updated", "fetched_at", "source")} != \
              {k: v for k, v in old.items() if k not in ("updated", "fetched_at", "source")}
    if not changed:
        new["updated"], new["fetched_at"] = old.get("updated", new["updated"]), old.get("fetched_at", new["fetched_at"])
    metrics["scholar"] = new
    delta = st[0] - int(old.get("citations") or 0)
    return True, f"总引用 {st[0]}（{'+' if delta >= 0 else ''}{delta}），h-index {st[2]}，{len(new['papers'])} 篇论文（来源 {data['source']}）"


# ---------------------------------------------------------------------------
#  GitHub stars
# ---------------------------------------------------------------------------
def code_repos() -> list[str]:
    papers = yaml.safe_load((ROOT / "data" / "papers.yml").read_text(encoding="utf-8")) or []
    repos = []
    for p in papers:
        url = str(((p or {}).get("links") or {}).get("code") or "")
        m = re.match(r"https?://github\.com/([^/\s]+/[^/\s#?]+)", url)
        if m:
            repo = m.group(1).removesuffix(".git")
            if repo not in repos:
                repos.append(repo)
    return repos


def update_github(metrics: dict) -> tuple[bool, str]:
    old = metrics.get("github") or {}
    old_stars = old.get("stars") or {}
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "homepage-metrics"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    stars, failed = {}, []
    for repo in code_repos():
        try:
            r = requests.get(f"https://api.github.com/repos/{repo}", headers=headers, timeout=20)
            if r.status_code == 200:
                stars[repo] = int(r.json().get("stargazers_count") or 0)
                continue
            failed.append(f"{repo}（HTTP {r.status_code}）")
        except Exception as e:
            failed.append(f"{repo}（{e}）")
        if repo in old_stars:
            stars[repo] = old_stars[repo]
    if not stars and failed:
        return False, "全部仓库都读取失败：" + "，".join(failed[:5])
    changed = stars != old_stars
    metrics["github"] = {
        "updated": today() if changed else old.get("updated", today()),
        "fetched_at": now_iso() if changed else old.get("fetched_at", now_iso()),
        "stars": dict(sorted(stars.items(), key=lambda kv: -kv[1])),
    }
    msg = f"{len(stars)} 个仓库，共 {sum(stars.values())} stars"
    if failed:
        msg += f"；{len(failed)} 个读取失败（沿用旧值）：{'，'.join(failed[:5])}{' …' if len(failed) > 5 else ''}"
    return True, msg


# ---------------------------------------------------------------------------
def pick_newer(other_path: Path) -> None:
    """CI 用：把另一份 metrics.json（metrics 分支上的）中更新的部分合并进来。"""
    cur, other = load_json(METRICS), load_json(other_path)
    merged = copy.deepcopy(cur)
    for sec in ("scholar", "github"):
        a, b = cur.get(sec) or {}, other.get(sec) or {}
        if b and (b.get("fetched_at") or "") > (a.get("fetched_at") or ""):
            merged[sec] = b
            print(f"· {sec}: 使用 metrics 分支上较新的数据（{b.get('updated')}）")
    if merged != cur:
        METRICS.write_text(json.dumps(merged, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["scholar", "github"])
    ap.add_argument("--pick-newer", metavar="FILE", help="合并另一份 metrics.json 中较新的部分后退出")
    args = ap.parse_args()
    if args.pick_newer:
        pick_newer(Path(args.pick_newer))
        return
    site = yaml.safe_load((ROOT / "data" / "site.yml").read_text(encoding="utf-8")) or {}
    metrics = load_json(METRICS)
    before = copy.deepcopy(metrics)
    lines = []
    if args.only in (None, "scholar"):
        pid = site.get("scholar_id")
        if pid:
            ok, msg = update_scholar(metrics, pid)
            lines.append(f"{'✓' if ok else '✗'} Google Scholar：{msg}")
        else:
            lines.append("· site.yml 中没有 scholar_id，跳过引用数")
    if args.only in (None, "github"):
        ok, msg = update_github(metrics)
        lines.append(f"{'✓' if ok else '✗'} GitHub：{msg}")
    for l in lines:
        print(l)
    if metrics != before:
        METRICS.write_text(json.dumps(metrics, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"已写入 {METRICS.relative_to(ROOT)}")
    else:
        print("数据无变化")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### 引用数 / star 数更新\n\n" + "\n".join(f"- {l}" for l in lines) + "\n")


if __name__ == "__main__":
    main()

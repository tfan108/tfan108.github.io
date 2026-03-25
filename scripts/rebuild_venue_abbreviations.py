from __future__ import annotations

import re
from pathlib import Path


RE_YML_ENTRY = re.compile(r'^"(.*)":\s*"(.*)"\s*$')


def read_existing_map(yml_path: Path) -> dict[str, str]:
    if not yml_path.exists():
        return {}
    m: dict[str, str] = {}
    for line in yml_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        mo = RE_YML_ENTRY.match(line)
        if not mo:
            continue
        key, val = mo.group(1), mo.group(2)
        # unescape quotes (minimal)
        key = key.replace('\\"', '"')
        val = val.replace('\\"', '"')
        m[key] = val
    return m


def extract_venues(publications_dir: Path) -> list[str]:
    venues: set[str] = set()
    for md_path in publications_dir.glob("*.md"):
        try:
            for line in md_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("venue:"):
                    v = line.split(":", 1)[1].strip().strip("'").strip('"').strip()
                    if v and ("arXiv" not in v):
                        venues.add(v)
                    break
        except UnicodeDecodeError:
            # skip weird-encoded files
            continue
    return sorted(venues)


def write_yml(yml_path: Path, venues: list[str], existing: dict[str, str]) -> None:
    header = [
        "# 用于在 publications 列表页显示“刊物简称/等级”前缀。",
        "# - key 必须与 publications 页每篇文章的 `venue` 字段完全一致",
        "# - value 填入你希望展示的简称内容（不含外层方括号 []）",
        "#",
        "",
    ]
    lines: list[str] = []
    lines.extend(header)
    for v in venues:
        abbr = existing.get(v, "")
        v_esc = v.replace('"', '\\"')
        abbr_esc = abbr.replace('"', '\\"')
        lines.append(f"\"{v_esc}\": \"{abbr_esc}\"")
    lines.append("")
    yml_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    publications_dir = repo_root / "_publications"
    yml_path = repo_root / "_data" / "venue_abbreviations.yml"

    if not publications_dir.exists():
        raise SystemExit(f"Missing directory: {publications_dir}")

    existing = read_existing_map(yml_path)
    venues = extract_venues(publications_dir)

    before_keys = set(existing.keys())
    after_keys = set(venues)
    removed = sorted(before_keys - after_keys)
    added = sorted(after_keys - before_keys)

    write_yml(yml_path, venues, existing)

    print(f"Rebuilt {yml_path} with {len(venues)} venues.")
    if added:
        print(f"Added {len(added)} new venues (abbr empty).")
    if removed:
        print(f"Removed {len(removed)} stale venues.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


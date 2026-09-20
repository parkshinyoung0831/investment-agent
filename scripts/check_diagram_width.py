"""각 SVG가 GitHub 본문 폭(약 830px)에서 실제로 몇 px 글자로 보이는지 잰다.

Archify는 1440px 뷰포트를 기준으로 가독성을 검사하지만 GitHub 본문은 그보다 훨씬 좁다.
Markdown이 SVG를 본문 폭에 맞춰 축소하므로 `viewBox` 폭이 곧 글자 크기가 된다.

사용법:
    python scripts/check_diagram_width.py
    python scripts/check_diagram_width.py --readme-only   # README에 실리는 것만
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG_DIR = ROOT / "docs" / "diagrams" / "svg"

GITHUB_CONTENT_WIDTH = 830.0
# 루트 README는 설명 없이 그림만으로 읽혀야 하므로 더 좁은 계약을 진다.
README_DIAGRAMS = ("overview", "promotion-ladder")
README_MAX_VIEWBOX = 880

VIEWBOX_RE = re.compile(r'viewBox="0 0 ([\d.]+) ([\d.]+)"')
FONT_RE = re.compile(r'font-size[:="\s]+([\d.]+)')


def measure(path: Path) -> tuple[float, float, float]:
    """(viewBox 폭, viewBox 높이, 830px에서의 최소 글자 크기)."""
    text = path.read_text(encoding="utf-8")
    box = VIEWBOX_RE.search(text)
    if box is None:
        raise ValueError(f"{path.name}: viewBox를 찾지 못했다")
    width, height = float(box.group(1)), float(box.group(2))
    sizes = {float(m) for m in FONT_RE.findall(text)}
    if not sizes:
        raise ValueError(f"{path.name}: font-size를 찾지 못했다")
    scale = min(1.0, GITHUB_CONTENT_WIDTH / width)
    return width, height, min(sizes) * scale


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme-only", action="store_true")
    args = parser.parse_args()

    names = README_DIAGRAMS if args.readme_only else None
    paths = sorted(SVG_DIR.glob("*.svg"))
    if names is not None:
        paths = [p for p in paths if p.stem in names]
    if not paths:
        print("측정할 SVG가 없다 — 먼저 python scripts/build_diagrams.py", file=sys.stderr)
        return 1

    violations = 0
    print(f"{'다이어그램':24} {'viewBox':>12}  {'830px에서':>10}")
    for path in paths:
        width, height, effective = measure(path)
        note = ""
        if path.stem in README_DIAGRAMS and width > README_MAX_VIEWBOX:
            note = f"  README 계약 위반 (<= {README_MAX_VIEWBOX})"
            violations += 1
        elif effective < 6.0:
            note = "  본문에서는 작다 — 원본/html로 본다"
        print(f"{path.stem:24} {int(width):5}x{int(height):<6} {effective:9.1f}px{note}")

    if violations:
        print(f"\nREADME 다이어그램 {violations}개가 너무 넓다.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

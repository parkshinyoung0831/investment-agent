"""Archify가 납품한 HTML에서 GitHub이 렌더할 수 있는 standalone SVG를 파생한다.

왜 필요한가: GitHub Markdown은 HTML을 렌더하지 않는다. 저장소의 `.html`을 상대 링크로
걸어도 raw 소스나 다운로드로 갈 뿐이라, 다이어그램이 저장소에 있어도 **아무도 보지 못한다.**
SVG는 Markdown에서 이미지로 직접 렌더된다.

Archify CLI에는 SVG export 명령이 없다(`archify --help`). 대신 납품된 HTML 안에 inline
`<svg viewBox=...>`가 하나 들어 있고, 그 도형들은 head `<style>`의 `:root` CSS 변수와
`.c-*`/`.a-*`/`.m-*` 클래스 규칙에 의존한다. 그래서 **SVG만 떼면 무채색이 된다.**
이 스크립트는 그 SVG가 실제로 쓰는 규칙만 골라 `<svg>` 안으로 인라인한다.

한 방향으로만 흐른다:

    *.json  →  archify deliver  →  *.html  →  (이 스크립트)  →  *.svg

**생성물을 손으로 고치지 않는다.** 그림을 바꾸려면 `docs/diagrams/src/*.json`을 고치고
`python scripts/build_diagrams.py`를 다시 돌린다.

사용:
    python scripts/export_diagram_svg.py            # docs/diagrams/html/*.html 전부
    python scripts/export_diagram_svg.py --check    # 쓰지 않고 최신인지만 확인 (CI용)
종료 코드: 실패하거나 --check에서 낡은 것이 있으면 1.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Windows 콘솔 기본 인코딩(cp949 등)에서 한글·em dash가 깨지지 않게.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[1]
DIAGRAMS = ROOT / "docs" / "diagrams"
HTML_DIR = DIAGRAMS / "html"
SVG_DIR = DIAGRAMS / "svg"

# SVG 안에서 쓰일 수 있는 요소 선택자. 이 이름이 선택자에 있으면 규칙을 가져온다.
SVG_ELEMENTS = frozenset({
    "svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline",
    "polygon", "text", "tspan", "textPath", "marker", "defs", "use", "image",
    "clipPath", "mask", "pattern", "linearGradient", "radialGradient", "stop",
    "foreignObject", "title", "desc", "animate", "animateTransform",
})

STYLE_BLOCK = re.compile(r"<style[^>]*>(.*?)</style>", re.S)
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
CLASS_ATTR = re.compile(r'\bclass="([^"]*)"')
# 선택자 안의 .클래스 / #id / 요소이름
SELECTOR_TOKEN = re.compile(r"[.#]?[A-Za-z_][\w-]*")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def extract_svg(html: str) -> str | None:
    """납품 HTML에는 최상위 inline SVG가 하나다. 없으면 이 파일은 대상이 아니다."""
    start = html.find("<svg")
    if start == -1:
        return None
    end = html.find("</svg>", start)
    if end == -1:
        return None
    return html[start:end + len("</svg>")]


def split_rules(css: str) -> list[tuple[str, str]]:
    """CSS를 (선택자, 본문) 목록으로 자른다. @media 등 at-rule 안까지 평탄화한다.

    정규식 한 방으로는 중첩 블록에서 틀린다 — 중괄호 깊이를 직접 센다.
    """
    css = CSS_COMMENT.sub("", css)
    rules: list[tuple[str, str]] = []
    i, n = 0, len(css)
    head_start = 0
    while i < n:
        ch = css[i]
        if ch == "{":
            head = css[head_start:i].strip()
            depth, j = 1, i + 1
            while j < n and depth:
                if css[j] == "{":
                    depth += 1
                elif css[j] == "}":
                    depth -= 1
                j += 1
            body = css[i + 1:j - 1]
            if head.startswith("@"):
                # at-rule 안의 규칙을 같은 평면으로 끌어올린다. GitHub은 SVG 안의
                # @media를 지원하지만, 테마 분기까지 옮기면 결과가 환경에 따라 달라진다.
                if head.startswith(("@media", "@supports")):
                    rules.extend(split_rules(body))
                else:
                    rules.append((head, body))       # @keyframes·@font-face는 통째로
            else:
                rules.append((head, body))
            i = head_start = j
            continue
        i += 1
    return rules


def selector_matches(selector: str, classes: set[str], ids: set[str]) -> bool:
    """이 선택자가 SVG 안의 무언가를 가리킬 수 있는가.

    넓게 잡는다 — 규칙을 빠뜨리면 그림이 조용히 무채색이 되지만, 몇 개 더
    가져오는 것은 파일이 조금 커질 뿐이다.
    """
    for part in selector.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = SELECTOR_TOKEN.findall(part)
        if not tokens:
            continue
        ok = True
        for token in tokens:
            if token.startswith("."):
                if token[1:] not in classes:
                    ok = False
                    break
            elif token.startswith("#"):
                if token[1:] not in ids:
                    ok = False
                    break
            elif token[0].islower() and token in SVG_ELEMENTS:
                continue
            elif token[0].islower() and token not in SVG_ELEMENTS:
                # html·body·button 같은 HTML 크롬 선택자. SVG에는 없다.
                ok = False
                break
        if ok:
            return True
    return False


def only_variables(body: str) -> str:
    """선언 블록에서 CSS 변수만 남긴다."""
    return ";".join(d for d in body.split(";") if d.strip().startswith("--"))


def collect_css(html: str, svg: str, preset: str) -> str:
    """SVG가 실제로 쓰는 규칙 + 그것들이 참조하는 CSS 변수를 테마별로 모은다.

    납품 HTML은 `<html data-theme="dark">`이고 팔레트가 `:root`와 `[data-theme=...]`에
    나뉘어 있다. `:root`만 가져오면 어느 테마가 이기는지가 **선언 순서에 달린 우연**이 된다.
    그래서 두 팔레트를 따로 모아 **기본을 dark로 고정한다** — Archify가 설계한 기본 모습이다.
    light는 `prefers-color-scheme: light`에 실어, 밝은 화면으로 보는 사람도 읽을 수 있게 한다.

    프리셋 전용 블록(`[data-preset="blueprint"]` 등)은 이 문서의 preset이 아니면 버린다.
    """
    classes: set[str] = set()
    for attr in CLASS_ATTR.findall(svg):
        classes.update(attr.split())
    ids = set(re.findall(r'\bid="([^"]+)"', svg))

    head = html[:html.find("<svg")]
    kept: list[str] = []
    base: list[str] = []       # :root — 테마 표시가 없는 공통 팔레트
    light: list[str] = []
    dark: list[str] = []

    for block in STYLE_BLOCK.findall(head):
        for selector, body in split_rules(block):
            if selector.startswith("@"):
                if selector.startswith("@keyframes"):
                    kept.append(f"{selector}{{{body}}}")
                continue

            # 다른 preset의 팔레트는 이 그림에 적용되지 않는다.
            presets = re.findall(r'\[data-preset="([^"]+)"\]', selector)
            if presets and preset not in presets:
                continue

            themes = set(re.findall(r'\[data-theme="([^"]+)"\]', selector))
            if ":root" in selector or themes:
                declarations = only_variables(body)
                if not declarations:
                    continue        # #theme-icon 같은 HTML 크롬 규칙
                if ":root" in selector and not themes - {"dark", "light"}:
                    # `:root, [data-theme="dark"]` 처럼 둘을 겸하는 선언.
                    # 어느 쪽 팔레트인지는 함께 적힌 테마가 말한다.
                    if themes == {"dark"}:
                        dark.append(declarations)
                    elif themes == {"light"}:
                        light.append(declarations)
                    else:
                        base.append(declarations)
                elif themes == {"light"}:
                    light.append(declarations)
                elif themes == {"dark"}:
                    dark.append(declarations)
                continue

            if selector.strip() in ("html", "body", "*"):
                declarations = only_variables(body)
                if declarations:
                    base.append(declarations)
                continue

            if selector_matches(selector, classes, ids):
                kept.append(f"{selector}{{{body}}}")

    out: list[str] = []
    if base:
        out.append("svg{" + ";".join(base) + ";}")
    if dark:
        out.append("svg{" + ";".join(dark) + ";}")            # 기본은 dark
    if light:
        out.append("@media (prefers-color-scheme: light){svg{"
                   + ";".join(light) + ";}}")                 # 밝은 화면에서도 읽히게
    out.extend(kept)
    return "\n".join(out)


def build_svg(html: str) -> str | None:
    svg = extract_svg(html)
    if svg is None:
        return None

    preset_match = re.search(r'<html[^>]*data-preset="([^"]+)"', html)
    css = collect_css(html, svg, preset_match.group(1) if preset_match else "classic")

    # 독립 문서로 열리려면 namespace가 있어야 한다. 납품 HTML 안에서는 생략돼 있다.
    open_tag_end = svg.find(">")
    open_tag = svg[:open_tag_end]
    if "xmlns=" not in open_tag:
        open_tag += ' xmlns="http://www.w3.org/2000/svg"'
    if "xmlns:xlink=" not in open_tag:
        open_tag += ' xmlns:xlink="http://www.w3.org/1999/xlink"'

    body = svg[open_tag_end + 1:]
    style = f"<style>\n{css}\n</style>\n" if css else ""
    # 배경을 칠하지 않으면 캔버스가 투명하다 — GitHub 다크 모드에서 어두운 바탕에
    # 어두운 글자가 얹혀 읽을 수 없게 된다. 테마 변수를 그대로 쓰므로 위 팔레트를 따라간다.
    canvas = '<rect width="100%" height="100%" fill="var(--bg)" />\n'
    banner = (
        "<!-- 생성물이다. 손으로 고치지 마라. "
        "docs/diagrams/*.json 을 고치고 python scripts/build_diagrams.py 를 돌려라. -->\n"
    )
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n{banner}{open_tag}>\n'
            f'{style}{canvas}{body}\n')


def main() -> int:
    parser = argparse.ArgumentParser(description="납품 HTML에서 standalone SVG 파생")
    parser.add_argument("--check", action="store_true",
                        help="쓰지 않고 현재 SVG가 HTML과 일치하는지만 확인")
    parser.add_argument("--dir", default=str(HTML_DIR), help="납품 HTML 디렉터리")
    args = parser.parse_args()

    directory = Path(args.dir)
    # visual-check는 Archify의 검사 리포트지 다이어그램이 아니다.
    sources = sorted(p for p in directory.glob("*.html") if ".visual-check" not in p.name)
    if not sources:
        print(f"HTML을 하나도 찾지 못했다: {directory}", file=sys.stderr)
        return 2                      # 0건이면 아래 검사는 아무것도 지키지 않는다

    SVG_DIR.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []
    written = 0
    for source in sources:
        target = SVG_DIR / f"{source.stem}.svg"
        produced = build_svg(read_text(source))
        if produced is None:
            print(f"  [건너뜀] {source.name} — inline SVG가 없다")
            continue
        if args.check:
            if not target.exists() or read_text(target) != produced:
                stale.append(target.name)
            continue
        if target.exists() and read_text(target) == produced:
            print(f"  [그대로] {target.name}")
            continue
        target.write_text(produced, encoding="utf-8", newline="\n")
        written += 1
        print(f"  [생성]   {target.name}  ({len(produced) // 1024}KB)")

    if args.check:
        if stale:
            print(f"낡았다 {len(stale)}건: {', '.join(stale)}\n"
                  f"python scripts/build_diagrams.py 를 돌린 뒤 이 스크립트를 다시 돌려라.",
                  file=sys.stderr)
            return 1
        print(f"OK — SVG {len(sources)}개가 HTML과 일치한다")
        return 0

    print(f"\nSVG {written}개 갱신 / 대상 {len(sources)}개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

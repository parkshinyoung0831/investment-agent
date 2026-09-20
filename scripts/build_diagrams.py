"""이 저장소의 모든 Archify 아키텍처 다이어그램을 일괄 검증 및 납품(deliver)하는 스크립트.

사용법:
    python scripts/build_diagrams.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIAGRAMS_DIR = ROOT / "docs" / "diagrams"
SPEC_DIR = DIAGRAMS_DIR / "src"      # 손으로 고치는 유일한 곳
HTML_DIR = DIAGRAMS_DIR / "html"     # 생성물

DEFAULT_NODE = Path(r"C:\Program Files\nodejs\node.exe")
ARCHIFY_MJS = Path(r"C:\Users\parks\.agents\skills\archify\bin\archify.mjs")

DIAGRAMS = [
    # (type, json_file, output_html)
    ("dataflow", "pipeline.dataflow.json", "pipeline.html"),
    ("dataflow", "trading-analysis.dataflow.json", "trading-analysis.html"),
    ("dataflow", "trading-target.dataflow.json", "trading-target.html"),
    ("lifecycle", "promotion-ladder.lifecycle.json", "promotion-ladder.html"),
    ("lifecycle", "execution-lifecycle.lifecycle.json", "execution-lifecycle.html"),
    ("workflow", "execution-runbook.workflow.json", "execution-runbook.html"),
    ("sequence", "earnings-pipeline.sequence.json", "earnings-pipeline.html"),
    ("architecture", "overview.architecture.json", "overview.html"),
    ("architecture", "system-architecture.architecture.json", "system-architecture.html"),
]


def resolve_node() -> str:
    if DEFAULT_NODE.is_file():
        return str(DEFAULT_NODE)
    in_path = shutil.which("node")
    if in_path:
        return in_path
    raise FileNotFoundError(f"Node.js not found at {DEFAULT_NODE} and not in PATH.")


def run() -> int:
    try:
        node_exe = resolve_node()
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if not ARCHIFY_MJS.is_file():
        print(f"[ERROR] archify.mjs not found at {ARCHIFY_MJS}.", file=sys.stderr)
        return 1

    failures = 0
    print(f"=== Building {len(DIAGRAMS)} Archify Showcase Diagrams ===")

    HTML_DIR.mkdir(parents=True, exist_ok=True)
    for dtype, json_name, html_name in DIAGRAMS:
        json_path = SPEC_DIR / json_name
        html_path = HTML_DIR / html_name

        if not json_path.exists():
            print(f"[FAIL] Missing specification: {json_path}", file=sys.stderr)
            failures += 1
            continue

        cmd = [
            node_exe,
            str(ARCHIFY_MJS),
            "deliver",
            dtype,
            str(json_path),
            str(html_path),
            "--quality",
            "showcase",
            "--json",
        ]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(ROOT),
        )
        if proc.returncode != 0:
            print(f"[FAIL] {json_name} -> {html_name}")
            print(proc.stderr or proc.stdout, file=sys.stderr)
            failures += 1
        else:
            try:
                receipt = json.loads(proc.stdout)
                spec_sha = receipt.get("specification", {}).get("sha256", "")[:8]
                art_sha = receipt.get("artifact", {}).get("sha256", "")[:8]
                print(f"[OK] {dtype:9} | {json_name} -> {html_name} (spec:{spec_sha} art:{art_sha})")
            except Exception:
                print(f"[OK] {dtype:9} | {json_name} -> {html_name}")

    if failures:
        print(f"\n{failures} diagram(s) failed.", file=sys.stderr)
        return 1

    print(f"\nAll {len(DIAGRAMS)} diagrams successfully validated & delivered with showcase profile.")

    # HTML만 만들고 끝내면 GitHub에서는 아무것도 보이지 않는다 — Markdown이 렌더하는 것은
    # SVG다. 빌드를 여기서 끊으면 둘이 갈라지므로 같은 명령 안에서 이어 만든다.
    print("\n=== Deriving standalone SVG for Markdown preview ===")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from export_diagram_svg import main as export_svg
    finally:
        sys.path.pop(0)

    argv, sys.argv = sys.argv, ["export_diagram_svg.py"]
    try:
        return export_svg()
    finally:
        sys.argv = argv


if __name__ == "__main__":
    sys.exit(run())

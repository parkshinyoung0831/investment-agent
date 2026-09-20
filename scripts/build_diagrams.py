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

DEFAULT_NODE = Path(r"C:\Program Files\nodejs\node.exe")
ARCHIFY_MJS = Path(r"C:\Users\parks\.agents\skills\archify\bin\archify.mjs")

DIAGRAMS = [
    # (type, json_file, output_html)
    ("dataflow", "pipeline.dataflow.json", "pipeline.html"),
    ("dataflow", "trading-analysis.dataflow.json", "trading-analysis.html"),
    ("dataflow", "trading-target.dataflow.json", "trading-target.html"),
    ("dataflow", "vnext-closed-loop.dataflow.json", "vnext-closed-loop.html"),
    ("lifecycle", "execution-lifecycle.lifecycle.json", "execution-lifecycle.html"),
    ("workflow", "execution-runbook.workflow.json", "execution-runbook.html"),
    ("sequence", "earnings-pipeline.sequence.json", "earnings-pipeline.html"),
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

    for dtype, json_name, html_name in DIAGRAMS:
        json_path = DIAGRAMS_DIR / json_name
        html_path = DIAGRAMS_DIR / html_name

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

    if failures == 0:
        print(f"\nAll {len(DIAGRAMS)} diagrams successfully validated & delivered with showcase profile.")
        return 0
    else:
        print(f"\n{failures} diagram(s) failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())

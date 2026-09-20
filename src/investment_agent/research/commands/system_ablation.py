"""System Portfolio Ablation 재현을 돌려 결과 JSON을 남긴다. 운영 원장·실계좌에는 닿지 않는다.

    python -m investment_agent.research.commands.system_ablation --start 2025-01-01 --end 2025-12-31
    python -m investment_agent.research.commands.system_ablation --start 2025-01-01 --end 2025-12-31 \\
        --variants factor_only,factor_ml --ml-artifact artifacts/trading/ml_models/candidates/<id>.json

결과는 `artifacts/research/ablation/`에 시각별 파일과 `latest.json`으로 쓴다. 채택·정책 변경은 사람이 결과를
보고 코드 리뷰로 한다.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import canonical_json

log = get_logger(__name__)


def default_output_dir() -> Path:
    from investment_agent.platform.storage_paths import repository_root
    return repository_root() / "artifacts" / "research" / "ablation"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.research.commands.system_ablation")
    parser.add_argument("--start", required=True, type=date.fromisoformat, help="재현 시작일(YYYY-MM-DD)")
    parser.add_argument("--end", required=True, type=date.fromisoformat, help="재현 종료일(YYYY-MM-DD)")
    parser.add_argument("--variants", help="쉼표로 구분한 변형 이름. 기본은 전체")
    parser.add_argument("--cvar-limits", default="0.05,0.12", help="비교할 CVaR 한도(운영 기본 0.08 외)")
    parser.add_argument("--ml-artifact", type=Path, help="재현 시작 전에 학습이 끝난 ML artifact JSON")
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    from investment_agent.research.system_validation.ablation import default_variants, run_ablation
    from investment_agent.trading.supabase_repository import SupabaseRepository

    variants = default_variants(cvar_limits=tuple(float(value) for value in args.cvar_limits.split(",") if value.strip()))
    if args.variants:
        wanted = {name.strip() for name in args.variants.split(",") if name.strip()}
        unknown = wanted - {variant.name for variant in variants}
        if unknown:
            raise SystemExit(f"unknown variants: {sorted(unknown)}")
        variants = tuple(variant for variant in variants if variant.name in wanted)
    artifact = json.loads(args.ml_artifact.read_text(encoding="utf-8")) if args.ml_artifact else None
    report = run_ablation(SupabaseRepository(), start=args.start, end=args.end, variants=variants, ml_artifact=artifact)
    directory = args.output_dir or default_output_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(report)
    (directory / f"ablation_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json").write_text(payload, encoding="utf-8")
    (directory / "latest.json").write_text(payload, encoding="utf-8")
    log.info("system ablation done %s", canonical_json({
        "sessions": report["sessions"],
        "variants": [{"name": row["name"], "status": row["status"],
                      "excess_return": (row.get("summary") or {}).get("excess_return")} for row in report["variants"]],
    }))
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())

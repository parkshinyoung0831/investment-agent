"""투자 하네스 보안 및 런타임 안전 감사 CLI.

사용 예시:
    python -m investment_agent.operations.commands.security_audit
    python -m investment_agent.operations.commands.security_audit --mode approval_workflow
    python -m investment_agent.operations.commands.security_audit --strict
    python -m investment_agent.operations.commands.security_audit --generate-hmac
    python -m investment_agent.operations.commands.security_audit --json
"""
from __future__ import annotations

import argparse
import os
import sys

from investment_agent.platform.serialization import canonical_json
from investment_agent.operations.harness.contracts import HarnessMode
from investment_agent.operations.harness.security_audit import (
    CheckStatus,
    run_security_audit,
)
from investment_agent.platform.storage_paths import repository_root

_ROOT = repository_root()


def _format_terminal_output(report) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append("  🔒 ATLAS Investment Harness — 보안 및 안전 감사 보고서")
    lines.append(f"  모드: {report.mode} | 점검 시각: {report.timestamp}")
    lines.append("=" * 70)

    current_category = ""
    for r in report.results:
        if r.category != current_category:
            current_category = r.category
            lines.append(f"\n[{current_category}]")

        icon = "✅ PASS" if r.status == CheckStatus.PASS else ("⚠️  WARN" if r.status == CheckStatus.WARN else "❌ FAIL")
        lines.append(f"  {icon:<8} | {r.code:<32} | {r.message}")
        if r.details:
            lines.append(f"            └ {r.details}")

    lines.append("\n" + "-" * 70)
    lines.append(
        f"  요약: 통과 {report.summary['PASS']}개 | 경고 {report.summary['WARN']}개 | 실패 {report.summary['FAIL']}개"
    )
    if report.healthy:
        lines.append("  🎉 종합 결과: 정상 (모든 치명적 보안 검사를 통과했습니다)")
    else:
        lines.append("  🚨 종합 결과: 보안 위험 감지 (FAIL 항목을 조치하기 전에는 실주문을 실행할 수 없습니다)")
    lines.append("=" * 70)
    return "\n".join(lines)


def _safe_print(text: str) -> None:
    data = (text + "\n").encode("utf-8", errors="replace")
    stream = getattr(sys.stdout, "buffer", None)
    if stream is not None:
        stream.write(data)
        stream.flush()
    else:
        try:
            sys.stdout.write(text + "\n")
        except UnicodeEncodeError:
            sys.stdout.write(text.encode("ascii", errors="replace").decode("ascii") + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="투자 하네스 보안 및 런타임 안전 감사 도구")
    parser.add_argument(
        "--mode",
        choices=[m.value for m in HarnessMode],
        default=HarnessMode.ANALYSIS_ONLY.value,
        help="점검 대상 하네스 모드 (기본값: analysis_only)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="경고(WARN)가 있는 경우에도 종료 코드 1을 반환",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON 형식으로 출력",
    )
    parser.add_argument(
        "--generate-hmac",
        action="store_true",
        help="새로운 암호학적 256비트 HMAC 서명 키를 생성하여 출력",
    )
    args = parser.parse_args(argv)

    if args.generate_hmac:
        import hashlib
        from investment_agent.execution.approval.secret import _default_path, load_or_create_approval_secret
        secret = load_or_create_approval_secret()
        fingerprint = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        key_path = _default_path(os.environ)
        if args.json:
            _safe_print(canonical_json({
                "status": "created_or_loaded",
                "key_file": str(key_path),
                "fingerprint_sha256": fingerprint,
            }))
        else:
            _safe_print("\n[HMAC Secret Key Ready]")
            _safe_print(f"  Key File: {key_path}")
            _safe_print(f"  Fingerprint (SHA256): {fingerprint}")
            _safe_print("  (Raw secret is secured in key file with restricted ACL permissions)\n")
        return 0

    mode = HarnessMode(args.mode)
    report = run_security_audit(
        repository_root=_ROOT,
        mode=mode,
    )

    if args.json:
        _safe_print(canonical_json(report.to_dict()))
    else:
        _safe_print(_format_terminal_output(report))

    if not report.healthy:
        return 1
    if args.strict and report.summary[CheckStatus.WARN.value] > 0:
        return 1
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    sys.exit(main())

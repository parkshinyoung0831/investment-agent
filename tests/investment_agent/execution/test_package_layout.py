"""execution의 폴더가 주문 lifecycle 순서를 그대로 말하게 한다.

    승인 → 주문 → broker → 재조정
                (그 옆에서) safety

27개 평면 모듈이었을 때는 파일 목록을 봐도 이 순서가 보이지 않았다. 이름만 옮기고
방향을 안 걸면 폴더가 하나 더 생길 뿐이므로, 여기서 두 가지를 지킨다 — 평면 경로가
돌아오지 않는 것과, `safety/`가 감시 대상을 거꾸로 참조하지 않는 것.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path("src/investment_agent/execution")
LAYERS = ("approval", "orders", "brokers", "reconciliation", "safety")


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


class ExecutionPackageLayoutTest(unittest.TestCase):
    def test_lifecycle_layers_exist(self) -> None:
        for name in LAYERS:
            with self.subTest(layer=name):
                self.assertTrue((ROOT / name).is_dir())

    def test_only_contracts_and_the_ledger_stay_flat(self) -> None:
        """루트에 모듈이 늘어나면 다시 "어디에 둘지 모르겠으면 여기" 가 된다."""
        found = {p.stem for p in ROOT.glob("*.py") if p.stem != "__init__"}
        self.assertEqual({"contracts", "db"}, found)

    def test_safety_does_not_depend_on_what_it_gates(self) -> None:
        """게이트가 감시 대상을 import하면 그 대상 없이는 게이트를 켤 수 없다.

        `risk_snapshot`이 여기 있다가 걸렸다 — 그것은 게이트가 아니라 게이트가
        나중에 읽는 관측이라 `orders/`가 맞는 자리다.
        """
        forbidden = (
            "investment_agent.execution.orders",
            "investment_agent.execution.approval",
            "investment_agent.execution.reconciliation",
            "investment_agent.execution.brokers",
        )
        offenders = [
            f"{path.as_posix()} -> {name}"
            for path in (ROOT / "safety").rglob("*.py")
            for name in _imports(path)
            if name.startswith(forbidden)
        ]
        self.assertEqual([], sorted(offenders))

    def test_removed_flat_modules_do_not_return(self) -> None:
        removed = (
            "approvals.py", "approval_card.py", "approval_secret.py", "approval_service.py",
            "approval_status.py", "discord_approval.py", "intents.py", "planning.py",
            "ledger.py", "lifecycle.py", "twap.py", "live_worker.py", "paper_worker.py",
            "toss_manual.py", "snapshots.py", "toss_snapshot.py", "tca.py", "tca_recorder.py",
            "market_state.py", "reconciliation.py", "reconciliation_worker.py",
            "circuit_breaker.py", "control.py", "control_state.py", "risk_snapshot.py",
        )
        for name in removed:
            with self.subTest(name=name):
                self.assertFalse((ROOT / name).exists())


if __name__ == "__main__":
    unittest.main()

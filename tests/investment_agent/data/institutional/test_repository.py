"""13F의 45일 지연이 PIT 경계로 지켜지는지 본다."""
from __future__ import annotations

import unittest
from datetime import date

from investment_agent.data.institutional.domain.holdings import AMENDMENT_RESTATEMENT
from investment_agent.data.institutional.repository import (
    SCHEMA,
    T_FILINGS,
    T_POSITIONS,
    InstitutionalRepository,
)
from tests.investment_agent.fakes import FakeDatabase

MANAGER = "0001067983"
PERIOD = "2026-06-30"
ORIGINAL = "0001067983-26-000001"
RESTATED = "0001067983-26-000009"


def _filing_row(accession: str, filed: str, *, form: str = "13F-HR",
                amendment: str | None = None) -> dict:
    return {
        "accession_no": accession,
        "manager_cik": MANAGER,
        "period_end": PERIOD,
        "form_type": form,
        "filing_date": filed,
        "amendment_type": amendment,
        "amendment_no": 1 if amendment else None,
        "reported_value_usd": 1000.0,
    }


def _position_row(accession: str, row_no: int, identifier: str, value: float,
                  kind: str = "SHARES") -> dict:
    return {
        "accession_no": accession,
        "source_row_no": row_no,
        "issuer_name": "EXAMPLE",
        "identifier": identifier,
        "identifier_type": "CUSIP",
        "value_usd": value,
        "quantity": 100,
        "quantity_type": "SH",
        "position_kind": kind,
    }


class ManagerTest(unittest.TestCase):
    def test_active_managers_reads_code_config_not_the_database(self) -> None:
        """manager_cik/name/fund_name/is_active의 SSOT는 코드 설정이다 — Supabase에는
        해당 표가 없으므로 이 조회는 db 인자를 전혀 건드리지 않는다."""
        from investment_agent.data.institutional.domain import managers as manager_config

        db = FakeDatabase()
        managers = InstitutionalRepository(db).active_managers()
        self.assertEqual(manager_config.active_managers(), managers)
        self.assertEqual({}, db.tables)


class PointInTimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeDatabase()
        self.db.put(SCHEMA, T_FILINGS, [_filing_row(ORIGINAL, "2026-08-14")])
        self.repo = InstitutionalRepository(self.db)

    def test_the_quarter_end_is_not_when_we_could_see_it(self) -> None:
        """13F는 45일 늦게 나온다. period_end로 자르면 한 분기를 미리 본다."""
        self.assertEqual([], self.repo.filings([MANAGER], known_at=date(2026, 7, 1)))

    def test_after_the_filing_date_it_is_visible(self) -> None:
        self.assertEqual(1, len(self.repo.filings([MANAGER], known_at=date(2026, 8, 20))))

    def test_without_known_at_everything_is_returned(self) -> None:
        self.assertEqual(1, len(self.repo.filings([MANAGER])))


class RestatementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeDatabase()
        self.db.put(SCHEMA, T_FILINGS, [
            _filing_row(ORIGINAL, "2026-08-14"),
            _filing_row(RESTATED, "2026-08-25", form="13F-HR/A", amendment=AMENDMENT_RESTATEMENT),
        ])
        self.db.put(SCHEMA, T_POSITIONS, [
            _position_row(ORIGINAL, 1, "037833100", 100.0),
            _position_row(RESTATED, 1, "594918104", 100.0),
        ])
        self.repo = InstitutionalRepository(self.db)

    def test_only_the_restatement_counts(self) -> None:
        """원본까지 세면 이 매니저의 보유가 두 배가 된다."""
        weights = self.repo.weights_for(MANAGER, period_end=date(2026, 6, 30))
        self.assertEqual({"594918104": 1.0}, weights)

    def test_before_the_restatement_arrived_the_original_stands(self) -> None:
        weights = self.repo.weights_for(
            MANAGER, period_end=date(2026, 6, 30), known_at=date(2026, 8, 20)
        )
        self.assertEqual({"037833100": 1.0}, weights)

    def test_a_manager_with_no_filing_has_no_weights(self) -> None:
        self.assertEqual({}, self.repo.weights_for("0000000099", period_end=date(2026, 6, 30)))


class OptionsTest(unittest.TestCase):
    def test_option_lines_are_excluded_from_weights(self) -> None:
        db = FakeDatabase()
        db.put(SCHEMA, T_FILINGS, [_filing_row(ORIGINAL, "2026-08-14")])
        db.put(SCHEMA, T_POSITIONS, [
            _position_row(ORIGINAL, 1, "037833100", 100.0),
            _position_row(ORIGINAL, 2, "594918104", 100.0, kind="PUT"),
        ])
        weights = InstitutionalRepository(db).weights_for(MANAGER, period_end=date(2026, 6, 30))
        self.assertEqual({"037833100": 1.0}, weights)


if __name__ == "__main__":
    unittest.main()

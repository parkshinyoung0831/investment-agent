"""institutional v1 SQL이 §9의 세 표와 universe 매핑 경계를 지키는지 검증한다."""
from __future__ import annotations

from pathlib import Path
import unittest


class InstitutionalSchemaContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[4]
        cls.sql = (root / "db" / "postgres" / "v1" / "50_institutional.sql").read_text(encoding="utf-8")

    def test_only_two_institutional_tables_are_declared(self) -> None:
        """manager(name/fund_name/is_active)는 SEC 사실이 아니라 우리가 고른
        추적 대상이라 Supabase 표가 아니라 코드 설정이 소유한다."""
        self.assertEqual(self.sql.count("CREATE TABLE IF NOT EXISTS institutional."), 2)
        for table in ("filings", "positions"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS institutional.{table}", self.sql)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS institutional.managers", self.sql)
        self.assertNotIn("cusip_ticker_map", self.sql)

    def test_filings_preserve_provenance_and_amendment_shape(self) -> None:
        for field in ("accepted_at", "source_url", "content_sha256", "reported_line_count"):
            self.assertIn(field, self.sql)
        # 이름 붙은 제약이 아니라 인라인 CHECK로 선언돼 있다.
        self.assertIn(
            "CHECK ((form_type = '13F-HR' AND amendment_type IS NULL AND amendment_no IS NULL)\n"
            "      OR (form_type = '13F-HR/A' AND amendment_type IS NOT NULL AND amendment_no IS NOT NULL))",
            self.sql,
        )
        self.assertIn("CHECK (period_end <= filing_date)", self.sql)

    def test_positions_preserve_raw_rows(self) -> None:
        """SEC raw XML의 투표권·투자재량 상세는 더 이상 저장하지 않는다 — 사실
        컬럼만 남기는 간소화다(파일 상단 주석 참고)."""
        for field in ("source_row_no", "identifier", "identifier_type"):
            self.assertIn(field, self.sql)
        for removed in ("title_of_class", "investment_discretion", "other_manager",
                        "voting_sole", "voting_shared", "voting_none"):
            self.assertNotIn(removed, self.sql)
        self.assertIn("PRIMARY KEY (accession_no, source_row_no)", self.sql)

    def test_manager_catalog_declares_operational_metadata(self) -> None:
        """manager 사실(name/fund_name/is_active)과 화면 해석(strategy_group·
        signal_role 등)은 SQL이 아니라 코드 설정
        (`investment_agent.data.institutional.managers`)이 소유한다."""
        from investment_agent.data.institutional.domain.managers import (
            MANAGER_CATALOG,
            MANAGER_PRESENTATION,
        )

        self.assertNotIn("INSERT INTO institutional.managers", self.sql)
        self.assertTrue(MANAGER_CATALOG)
        for cik, row in MANAGER_CATALOG.items():
            self.assertRegex(cik, r"^[0-9]{10}$")
            for field in ("name", "fund_name", "is_active"):
                self.assertIn(field, row)
        self.assertTrue(MANAGER_PRESENTATION)
        for row in MANAGER_PRESENTATION.values():
            for field in ("strategy_group", "signal_role", "copyability", "blind_spots"):
                self.assertIn(field, row)


if __name__ == "__main__":
    unittest.main()

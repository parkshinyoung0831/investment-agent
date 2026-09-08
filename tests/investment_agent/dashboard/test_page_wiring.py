"""화면이 실제로 그려지는지, 그리고 화면이 요구하는 것을 reader가 받아 주는지.

2,500개 테스트 중 **화면을 한 번도 렌더하지 않았다.** 그 사이에 네 가지가 조용히
망가져 있었다 — 국기 SVG 경로가 옮겨진 디렉터리를 가리켜 지표 발표 화면이 통째로
죽었고, 발표 화면이 시장 관측 지표까지 발표 카탈로그로 해석하려다 예외를 냈고,
홈이 가격 저장소에 없는 심볼을 섞어 물어 SPY·QQQ 카드까지 함께 비었고, 쓰이지 않는
실적 reader가 어느 경로로도 성공할 수 없는 채 남아 있었다.

여기서는 **DB를 때리지 않는다.** `DASHBOARD_OFFLINE`을 켜면 reader가 첫 줄에서
offline을 돌려주므로, 화면은 "연결 대기" 상태를 끝까지 그리게 된다. 그것만으로도
import·모듈 최상단 계산·레이아웃·자산 경로가 전부 실행된다.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
PAGES = ROOT / "src" / "investment_agent" / "dashboard" / "app_pages"

OFFLINE_ENV = {
    "DASHBOARD_OFFLINE": "1",
    "SUPABASE_URL": "",
    "SUPABASE_SERVICE_KEY": "",
}


def _page_files() -> list[Path]:
    return sorted(path for path in PAGES.glob("*.py") if path.stem != "__init__")


class PageRenderTest(unittest.TestCase):
    """모든 화면이 연결 없이도 예외 없이 끝까지 그려진다."""

    def test_there_are_pages_to_render(self) -> None:
        """화면을 못 찾으면 아래 검사가 공허하게 통과한다."""
        self.assertGreaterEqual(len(_page_files()), 10)

    def test_every_page_renders_offline_without_raising(self) -> None:
        from streamlit.testing.v1 import AppTest

        offenders: list[str] = []
        for path in _page_files():
            with mock.patch.dict("os.environ", OFFLINE_ENV):
                app = AppTest.from_file(str(path), default_timeout=120)
                app.run()
            for problem in app.exception:
                message = " ".join(str(problem.message or "").split())[:200]
                offenders.append(f"{path.stem}: {problem.type}: {message}")
        self.assertEqual([], offenders)


class CalendarAssetTest(unittest.TestCase):
    """st.image는 파일이 없으면 화면 전체를 죽인다 — 경로를 디스크에서 확인한다."""

    def test_every_declared_flag_file_exists(self) -> None:
        from investment_agent.dashboard.components.calendar_grid import COUNTRY_FLAG_ASSETS

        self.assertTrue(COUNTRY_FLAG_ASSETS, "국기 자산 선언이 비었다")
        missing = [
            f"{country}={path}"
            for country, path in COUNTRY_FLAG_ASSETS.items()
            if not path.is_file()
        ]
        self.assertEqual([], missing)


class HomeMarketWiringTest(unittest.TestCase):
    """홈이 묻는 심볼을 가격 reader가 그대로 받아야 한다."""

    def test_home_price_tickers_are_not_rejected_by_the_reader(self) -> None:
        """형식 거절은 질의 **전체**를 막는다 — 하나만 어긋나도 카드가 다 빈다."""
        from investment_agent.dashboard.app_pages import home
        from investment_agent.reporting.readers.dashboard import load_price_history

        with mock.patch.dict("os.environ", OFFLINE_ENV):
            result = load_price_history.__wrapped__(home._PRICE_TICKERS, period="1mo")
        # offline은 "연결을 안 열었다"이고 blocked는 "입력이 틀렸다"이다. 후자가
        # 나오면 화면이 저장소에 없는 심볼을 섞어 물었다는 뜻이다.
        self.assertEqual("offline", result.status)

    def test_price_store_tickers_are_declared_as_benchmarks(self) -> None:
        """홈이 읽는 벤치마크는 수집 대상이어야 한다 — 아니면 행이 영영 안 생긴다."""
        from investment_agent.data.market import REFERENCE_PRICE_TICKERS
        from investment_agent.dashboard.app_pages import home

        self.assertLessEqual(set(home._PRICE_TICKERS), set(REFERENCE_PRICE_TICKERS))


class EconSeriesScopeTest(unittest.TestCase):
    """발표 화면은 발표 지표만 읽는다."""

    def test_series_master_is_read_with_the_release_domain_filter(self) -> None:
        """macro.series에는 시장 관측 지표가 함께 산다. 걸러지지 않은 채 발표
        카탈로그로 넘어가면 domain이 `unknown ECON series`로 화면을 죽인다."""
        from investment_agent.reporting.models import DataResult
        from investment_agent.reporting.readers import dashboard as reader

        seen: list[tuple[str, dict]] = []

        def fake_read(view: str, **kwargs: object) -> DataResult:
            seen.append((view, dict(kwargs)))
            return DataResult.ok(rows=[], source="test")

        with mock.patch.object(reader, "_read", side_effect=fake_read):
            reader.load_econ_series.__wrapped__()

        series_reads = [kwargs for view, kwargs in seen if view == "macro_series"]
        self.assertEqual(1, len(series_reads), f"macro_series 조회가 없다: {seen}")
        self.assertEqual({"domain": "economic_release"}, series_reads[0].get("equals"))


if __name__ == "__main__":
    unittest.main()

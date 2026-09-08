"""수집 대상 서브레딧 선언.

환경변수가 아니라 코드가 선언을 갖는다 — 어떤 채널을 보는지는 실행 환경마다
달라야 할 설정이 아니라 이 저장소의 결정이다.
"""
from __future__ import annotations

SUBREDDITS = ("stocks", "investing", "wallstreetbets", "StockMarket")

__all__ = ["SUBREDDITS"]

"""News/Social 수집 상태 화면.

## 왜 intelligence.py가 아닌가

`app_pages/intelligence.py`는 이미 AI 판단 엔진 화면이 쓰고 있다. 저장소 이름은
목표대로 intelligence를 쓰되, 화면 파일 이름만 피한다 — 그 페이지를 지금 개명하면
이번 작업 범위 밖의 라우팅과 테스트를 건드리게 된다.

## 이 화면은 reporting만 읽는다

저장소를 직접 열지 않는다. 이 페이지는 `저장소 → reporting → 화면` 경로가 실제로
성립한다는 증거이기도 하다.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd
import streamlit as st

from investment_agent.reporting.readers import intelligence as store


def _freshness_frame(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "영역": row.get("domain"),
                "보관 행": row.get("row_count"),
                "가장 오래된 글": row.get("oldest_at"),
                "가장 최근 글": row.get("newest_at"),
                "마지막 수집": row.get("last_collected_at"),
            }
            for row in rows
        ]
    )


def _render_runs(runs: Sequence[Mapping[str, Any]]) -> None:
    if not runs:
        st.caption("아직 수집·정리 기록이 없어요.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "종류": row.get("kind"),
                    "영역": row.get("domain"),
                    "상태": row.get("status"),
                    "저장": row.get("stored_count"),
                    "중복": row.get("duplicate_count"),
                    "해석 실패": row.get("unparsed_count"),
                    "삭제": row.get("deleted_count"),
                    "시각": row.get("started_at"),
                }
                for row in runs
            ]
        ),
        width="stretch",
        hide_index=True,
    )


st.header("뉴스 · 소셜")
st.caption("로컬에 90일만 보관해요. 발행일이 90일을 넘기면 자동으로 지워집니다.")

_overview = store.load_overview()

if not _overview["available"]:
    st.info(
        "아직 수집이 한 번도 돌지 않았어요. "
        "`python -m investment_agent.intelligence.commands.collect_news`로 시작할 수 있어요."
    )
    st.caption(f"저장 위치: {_overview['path']}")
else:
    st.subheader("보관 상태")
    st.dataframe(_freshness_frame(_overview["freshness"]), width="stretch", hide_index=True)

    st.subheader("최근 수집·정리")
    _render_runs(_overview["runs"])

    _trending = store.load_trending(days=7, limit=20)
    if _trending:
        st.subheader("최근 7일 언급 상위")
        st.dataframe(pd.DataFrame(_trending), width="stretch", hide_index=True)

    _news_tab, _social_tab = st.tabs(["뉴스", "소셜"])
    with _news_tab:
        _rows = store.load_news(limit=50)
        if _rows:
            st.dataframe(pd.DataFrame(_rows), width="stretch", hide_index=True)
        else:
            st.caption("보관된 기사가 없어요.")
    with _social_tab:
        _rows = store.load_social(limit=50)
        if _rows:
            st.dataframe(pd.DataFrame(_rows), width="stretch", hide_index=True)
        else:
            st.caption("Reddit 자격증명을 넣으면 여기에 게시물이 쌓여요.")

"""Discord-first 운영 로그 위치와 확인 순서를 안내한다."""

from __future__ import annotations

import os

import streamlit as st


def operations_links() -> dict[str, str]:
    """설정된 운영 링크만 안전한 HTTPS URL로 반환한다."""
    links = {
        "discord": os.getenv("DISCORD_SYSTEM_LOG_URL", "").strip(),
        "github": os.getenv("GITHUB_ACTIONS_URL", "").strip(),
    }
    return {name: url for name, url in links.items() if url.startswith("https://")}


def render_operations_guide() -> None:
    """DB 조회 없이 운영 기록의 단일 확인 경로를 보여준다."""
    st.info(
        "운영 오류와 실행 이력은 데이터베이스에 저장하지 않습니다. "
        "Discord에서 사건을 찾고 GitHub Actions에서 원문 로그를 확인하세요.",
        icon=":material/info:",
    )

    links = operations_links()
    with st.container(horizontal=True):
        if "discord" in links:
            st.link_button(
                "Discord 시스템 로그",
                links["discord"],
                icon=":material/forum:",
                type="primary",
            )
        if "github" in links:
            st.link_button(
                "GitHub Actions",
                links["github"],
                icon=":material/open_in_new:",
            )

    with st.container(border=True):
        st.markdown("**1. Discord `#액션-실패`(GitHub Actions) 또는 `#로컬-실패`(이 컴퓨터)에서 사건을 찾습니다**")
        st.write("실패 위치, 짧은 원인, 영향, 다음 행동, KST 발생 시각과 사건 ID를 확인합니다.")

    with st.container(border=True):
        st.markdown("**2. 카드의 실행 링크로 GitHub Actions를 엽니다**")
        st.write("실패한 잡·단계의 원문 로그를 확인하고 수정 또는 재실행합니다.")

    with st.container(border=True):
        st.markdown("**3. 복구 여부는 다음 실행과 일일 heartbeat로 확인합니다**")
        st.write("로컬 상시 하네스 상태는 이 화면의 프로세스·잡·단계 보기에서 따로 확인합니다.")

    if not links:
        st.caption(
            "바로가기 설정 · DISCORD_SYSTEM_LOG_URL, GITHUB_ACTIONS_URL을 환경변수에 넣으면 버튼이 표시됩니다."
        )


__all__ = ["operations_links", "render_operations_guide"]

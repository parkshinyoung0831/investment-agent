"""하네스 요약을 먼저 보여주고 선택한 운영 상세만 읽는다."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import streamlit as st

from investment_agent.dashboard.ops import read_harness_state
from investment_agent.dashboard.components.operations_view import render_operations_guide
from investment_agent.dashboard.components.ui import (
    SOURCE_LOCAL,
    dataframe,
    format_time,
    page_header,
    render_source_help,
    result_payload,
    result_status,
    source_note,
    view_selector,
)


ROOT = Path(__file__).resolve().parents[3]
STATE_PATH = ROOT / "artifacts" / "ops" / "investment_harness" / "state.json"


def _kill_switch_label() -> tuple[str, str]:
    raw = os.getenv("TRADING_KILL_SWITCH")
    if raw is None:
        return "ON (안전 기본값)", "환경변수 미설정은 기존 안전 정책상 ON으로 해석"
    normalised = raw.strip().lower()
    if normalised in {"0", "false", "off", "no"}:
        return "OFF", "환경변수의 현재 읽기값"
    if normalised in {"1", "true", "on", "yes"}:
        return "ON", "환경변수의 현재 읽기값"
    return "ON (값 해석 불가)", "알 수 없는 값은 기존 안전 정책상 ON으로 해석"


def _jobs_from_state(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    jobs_value = state.get("jobs") or {}
    if isinstance(jobs_value, list):
        return {
            str(row.get("job_id")): row
            for row in jobs_value
            if isinstance(row, dict) and row.get("job_id")
        }
    if isinstance(jobs_value, dict):
        return {str(key): value for key, value in jobs_value.items() if isinstance(value, dict)}
    return {}


page_header(
    "시스템 관제탑",
    "로컬 프로세스 안전 상태와 Discord-first 운영 기록 위치를 확인해요",
    discord="#운영-요약 · #로컬-실패",
)
render_source_help()
st.warning(
    "이 화면에서는 하네스 시작·종료·재시작, kill switch 변경, 잡 재개를 할 수 없어요.",
    icon=":material/lock:",
)

state_result = read_harness_state(STATE_PATH)
state_available = result_status(state_result, empty_text="하네스 상태 파일이 없습니다")
state = result_payload(state_result, default={}) or {} if state_available else {}
health = state.get("health") if isinstance(state.get("health"), dict) else {}
jobs = _jobs_from_state(state)

view = view_selector(
    "관제 보기",
    ("프로세스 요약", "자동화 잡", "단계 상세", "운영 로그"),
    key="system_adaptive_view",
    default="프로세스 요약",
)

if view == "프로세스 요약":
    kill_label, kill_detail = _kill_switch_label()
    started_full = format_time(state.get("process_started_at"))
    heartbeat_full = format_time(state.get("process_heartbeat_at"))
    started_short = started_full[5:16] if started_full != "—" else "—"
    heartbeat_short = heartbeat_full[5:16] if heartbeat_full != "—" else "—"
    pid_alive = health.get("pid_alive")
    pid_text = "예" if pid_alive is True else "아니오" if pid_alive is False else "확인 불가"
    age = health.get("heartbeat_age_seconds")
    age_text = f"{float(age):,.0f}초" if isinstance(age, (int, float)) else "—"

    with st.container(horizontal=True):
        st.metric("PID", state.get("process_id") or "—", border=True)
        st.metric("프로세스 판정", health.get("label") or health.get("status") or "—", border=True)
        st.metric("시작 시각", started_short, border=True)
    with st.container(horizontal=True):
        st.metric("최근 상태 신호", heartbeat_short, border=True)
        stopped = state.get("stopped_cleanly")
        st.metric("정상 종료", "예" if stopped is True else "아니오" if stopped is False else "—", border=True)
        st.metric("주문 차단 스위치", kill_label, border=True)
    st.caption(
        f"프로세스 실행 중 · {pid_text} · 마지막 신호 경과 · {age_text} · "
        f"전체 시작 시각 · {started_full} · 전체 마지막 신호 · {heartbeat_full}"
    )
    st.caption(
        f"stopped_at · {format_time(state.get('stopped_at'))} · "
        f"recovery · {state.get('recovery_count') if state.get('recovery_count') is not None else '—'} · "
        f"kill switch · {kill_detail}"
    )
    source_note(SOURCE_LOCAL, observed_at=state.get("process_heartbeat_at"), detail=str(STATE_PATH.relative_to(ROOT)))

elif view == "자동화 잡":
    job_rows: list[dict[str, Any]] = []
    for job_id, job in jobs.items():
        stages = job.get("stages") if isinstance(job.get("stages"), dict) else {}
        failed_stages = [
            name
            for name, stage in stages.items()
            if isinstance(stage, dict) and stage.get("status") == "failed"
        ]
        job_rows.append(
            {
                "잡": job.get("job_id") or job_id,
                "상태": job.get("status"),
                "현재 단계": job.get("stage"),
                "최근 시작": job.get("started_at"),
                "최근 완료": job.get("completed_at"),
                "최근 신호": job.get("heartbeat_at"),
                "중단 사유": job.get("pause_reason"),
                "실패 단계": ", ".join(failed_stages) or "—",
                "실행 ID": job.get("run_id"),
            }
        )
    if job_rows:
        dataframe(job_rows, key="system_jobs")
        source_note(SOURCE_LOCAL, observed_at=state.get("process_heartbeat_at"), detail=str(STATE_PATH.relative_to(ROOT)))
    else:
        st.info("상태 파일에 잡 정보가 없습니다.")

elif view == "단계 상세":
    if not jobs:
        st.info("상태 파일에 단계 상세를 볼 잡이 없습니다.")
    else:
        selected_job_id = st.selectbox(
            "잡",
            list(jobs),
            format_func=lambda value: jobs[value].get("job_id") or value,
            key="system_stage_job",
        )
        selected_job = jobs[selected_job_id]
        stages = selected_job.get("stages") if isinstance(selected_job.get("stages"), dict) else {}
        stage_rows = [
            {
                "단계": stage_name,
                "상태": stage.get("status"),
                "시도": stage.get("attempts"),
                "시작": stage.get("started_at"),
                "완료": stage.get("completed_at"),
                "재개 예정": stage.get("resume_at"),
                "최근 오류": stage.get("last_error"),
                "메타데이터": stage.get("metadata"),
            }
            for stage_name, stage in stages.items()
            if isinstance(stage, dict)
        ]
        dataframe(stage_rows, key=f"system_stages:{selected_job_id}")
        source_note(SOURCE_LOCAL, observed_at=selected_job.get("heartbeat_at"))

elif view == "운영 로그":
    render_operations_guide()

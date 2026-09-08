"""저장소별 읽기 경계. 파일 이름이 "어디서 오는가"를 말한다.

reporting이 존재하는 이유가 그 질문을 화면과 알림에서 감추는 것이다 — 그러니
감추는 쪽은 한곳에 모여 있어야 한다. Supabase·로컬 SQLite·DuckDB·외부 provider가
각각 한 파일이고, `services/`는 이 계약만 소비한다.
"""
from __future__ import annotations

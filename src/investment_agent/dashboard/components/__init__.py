"""페이지가 함께 쓰는 화면 조각.

여기 있는 것은 그리는 방법만 안다 — 무엇을 그릴지는 `app_pages/`가, 값을 어디서
읽을지는 `db.py`가 정한다.

디렉터리 이름이 `pages/`가 아니라 `app_pages/`인 것은 취향이 아니다. Streamlit은
진입점 옆의 `pages/`를 자동 멀티페이지로 훑어 `st.navigation`이 만든 것과 겹치는
사이드바를 하나 더 만든다.
"""
from __future__ import annotations

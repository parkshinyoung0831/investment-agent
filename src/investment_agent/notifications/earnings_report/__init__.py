"""fundamentals: 관심종목 실적 공시(10-Q/10-K) 알림.

트리거: 펀더멘탈·세그먼트 ETL 이후 실행 — 관심종목의 미발송 신규 공시만 추려 알린다.
대상:   Supabase universe.entities의 활성 관심 기업(대표 종목 표기).

데이터:   reporting/notifications/earnings_report.py — financial_versions에서
                         '헤드라인 1행 + 전년 동기 1행' 조회,
                         accession_no으로 세그먼트 상태·주축을 연결하고
                         notifications.outbox 중복 키를 확인
계산:     reporting/earnings/metrics.py — 마진·FCF·순부채·YoY 파생
판단:     reporting/earnings/thresholds.py — grade로 경고 등급(🔴🟡🟢) 판정
표시:     format.py    — 금액·퍼센트·전년비 / card.py — KPI·마진·현금·세그먼트·밸류 ctx 조립
렌더:     render.py + templates/earnings.html.j2 — Jinja2 HTML → Playwright PNG 캡처
알림:     run.py       — run() 하나만 노출. 진입점(__main__)이 --kind fundamentals_earnings로 호출.

dedup 단위는 (ticker, accession_no) — 같은 날 별도 공시와 정정공시를 정확히 구분한다.
PNG 발송은 notifications.outbox에 고정한 첨부 스냅샷을 통해 처리한다.
"""
from __future__ import annotations

"""뉴스·소셜 — 외부 비정형 텍스트를 투자 intelligence로 바꾼다.

`data/`와 나란히 두는 이유는 저장소가 다르기 때문이다. `data/`의 금융 사실은
Supabase가 소유하고, 여기의 원문은 로컬 Parquet에, 색인과 언급은 로컬 DuckDB에
남는다. 뉴스와 소셜을 한 패키지로 묶은 것도 같은 이유다 — 출처는 다르지만 목적이
같아서(외부 텍스트 → 종목 언급) 도메인 규칙과 저장소를 공유한다.
"""
from __future__ import annotations

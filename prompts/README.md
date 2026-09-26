# prompts/ — 외부 GPT용 질의 템플릿

* **상위 문서**: [루트 README.md](../README.md) · [개발 가이드 CLAUDE.md](../CLAUDE.md)
* **템플릿 파일**:
  * [개별 주식 심층 분석 템플릿 (stock_analysis.md)](stock_analysis.md)
  * [ETF 퀀트 분석 템플릿 (etf_analysis.md)](etf_analysis.md)

**이 디렉터리는 코드가 아닙니다.** 저장소의 어떤 모듈도 여기를 import하지 않고,
테스트도 읽지 않습니다.

`stock_analysis.md`는 **Supabase MCP에 연결된 외부 GPT에게 그대로 던지는 질의
템플릿**입니다. GPT가 이 지시문을 받아 Supabase를 직접 조회하고 분석을 씁니다.

`etf_analysis.md`는 Supabase를 전혀 쓰지 않습니다. 사용자가 로컬에서 yfinance·edgartools
스크립트를 직접 실행하고, 그 출력(텍스트 요약)을 채팅에 붙여넣으면 GPT가 그 값을 근거로
분석을 씁니다.

두 템플릿 모두 길이는 의도된 것입니다 — 조회할 테이블·컬럼·판정 기준(또는 실행할 스크립트와
출력 형식)을 빠짐없이 적어야 GPT가 임의로 지어내지 않습니다. **압축하거나 지우지 마세요.**

## 스키마를 바꿀 때

`stock_analysis.md`는 DB 스키마·컬럼명을 문자열로 박아 두고 있습니다(`etf_analysis.md`는
Supabase를 쓰지 않으므로 해당 없음). 코드와 달리 참조가 깨져도 아무도 알려주지 않으므로,
**스키마 변경 시 확인 목록에 반드시 넣으세요.**

```bash
# 바꾼 이름이 프롬프트에 남아 있는지
grep -rn "<옛_컬럼명>\|<옛_테이블명>" prompts/
```

특히 이런 변경이 프롬프트를 조용히 깨뜨립니다:

- 테이블 이름 변경 (`fundamentals.financials`, `macro.market_observations` …)
- 컬럼 이름 변경 (예: `macro.market_observations.obs_date`)
- 저장소 이동 — Supabase에 있던 것이 로컬 SQLite·DuckDB로 옮겨가면 이름이 남아 있어도
  그 대화에서는 **조회 자체가 불가능**해진다
- CHECK 허용값 변경 (프롬프트가 값 자체를 조건으로 쓰는 경우)
- 뷰 삭제·통합


## 사용

`stock_analysis.md`는 Supabase MCP가 붙은 GPT 대화에, `etf_analysis.md`는 코드 실행이
가능한 GPT 대화에 파일 내용을 붙여넣고 종목/ETF 티커를 지정하면 됩니다. 둘 다 읽기 전용
조회·계산만 하도록 쓰여 있으며, 이 저장소의 파이프라인과는 독립적으로 동작합니다.

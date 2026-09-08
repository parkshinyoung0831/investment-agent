# AGENTS.md

이 저장소에서 작업하는 코딩 에이전트(OpenAI Codex 등)를 위한 안내서입니다.
Codex는 저장소 루트의 `AGENTS.md`를 자동으로 읽습니다.

**작업 관례와 아키텍처는 [CLAUDE.md](CLAUDE.md) 하나에 있습니다. 그 문서를 읽고 그대로 따르세요.**
조회용 레퍼런스는 거기서 링크로 갈라져 있습니다 — 환경변수는 [docs/ENV.md](docs/ENV.md),
실행 스크립트와 CI 상세는 [docs/OPERATIONS.md](docs/OPERATIONS.md)입니다.
시스템 전체 개요와 빠른 시작 가이드는 [README.md](README.md)를 참조하세요.
UI 및 알림 카드 디자인 규칙은 [DESIGN-system.md](DESIGN-system.md)를 따릅니다.

내용을 이 파일에 복사하지 마세요. 판단이 필요한 규칙의 단일 진실 공급원(SSOT)은 [CLAUDE.md](CLAUDE.md)이고,
레퍼런스 문서는 거기서만 링크합니다. 아래 '하지 말 것' 블록만 예외입니다 — 이유는 그 안에 적혀 있습니다.

## 실행 환경 노트

ETL·알림 실행(`python -m investment_agent.*`)은 외부 네트워크(SEC·yfinance·FRED·Supabase)와 Playwright
Chromium이 있어야 동작합니다. 샌드박스에서 네트워크가 막혀 있으면 이 명령들은 실패하니,
변경 검증은 **오프라인 단위 테스트**로 하고 작업을 마치기 전 통과시키세요.

```bash
python -m unittest discover -s tests -t .
```

파일 경로 참조는 클릭 링크가 아니라 그냥 상대경로로 읽으면 됩니다.

## 코드 지식 그래프 — graphify

`/graphify`를 입력하면 설치된 graphify 스킬(`.codex/skills/graphify/SKILL.md`)을 먼저 따르세요.
사용 규칙은 [CLAUDE.md](CLAUDE.md)의 "코드 지식 그래프 — graphify" 절 하나에만 있습니다.

## 스킬 — 그 영역을 만지기 전에 해당 SKILL.md를 읽으세요

Codex는 스킬을 자동 발견하지 않습니다. 아래 표에서 지금 만지는 영역을 찾아
그 파일을 먼저 읽으세요. 여러 개가 걸리면 전부 읽습니다.

| 스킬 | 언제 | 경로 |
|---|---|---|
| `graphify` | 코드 구조·의존성 파악 (grep보다 먼저) | `.codex/skills/graphify/SKILL.md` |

스킬과 [CLAUDE.md](CLAUDE.md)가 충돌하면 **CLAUDE.md가 우선**입니다.

## 하지 말 것

<!-- danger-floor:start -->
되돌릴 수 없거나 **에러 없이 조용히** 망가지는 것들이다. 이 블록은 AGENTS.md에도 같은
내용으로 있고, 두 파일이 어긋나면 테스트가 잡는다 — 한쪽만 고치지 마라.

- `LIVE_ENABLED`·`TOSS_LIVE_ENABLED`를 코드가 자동으로 바꾸기. 사람이 명시적으로 켠다.
- 정비 보류 없이 하네스·실행 코드 고치기 (`harness_switch --maintenance on` 먼저).
- LLM에게 hard risk limit·최종 portfolio weight·broker 실행 권한 넘기기.
- 카드 채널에 @everyone 채널 deny 달기. 카드 봇 권한까지 무력화돼 카드가 조용히 안 나간다.
- Discord 채널·역할·권한을 UI에서 손보기. `src/investment_agent/notifications/discord_admin/`이 SSOT다.
- 대량 읽기에 `select_all_paged()` 빠뜨리기. 1,000행에서 조용히 잘린다.
- `.env`나 비밀값 커밋하기.
<!-- danger-floor:end -->

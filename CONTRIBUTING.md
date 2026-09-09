# 기여 가이드 — 무엇을 먼저 읽고, 무엇을 절대 하지 않는가

이 저장소는 실제 돈이 오가는 경로를 갖고 있습니다. 그래서 기여 규칙의 대부분은 스타일이
아니라 **되돌릴 수 없는 일과 조용히 틀리는 일**을 막는 것에 관한 것입니다.

## 시작하기 전에

1. [CLAUDE.md](CLAUDE.md) — 개발 규칙의 단일 기준. 작업 전에 읽습니다.
2. [docs/README.md](docs/README.md) — 처음이면 여기서 시스템 지도를 봅니다.
3. 카드나 화면을 만진다면 [DESIGN-system.md](DESIGN-system.md)도 먼저 읽습니다.

```bash
python -m pip install uv==0.12.10
uv sync --group dev
python -m playwright install --with-deps chromium
python -m unittest discover -s tests -t .
```

`.env`가 없으면 대부분의 진입점이 첫 연결에서 자격증명 없음으로 멈춥니다. 테스트는
`.env` 없이도 전부 통과해야 합니다 — 통과하지 않는다면 그 테스트가 네트워크를 때리고
있다는 뜻입니다.

## 변경을 나누는 기준

큰 변경은 먼저 이슈로 의도를 적고 시작합니다. PR 하나는 **한 가지 판단**만 담습니다 —
리뷰어가 "이 변경이 옳은가"를 한 번만 물을 수 있어야 합니다.

리팩터링과 동작 변경을 한 PR에 섞지 마세요. 섞이면 diff가 커져서 동작이 바뀐 두 줄이
이동한 200줄에 묻힙니다.

## 테스트

- 표준 라이브러리 `unittest`만 씁니다. pytest 설정은 없습니다.
- **네트워크·DB를 때리지 않습니다.** 순수 변환과 계약을 검증합니다.
- 가드를 새로 쓰거나 고쳤으면 **위반을 일부러 주입해 실패를 확인**합니다. 통과만 보고
  끝내지 마세요 — 검사 대상이 사라지면 가드는 실패하지 않고 조용히 통과합니다.
- 주입은 한 번에 하나씩 합니다. 여러 개를 함께 넣으면 하나가 실패를 내는 동안 나머지가
  확인되지 않은 채 지나갑니다.

## 커밋과 문서

- 주석·docstring·커밋 메시지는 한국어, 식별자와 기술 용어는 영어입니다.
- 주석은 **"지금 왜 이런지"만** 적습니다. 경위는 git이 갖고 있습니다.
- 스키마·컬럼 이름을 바꿨으면 문서와 `prompts/`도 함께 고칩니다.
  `python -m unittest tests.test_docs_consistency`가 이것을 강제합니다.

## 절대 하지 않는 것

CLAUDE.md와 [AGENTS.md](AGENTS.md)에 같은 목록이 있고, 두 파일이 어긋나면 테스트가
잡습니다. 여기서는 기여자가 가장 자주 부딪히는 것만 다시 적습니다.

- `.env`·API key·broker 자격증명·개인 경로를 커밋하기.
- `LIVE_ENABLED`·`TOSS_LIVE_ENABLED`를 코드가 자동으로 바꾸게 만들기. 사람이 켭니다.
- 정비 보류 없이 하네스·실행 코드 고치기
  (`python -m investment_agent.operations.commands.harness_switch --maintenance on` 먼저).
- LLM에게 hard risk limit·최종 portfolio weight·broker 실행 권한 넘기기.
- 대량 읽기에 `select_all_paged()` 빠뜨리기 — 1,000행에서 조용히 잘립니다.
- Discord 채널·역할·권한을 UI에서 손보기. `notifications/discord_admin/`이 SSOT입니다.
- 카드 채널에 `@everyone` 채널 deny 달기 — 카드가 조용히 안 나갑니다.
- 생성물(`scratch/`, `artifacts/`, 로컬 DB 파일) 커밋하기.

## DB 선언

스키마 변경은 `db/` 아래 선언 파일에서만 합니다. 원격 Supabase 적용은 코드 변경이 아니라
**운영자의 별도 행위**입니다 — PR이 스스로 적용하지 않습니다.

적용이 끝난 `ALTER`·일회성 `UPDATE`는 남기지 말고 `CREATE TABLE`에 접어 넣습니다. 스키마
파일은 현재 모양만 선언합니다.

## 보안 문제를 발견했다면

공개 이슈에 적지 마세요. [SECURITY.md](SECURITY.md)의 절차를 따릅니다.

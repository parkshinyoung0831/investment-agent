# 오픈소스 공개 준비도 — 공개 전 점검과 알려진 제한

이 저장소는 실주문 경로와 개인 계좌 자격증명을 다루는 시스템입니다. 코드를 공개해도
**안전한 상태**와 그렇지 않은 상태가 뚜렷이 갈리므로, 공개 전에 확인할 것을 여기 모읍니다.

## 공개 전 점검

### 1. 비밀값이 이력에 남아 있지 않은가

`.gitignore`가 `.env`와 자격증명을 막고 있지만, **과거에 한 번 커밋됐다면 지금 지워도
이력에 남습니다.**

```bash
git log --all --full-history --oneline -- .env .env.local
git grep -nI -e "SUPABASE_SERVICE_KEY" -e "DISCORD_BOT_TOKEN" -e "TOSS_" -- ':!docs' ':!*.md'
```

둘 다 비어야 합니다. 이력에 남아 있다면 공개 전에 그 키를 **폐기하고 재발급**합니다 —
이력 재작성보다 확실합니다.

### 2. 생성물이 추적되고 있지 않은가

```bash
git ls-files | grep -E "^(data/local|artifacts|scratch)/"
git ls-files | grep -E "\.(duckdb|sqlite3|parquet|log)$"
```

로컬 DB·Parquet·렌더 결과·로그는 추적 대상이 아닙니다. 걸리는 것이 있으면 `.gitignore`가
아니라 **인덱스에서** 빼야 합니다(`git rm --cached`).

### 3. 개인 경로와 계좌 식별자

문서·주석·테스트 fixture에 개인 장비의 절대 경로나 계좌 번호, broker account hash가
남아 있지 않은지 봅니다. 경로는 저장소 뿌리 기준 상대 경로로, 값은 `{TICKER}` 같은
자리표시자로 적습니다. `tests/test_repo_conventions.py`가 절대 경로를 자동으로 잡습니다.

### 4. 라이브 실행이 꺼져 있는가

```bash
git grep -n "LIVE_ENABLED\|TOSS_LIVE_ENABLED" -- ':!docs' ':!*.md'
```

기본값이 꺼짐이고, 코드가 자동으로 켜는 경로가 없어야 합니다. 안전 플래그는 모르는 값을
꺼진 것으로 읽습니다(fail-closed).

### 5. 테스트가 네트워크 없이 통과하는가

```bash
python -m unittest discover -s tests -t .
```

`.env` 없는 기계에서 전부 통과해야 합니다. 통과하지 않으면 그 테스트가 실제 자격증명에
기대고 있다는 뜻이고, 공개 후 기여자에게는 재현 불가능한 실패로 보입니다.

### 6. 문서가 실제 저장소를 말하는가

```bash
python -m unittest tests.test_docs_consistency
```

문서가 부르는 표 이름과 상대 링크가 실재하는지 봅니다. 문서는 틀려도 아무도 알려주지
않으므로 이것이 유일한 방어입니다.

## 알려진 제한

공개하더라도 **그대로 돌려서 같은 결과를 얻을 수는 없습니다.** 무엇이 빠지는지 미리
적어 둡니다.

| 제한 | 이유 |
|---|---|
| 라이선스 미선언 | 루트에 `LICENSE`가 없습니다. 사용 권한을 추정하지 마세요 |
| 자격증명 필요 | SEC User-Agent, FRED·ECOS·EIA key, Supabase, Discord 봇 — 각자 발급해야 합니다 |
| 고정 IP 전제 | 토스증권 경로는 허용 IP가 등록된 기계에서만 동작합니다 |
| 로컬 저장소 비공개 | 로컬 SQLite·DuckDB·Parquet은 커밋하지 않습니다. 처음 실행은 빈 상태에서 시작합니다 |
| Discord 서버 구조 | `discord_admin` 선언은 있지만 실제 길드·채널 ID는 각자 만들어야 합니다 |
| 데이터 재배포 없음 | SEC·Yahoo·FRED 데이터를 담지 않습니다. 각 제공자 약관을 따릅니다 |

## 공개 저장소 정책 문서

- [기여 가이드](../CONTRIBUTING.md)
- [보안 정책](../SECURITY.md)
- [행동 강령](../CODE_OF_CONDUCT.md)
- [서드파티 고지](../THIRD_PARTY_NOTICES.md)

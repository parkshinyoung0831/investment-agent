# Third-party data notice — `gaap_mappings.json`

이 디렉터리의 `gaap_mappings.json`은 SEC us-gaap 태그를 표준 재무 개념 후보로 연결하는 **vendored reference data**다. 파일을 저장소에 포함해 결정적으로 읽으며, Fundamentals 런타임이 edgartools Python 패키지를 import하거나 edgartools parser를 호출하지 않는다.

## 출처와 현재 스냅샷

| 항목 | 값 |
|---|---|
| Upstream project | [dgunning/edgartools](https://github.com/dgunning/edgartools) |
| Upstream release | edgartools **5.53.0** |
| Upstream path | `edgar/xbrl/standardization/gaap_mappings.json` (PyPI wheel `edgartools-5.53.0-py3-none-any.whl`) |
| Local path | `src/investment_agent/data/fundamentals/data/gaap_mappings.json` |
| Local byte size | **3,741,595 bytes** |
| Local top-level entries | **2,924** |
| Local SHA-256 | `6355648d056e171cdb2d280e042181f1c3486a10c2d21eb0ad818b8ec387ff70` |
| Metadata verification date | 2026-08-29 |
| License | MIT License |
| Copyright | Copyright (c) 2022-present Dwight Gunning `<dgunning@gmail.com>` |

Upstream release 목록은 [edgartools releases](https://github.com/dgunning/edgartools/releases)에서 확인한다. SHA-256은 **이 저장소에 커밋된 현재 바이트**의 해시다. upstream 파일을 JSON으로 다시 포맷하면 의미가 같아도 byte hash가 달라질 수 있다.

## 5.36.0 -> 5.53.0에서 바뀐 것

의미는 하나도 바뀌지 않았다. 항목 2,924개가 그대로이고 추가·제거가 없으며
`standard_tags[0]`·`confidence`·`is_total` 변경도 0건이다. 줄어든 바이트는 포맷 차이다.

특히 **배당 지급액 오매핑은 upstream에서 고쳐지지 않았다.**
`PaymentsOfDividendsCommonStock`은 여전히 `NetCashFromFinancingActivities`로,
`PaymentsOfDividends`는 `DistributionsToMinorityInterests`로 간다. 사전을 올려도
이 오류는 사라지지 않으므로 `CORE_OVERRIDES`가 유일한 교정 지점이다.

같은 릴리스의 `concept_mappings.json`은 이 파일의 후속판이 아니다. 표시 라벨
100개를 태그 목록에 연결하는 별개의 작은 맵이라 벌크 사전을 대체할 수 없다.

## 프로젝트에서 사용하는 방식

`src/investment_agent/data/fundamentals/domain/taxonomy/gaap_concepts.py`가 import 시 이 JSON을 직접 읽는다.

1. 각 raw tag의 `standard_tags` 첫 항목과 confidence·total metadata를 기본 후보로 읽는다.
2. 표준 태그를 프로젝트의 `snake_case` column key로 바꾼다.
3. 프로젝트 `CORE_OVERRIDES`, equity fallback, column policy, unit·충돌 정책, 제외 목록을 사전보다 우선 적용한다.
4. 지원하는 wide 컬럼만 저장한다. 컬럼별 선택 manifest는 변환 중 검증하고,
   영속 행에는 SEC accession·공시일·form과 semantic policy version을 남긴다.
5. 파일이 없거나 유효한 JSON이 아니면 warning을 기록하고 raw tag의 `snake_case` fallback을 사용한다.

현재 프로젝트 semantic policy version은 `v1`이다. 이 값은 edgartools 버전과 같은 개념이
아니다 — vendored 사전이 후보군을 제공하고, 정책 버전은 그중 무엇을 실제 wide 값으로
선택했는지를 식별한다. 정책이 실제로 달라질 때만 다음 세대로 올린다.

기업 전체 재무 정책(`v1`)이 고정하는 것:

- 영구 비지배지분과 임시자본을 분리한다.
- 대차대조표 기준일과 다른 instant fact는 제외한다.
- 임시자본은 구성요소를 합산하고, 검증된 상환가능 비지배지분 공정가치 태그를 포함한다.
- SPAC 잔여자본은 신탁자산으로 확인된 것만 제한적으로 복원한다.
- 총자본 차이로 얻은 비지배지분은 자산·부채·임시자본 회계항등식으로 교차 검증한다.

세그먼트 정책(`v1`)은 2차원(주 축 × 보조 축) 교차 세그먼트를 1차원 부모 아래 계층으로
저장한다.

yfinance가 복수 클래스마다 동일한 전사 주식수를 제공하므로, 클래스별
`share_class_snapshots` 원천이 충분하지 않으면 valuation을 표시하지 않는다.

`data` dependency-group의 edgartools는 다른 파이프라인의 선택적 13F shadow 비교용이다. 이 JSON을 읽기 위해 edgartools를 fundamentals 경로의 의존성으로 끌어들이지 않는다.

## 무결성 확인

저장소 루트에서 다음 명령으로 현재 파일의 byte 수와 SHA-256을 확인한다.

```bash
python -c "from hashlib import sha256; from pathlib import Path; p=Path('src/investment_agent/data/fundamentals/data/gaap_mappings.json'); print(p.stat().st_size); print(sha256(p.read_bytes()).hexdigest())"
```

top-level entry 수는 다음처럼 확인한다.

```bash
python -c "import json; from pathlib import Path; p=Path('src/investment_agent/data/fundamentals/data/gaap_mappings.json'); print(len(json.loads(p.read_text(encoding='utf-8'))))"
```

기대값은 각각 `3741595`, 위 표의 SHA-256, `2924`다. 하나라도 다르면 의도한 사전 갱신인지 먼저 확인하고 이 NOTICE의 메타데이터를 함께 갱신한다.

## 업데이트와 검증 절차

단순히 upstream `main`의 최신 파일로 덮어쓰지 않는다. 재현 가능한 tagged release 또는 commit을 선택한다.

1. upstream release와 commit을 정하고 해당 commit의 정확한 `edgar/xbrl/standardization/gaap_mappings.json`을 가져온다.
2. JSON이 object인지, 각 entry가 object인지, `standard_tags`가 list인지 검증한다.
3. 이전 파일과 semantic diff를 만든다. 추가·삭제·변경 tag 수와 `standard_tags`, confidence, `is_total`, company count 변화를 따로 검토한다.
4. 프로젝트 override·column policy·제외 목록이 참조하는 중요 tag를 표본 검증한다. 사전 값이 바뀌어도 프로젝트 정책 우선순위가 의도대로인지 확인한다.
5. 이 문서의 release, commit, source link, byte size, entry count, SHA-256, verification date를 새 값으로 갱신한다.
6. mapping 변경이 영구 wide 결과를 바꿀 수 있으면 `SEMANTIC_POLICY_VERSION`을 올리고 `filing_processing.mapping_version` 기반 재처리·백필 범위를 결정한다.
7. 다음 회귀 테스트와 전체 오프라인 suite를 실행한다.

```bash
python -m unittest \
  tests.test_fundamentals_mapping_policy \
  tests.test_fundamentals_integrity \
  tests.fundamentals.domain.test_domain_contracts

python -m unittest discover -s tests -t .
```

8. 대표 기업에서 tag → column key, Q4 유도, mapping conflict JSON 로그,
   wide row의 accession·공시일·mapping version을 비교한다.
9. live DB에 반영할 때는 새 mapping version의 대상 accession을 재처리한 뒤 row count·NULL 변화·대표 지표·상태 분포를 검증한다.

업데이트 PR에는 upstream version/commit, semantic diff 요약, 새 hash, policy version 변경 여부, 재처리 계획과 테스트 결과를 남긴다.

## MIT License

Copyright (c) 2022-present Dwight Gunning `<dgunning@gmail.com>`

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

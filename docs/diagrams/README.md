# 다이어그램 — 소스와 생성물을 가른 폴더

폴더가 **무엇을 손으로 고쳐도 되는지**를 말한다.

```text
docs/diagrams/
  src/    *.json   ← 손으로 고치는 유일한 곳 (Archify 명세)
  html/   *.html   ← 생성물. 확대·테마 전환·흐름 추적이 되는 인터랙티브 판
  svg/    *.svg    ← 생성물. GitHub Markdown이 직접 렌더하는 미리보기
```

## 고치는 법

`src/`의 JSON을 고치고 한 명령을 돌린다. `html/`과 `svg/`는 **절대 손으로 편집하지 않는다** —
고친 순간 다음 빌드가 지우고, 소스와 생성물이 조용히 갈라진다.

```bash
python scripts/build_diagrams.py
```

`JSON → validate → HTML → SVG` 한 방향으로만 흐르고 결정적이다. 같은 소스는 같은 출력을
내므로 `git diff`가 비어 있으면 실제로 최신이라는 뜻이다.

node가 없는 환경에서는 마지막 단계만 따로 돌릴 수 있다.

```bash
python scripts/export_diagram_svg.py           # html/ → svg/
python scripts/export_diagram_svg.py --check   # 쓰지 않고 낡았는지만 확인
```

## 왜 SVG가 따로 있는가

GitHub Markdown은 HTML을 렌더하지 않는다. 저장소의 `.html`을 상대 링크로 걸어도 raw 소스나
다운로드로 갈 뿐이라, **그림이 저장소에 있어도 아무도 보지 못한다.** 그래서 Markdown에는
SVG를 붙이고, 인터랙티브 판은 `html/`을 브라우저로 직접 열어서 본다.

Archify CLI에는 SVG export 명령이 없다. `export_diagram_svg.py`가 납품 HTML 안의 inline
`<svg>`를 떼고, 그것이 의존하는 CSS 변수와 클래스 규칙만 골라 SVG 안으로 인라인한다.
색 처리는 아래 「색은 다크가 기본이다」를 본다.

## 현재 다이어그램

| 파일 | 유형 | 답하는 질문 | 실리는 곳 |
|---|---|---|---|
| `overview` | architecture | 수집에서 체결·성과까지 전체가 어떻게 이어지는가 | [루트 README](../../README.md) |
| `promotion-ladder` | lifecycle | 어느 단계까지 올라갈 수 있고 무엇이 막는가 | [루트 README](../../README.md) |
| `system-architecture` | architecture | 패키지 단위로 무엇이 무엇을 알아도 되는가 | [시스템 아키텍처](../SYSTEM_ARCHITECTURE.md) |
| `pipeline` | dataflow | 수집이 어디서 와서 어디로 가는가 | [데이터](../DATA.md) |
| `trading-analysis` | dataflow | 근거에서 신호까지 무엇이 계산되는가 | [투자 시스템](../INVESTMENT_SYSTEM.md) |
| `trading-target` | dataflow | 신호가 어떻게 목표 비중이 되는가 | [투자 시스템](../INVESTMENT_SYSTEM.md) |
| `execution-lifecycle` | lifecycle | 주문 하나가 어떤 상태를 지나는가 | [실행과 안전](../EXECUTION_AND_SAFETY.md) |
| `execution-runbook` | workflow | 사람이 실행할 때 어떤 관문을 지나는가 | [실행과 안전](../EXECUTION_AND_SAFETY.md) |
| `earnings-pipeline` | sequence | 실적 공시가 어떻게 카드가 되는가 | [운영](../OPERATIONS.md) |

모든 명세는 **showcase 품질**(9개 구성 검사, 오류·경고 0)을 통과해야 한다. 통과하지 못하면
빌드가 실패한다.

## 폭이 글자 크기를 정한다

Archify는 **1440px 뷰포트**를 기준으로 가독성을 검사하는데, GitHub 본문은 **약 830px**다.
Markdown에 붙은 SVG는 그 폭에 맞춰 축소되므로, `viewBox` 폭이 곧 글자 크기다 —
세부 글자는 7px로 고정이라 실제 크기는 `7 × 830 / viewBox폭`이 된다.

| viewBox 폭 | 830px에서 세부 글자 | 판정 |
|---|---|---|
| 880 이하 | 6.6px 이상 | 본문에서 그대로 읽힌다 |
| 900~980 | 6.0~6.5px | 읽히지만 여유가 없다 |
| 1000 이상 | 6.0px 미만 | 이미지를 눌러 원본으로 보거나 `html/`을 연다 |

**dataflow는 더 좁힐 수 없다.** 필요한 최소 폭이 `208 + 215 × 단계수`로 고정이라 5단계는
1068 미만이 되지 않는다(레이블을 아무리 줄여도 값이 같다 — 검증기가 단계 수만 본다).
`pipeline` · `trading-analysis` · `trading-target`이 여기 해당하고, 단계를 합치는 것은
파이프라인 모양을 거짓으로 그리는 일이라 하지 않았다. `system-architecture`도 패키지
16개와 경계 4개를 1440 기준으로 배치한 것이라 좁히면 간선 레이블이 서로 붙는다.

그래서 이 넷은 **본문 미리보기 + 원본/인터랙티브 판**의 두 단계로 읽는다. 폭이 넓은
그림을 싣는 문서는 SVG 바로 아래에 어디서 크게 볼 수 있는지 한 줄을 둔다.

폭을 재는 방법:

```bash
python scripts/check_diagram_width.py    # viewBox 폭과 830px에서의 실제 글자 크기
```

## 색은 다크가 기본이다

Archify가 설계한 기본 모습이 dark라서 SVG도 그것을 기본으로 굽는다. 밝은 화면으로 보는
사람을 위해 light 팔레트를 `@media (prefers-color-scheme: light)`에 함께 실어 두므로,
GitHub의 어느 테마에서도 읽힌다. 배경은 `<rect fill="var(--bg)">`로 **명시적으로 칠한다** —
칠하지 않으면 캔버스가 투명해져 반대 테마에서 글자가 바탕에 묻힌다.

## 조용히 틀리는 것

- **생성물을 손으로 고치기.** 다음 빌드가 지운다. `DiagramArtifactTest`가 잡는다.
- **코드에 없는 간선 그리기.** 그림은 틀려도 404를 내지 않고 그럴듯하게 남는다. 노드·간선은
  실제 import·전이 맵·선언 파일로 확인한 것만 그린다.
- **아직 만들지 않은 설계를 현재 구조처럼 그리기.** 그림은 지금 무엇인가만 말한다.
- **`src/`에 JSON만 추가하고 빌드를 안 돌리기.** 문서가 없는 그림을 가리키게 된다.
  `scripts/build_diagrams.py`의 `DIAGRAMS` 목록에도 함께 등록해야 빌드 대상이 된다.

# 디자인 시스템 — 알림 카드와 대시보드 UI의 단일 기준

> **상태:** Canonical SSOT
>
> **버전:** 1.0.0
>
>
> **적용 범위:** Streamlit 대시보드, Discord PNG 카드, Discord embed, 운영·승인 화면

이 문서는 이 저장소의 UI와 알림 카드가 따라야 하는 단일 디자인 기준이다. 라이트·다크 모드와 투자 데이터의 의미를 안전하게 표현하기 위해 이 프로젝트가 직접 설계한 제품 전용 시스템이며, 색·타이포·형태·카피 규칙과 그 설계 근거(§20)를 이 문서 하나로 완결한다.

**규범과 구현 현황은 다르다.** 이 문서는 목표 계약이며, 모든 화면이 이미 준수한다는 뜻은 아니다. 현재 확인된 이행 항목은 §16.4에서 구분한다. 저장소 구조·권한·실행 안전은 [CLAUDE.md](CLAUDE.md)가 우선하며, 이 문서로 기능이나 주문 권한을 추가하지 않는다.

---

## 1. 한 문장 정의

**복잡한 투자 사실을 유능한 친구처럼 정리하고, 사용자가 지금 무엇을 봐야 하고 다음에 무엇을 해야 하는지 차분하게 알려주는 금융 인터페이스다.**

화면은 두 테마 모두 명료하며, 차가운 중성색 위에 Brand Blue(`#3182F6`) 계열 하나만 브랜드 강조색으로 쓴다. 이 제품에서는 상승을 초록, 하락을 빨강으로 고정한다. 지역별 관습이 다르므로 방향을 좋고 나쁨으로 오해하지 않도록 부호·문장과 함께 쓴다.

---

## 2. 핵심 결정과 우선순위

### 2.1 핵심 결정 요약

| 영역 | 결정 |
|---|---|
| 제품 철학 | 이해 비용을 줄이고 다음 행동을 안내하는 것을 최우선으로 삼는다. |
| 브랜드 색 | Brand Blue `#3182F6` 계열만 브랜드 색으로 쓰며, 실제 행동색은 접근성 보정 토큰을 따른다. |
| 중성색 | cool-blue grey를 라이트 모드의 기준으로 삼는다. |
| 금융 상승·하락 | 원색은 상승 `#05B169`, 하락 `#CF202F`이며 실제 텍스트는 §5.5의 테마별 보정색을 쓴다. |
| 다크 모드 | 라이트 모드의 cool-neutral 성격을 유지한 별도 시맨틱 매핑을 이 시스템에서 직접 정의한다. |
| 타이포 | 본문은 Pretendard, 데이터 숫자는 JetBrains Mono를 쓴다. |
| 형태·간격 | 4px 리듬, 둥근 카드, pill CTA, 평면 표면을 쓴다. |
| 페이지 밀도 | 첫 화면은 단순하게, 상세 분석은 밀도를 올리되 계층은 유지한다. |
| 카피 | 해요체, 일상어, Navigating Error 원칙을 쓴다. |
| 다크 hero·카드 중첩 | 상시 브랜드 장식이 아니라 중요한 요약·리포트 표면에만 쓴다. |
| 두 번째 브랜드 색·전용 라이선스 서체 | 도입하지 않는다. |

### 2.2 충돌 시 우선순위

규칙이 충돌하면 다음 순서로 결정한다.

1. 데이터의 사실성과 금융 의미
2. 접근성 및 안전
3. 사용자의 다음 행동
4. 브랜드 일관성
5. 장식적 완성도

예를 들어 상승 값이 투자자에게 불리하더라도 값 자체는 상승 색으로 표시한다. 불리하다는 판단은 별도의 경고 문장이나 상태 라벨로 설명한다. 색을 사실보다 앞세우지 않는다.

### 2.3 규칙의 강도와 적용 단위

- `필수`, `한다`, `금지`는 준수 기준이고, `권장`, `기본`은 명시된 조건에서 조정할 수 있는 기본값이다. 예시는 새로운 예외를 만들지 않는다.
- 컴포넌트별 세부 규칙은 공통 규칙을 구체화한다. 예외는 적용 매체·조건·대체 표현을 함께 적어야 하며, §2.2의 상위 원칙을 무효화할 수 없다.
- **한 화면**은 현재 활성 페이지 또는 모달의 작업 문맥이다. 채움 Primary는 **최대 하나**이며, 읽기 전용 리포트는 없어도 된다. 모달이 열리면 배경 행동은 비활성화한다.
- px는 별도 표기가 없으면 CSS px다. 크기 표는 기본값이며 확대·줄바꿈 시 내용에 맞게 높이를 늘린다. 4px 리듬은 간격 기준으로, 선 두께·서체 크기까지 4의 배수로 강제하지 않는다.

### 2.4 매체별 적용 범위

| 매체 | 직접 제어하는 것 | 적용 방식과 한계 |
|---|---|---|
| 웹 대시보드·운영 화면 | 레이아웃·테마·서체·접근 가능한 상호작용 | 반응형·키보드·상태 규칙 적용. 현재 대시보드는 읽기 전용이며 승인 동작은 제공하지 않는다. |
| Discord PNG·차트 이미지 | 이미지 안의 색·서체·고정 레이아웃 | hover·focus·클릭을 요구하지 않는다. 핵심 값·기준 시각·위험을 본문에도 쓰고 상세는 원문 또는 접근 가능한 표로 연결한다. |
| Discord native embed·버튼 | 내용·순서·링크·플랫폼이 제공하는 옵션 | 서체·CSS·사용자 테마·임의 버튼색을 강제하지 않는다. 의미·부호·상태 라벨을 지키고 플랫폼 기본 컨트롤을 사용한다. |

PNG 안에 동작하는 것처럼 보이는 버튼을 그리지 않는다. Embed에는 숫자 비교가 필요한 짧은 구간만 inline code/code block을 쓰고 JetBrains Mono 사용을 전제로 삼지 않는다. Embed의 native 색 rail은 장식 보더 금지(§8.2)의 매체 예외이며, 생략 또는 중성색을 기본으로 하고 시스템 경고에만 `status.*`를 쓴다. 방향색을 rail에 쓰거나 승인/거절을 상승/하락으로 치환하지 않는다. 제어 가능한 필드는 [Discord Embed 명세](https://docs.discord.com/developers/resources/message#embed-object)를 따른다.

---

## 3. 제품 철학

### 3.1 먼저 이해시키고, 그다음 행동시킨다

- 첫 화면은 “현재 상태 → 중요한 변화 → 근거 → 가능한 행동” 순서로 읽힌다.
- 숫자를 먼저 쏟아내지 않는다. 사용자가 숫자의 의미를 알 수 있는 라벨과 기준 시각을 함께 준다.
- 기본 정보는 접지 않는다. 접는 것은 더 깊은 근거와 원자료다.
- 한 화면의 주된 질문은 하나여야 한다. 질문이 둘이면 섹션이나 단계로 나눈다.

### 3.2 사용자의 인지 부하를 대신 짊어진다

- 시스템이 계산할 수 있는 비교, 단위 변환, 최신성 판정은 사용자에게 떠넘기지 않는다.
- “왜 이런 상태인지”와 “다음에 무엇을 확인하면 되는지”를 같은 문맥에 둔다.
- 빈 값, 실패, 미지원, 아직 발표되지 않음을 모두 `0`으로 합치지 않는다.
- 데이터 출처와 기준 시각을 숨기지 않되, 본문보다 한 단계 낮은 위계로 둔다.

### 3.3 단순함은 정보 삭제가 아니라 우선순위다

- 요약에는 판단을 바꾸는 정보만 둔다.
- 상세에는 요약의 결론을 검증할 근거를 둔다.
- 원자료는 감사와 재현에 필요할 때만 둔다.
- 같은 문맥에서 목적 없이 값을 반복하지 않는다. 요약↔상세 연결, 접근성 대체 텍스트, 승인 대상 재확인에는 동일 기준 시각의 값을 반복할 수 있다.

### 3.4 차분하지만 모호하지 않다

- 과장, 흥분, 공포를 유도하지 않는다.
- 확실하지 않은 정보는 “예정”, “추정”, “기준 오래됨”처럼 불확실성 자체를 말한다.
- 주문, 승인, 손실 한도처럼 위험한 행동은 결과를 구체적으로 적는다.
- 확정되지 않은 전망을 성공·실패 색으로 단정하지 않는다.

---

## 4. 토큰 구조

색은 다음 3단계로만 사용한다.

```text
Primitive                 Semantic                    Component
brand.blue.600      →     action.primary.bg    →     button.primary.bg
grey.900 / grey.100 →     text.primary         →     metric.value
direction.up.base   →     data.direction.up     →     metric.delta.up
```

- **Primitive:** 색 자체다. 컴포넌트에서 직접 사용하지 않는다.
- **Semantic:** 역할을 말한다. 제품 코드는 기본적으로 이 단계만 참조한다.
- **Component:** 특별한 상태 조합이 반복될 때만 만든다.
- Semantic·Component 이름에는 `light`, `dark`, 구체 색 이름을 넣지 않는다. Primitive는 원색·톤을 식별하므로 `brand.blue.500`, `dark.900` 같은 이름을 허용한다. 테마는 같은 semantic key의 값만 바꾼다.
- `success`, `danger`, `up`, `down`을 서로 대체하지 않는다.

---

## 5. 색 시스템

### 5.1 브랜드 원색

| Primitive | 값 | 역할 |
|---|---:|---|
| `brand.blue.50` | `#E8F3FF` | 약한 선택·정보 표면 |
| `brand.blue.500` | `#3182F6` | 브랜드 기준 원색, 1차 행동 계열의 기준 |
| `brand.blue.600` | `#1B64DA` | 흰 라벨 CTA의 기본 배경 |
| `brand.blue.700` | `#1554B8` | CTA hover |
| `brand.blue.800` | `#10479F` | CTA pressed |

채움 Brand Blue 계열은 1차 행동에만 쓴다. 접근성 보정색도 같은 브랜드 계열이며 두 번째 브랜드 색이 아니다. 링크·focus·선택은 각각 `text.brand`, `focus.ring`, `bg.brand.weak`로 제한하고 탐색 전체를 파랗게 만들지 않는다. 차트는 §10의 중성 시리즈를 사용한다. 흰색 글자와 `#3182F6`는 약 `3.71:1`이므로 일반 버튼 라벨에는 §5.9의 보정된 배경을 쓴다.

### 5.2 라이트 모드 중성 원색

| Primitive | 값 | 대표 역할 |
|---|---:|---|
| `grey.900` | `#191F28` | primary text |
| `grey.800` | `#333D4B` | strong text |
| `grey.700` | `#4E5968` | secondary text |
| `grey.600` | `#6B7684` | tertiary text |
| `grey.500` | `#8B95A1` | 중성 원색; 라이트의 작은 정보 텍스트에는 사용하지 않음 |
| `grey.400` | `#B0B8C1` | 중성 보더; disabled 글자색은 semantic map 사용 |
| `grey.300` | `#D1D6DB` | strong divider |
| `grey.200` | `#E5E8EB` | default divider |
| `grey.100` | `#F2F4F6` | secondary surface |
| `grey.50` | `#F9FAFB` | app canvas |
| `white` | `#FFFFFF` | elevated surface |

### 5.3 다크 모드 중성 원색

아래 값은 라이트 모드의 차가운 중성색과 계층 원칙을 다크 모드로 확장해 이 제품에서 직접 정의한 값이다.

| Primitive | 값 | 대표 역할 |
|---|---:|---|
| `dark.950` | `#101318` | app canvas |
| `dark.900` | `#171B22` | primary surface |
| `dark.850` | `#202630` | secondary surface |
| `dark.800` | `#252D38` | elevated surface |
| `dark.750` | `#2B3441` | strong surface |
| `dark.700` | `#333D4B` | default divider |
| `dark.600` | `#4E5968` | strong divider |

다크 모드에서도 순수 검정 `#000000`을 넓은 캔버스로 쓰지 않는다. 카드가 배경과 구분될 만큼만 밝게 올라오며, 깊이는 채도나 강한 그림자가 아니라 표면 단계로 만든다.

### 5.4 금융 방향 원색

| Primitive | 값 | 의미 |
|---|---:|---|
| `direction.up.base` | `#05B169` | 값이 기준보다 상승하거나 증가함 |
| `direction.down.base` | `#CF202F` | 값이 기준보다 하락하거나 감소함 |

이 두 색은 **방향만** 말한다.

- 금리 상승은 초록으로 표시할 수 있지만 “좋음”을 뜻하지 않는다.
- 부채 감소도 빨강인 감소 방향색을 쓰되, 별도 문장으로 재무상 긍정임을 설명한다.
- 모델 판정, 승인 여부, 데이터 품질, 오류 상태에는 방향 색을 재사용하지 않는다.
- 상승·하락 색은 **텍스트 전용**이다. 방향 화살표 글리프는 부호·문장을 보조할 수 있다. 차트 선·점·막대·면적, 카드·배지·표 셀 배경에는 쓰지 않는다.
- 기준값, 비교 기간, 변화 단위를 함께 정의한다. 별도 도메인 기준이 없으면 변화량의 원값 부호로 판정하며 임의의 보합 임계값을 만들지 않는다. 임계값이 있는 보합도 실제 수치는 그대로 표시한다(§6.3).

### 5.5 접근성 보정 방향 토큰

방향 원색은 Primitive로 보존하며 제품의 숫자는 아래 Semantic을 쓴다. 큰 글자라고 원색으로 되돌리지 않는다.

| Semantic | Light | Dark | 사용 |
|---|---:|---:|---|
| `data.direction.up` | `#007A50` | `#05B169` | 상승 텍스트 |
| `data.direction.down` | `#CF202F` | `#FF6673` | 하락 텍스트 |
| `data.direction.flat` | `#5E6B7A` | `#8B95A1` | 보합·0 변화 |

대비 근거:

- `#05B169` on white는 약 `2.80:1`이므로 큰 글자의 `3:1`도 통과하지 않는다.
- `#CF202F` on `#101318`은 약 `3.46:1`이며 더 밝은 다크 표면에서는 더 낮다.
- light up `#007A50`은 white에서 약 `5.39:1`, `bg.surface.subtle`에서 약 `4.88:1`이다.
- dark down `#FF6673`은 `bg.canvas`에서 약 `6.56:1`, `bg.surface.elevated`에서 약 `4.90:1`이다.

위 텍스트 토큰의 기본 배경은 `bg.canvas`, `bg.surface`, `bg.surface.subtle`, `bg.surface.elevated`다. `bg.surface.strong`에는 작은 방향·상태·tertiary 텍스트를 두지 않고 `text.primary`/`text.secondary`로 의미를 적는다. tint·선택·이미지 위 조합은 합성된 실제 배경으로 별도 검증한다. 흰 배경에서의 통과가 모든 배경에서의 통과를 뜻하지 않는다.

색만으로 방향을 전달하지 않는다. 변화량에는 `+3.2%`, `−1.8%`처럼 부호를 쓰고 숫자 없는 요약에는 “증가”, “감소”를 적는다. 화살표만으로 대체하지 않는다.

### 5.6 상태색과 방향색의 분리

| Semantic | Light | Dark | 의미 |
|---|---:|---:|---|
| `status.info` | `#1B64DA` | `#64A8FF` | 안내·연결·진행 |
| `status.success` | `#00773A` | `#4FD18B` | 작업 완료·검증 통과 |
| `status.warning` | `#B54708` | `#FFB454` | 주의·오래된 데이터·확인 필요 |
| `status.danger` | `#D22030` | `#FF6673` | 실패·차단 상태의 텍스트·아이콘 |

동일한 계열색이 시각적으로 가까워도 코드 토큰은 분리한다. `data.direction.down`을 API 오류에 쓰거나 `status.success`를 수익 상승에 쓰면 안 된다.

저평가·재무 개선 같은 **투자 해석**은 방향이나 작업 성공이 아니다. 별도 라벨과 기준·기간을 중립색으로 설명하고, 계산된 위험 경고만 `status.warning`/`status.danger`로 분리한다. `higher_better`를 이유로 상승·하락 색을 뒤집지 않는다. Danger 버튼 배경은 상태 텍스트 토큰이 아닌 §5.9의 행동 토큰을 쓴다.

### 5.7 라이트·다크 시맨틱 매핑

| Semantic token | Light | Dark |
|---|---:|---:|
| `bg.canvas` | `#F9FAFB` | `#101318` |
| `bg.surface` | `#FFFFFF` | `#171B22` |
| `bg.surface.subtle` | `#F2F4F6` | `#202630` |
| `bg.surface.elevated` | `#FFFFFF` | `#252D38` |
| `bg.surface.strong` | `#E5E8EB` | `#2B3441` |
| `bg.brand.weak` | `#E8F3FF` | `rgba(49,130,246,.16)` |
| `text.primary` | `#191F28` | `#F2F4F6` |
| `text.secondary` | `#4E5968` | `#B0B8C1` |
| `text.tertiary` | `#5E6B7A` | `#8B95A1` |
| `text.disabled` | `#4E5968` | `#B0B8C1` |
| `text.brand` | `#1B64DA` | `#64A8FF` |
| `text.inverse` | `#FFFFFF` | `#191F28` |
| `border.default` | `#E5E8EB` | `#333D4B` |
| `border.subtle` | `rgba(0,0,0,.08)` | `rgba(255,255,255,.08)` |
| `border.strong` | `#B0B8C1` | `#4E5968` |
| `border.control` | `#5E6B7A` | `#8B95A1` |
| `focus.ring` | `#1B64DA` | `#64A8FF` |
| `overlay.scrim` | `rgba(0,0,0,.56)` | `rgba(0,0,0,.72)` |

### 5.8 색 사용 금지

- Brand Blue를 하락, 손실, 매도 의미로 쓰지 않는다.
- 방향색으로 면을 채우지 않는다. 시스템 상태의 작은 tint(§9.5)와 Danger 행동(§5.9)은 별도 상태·행동 토큰으로만 허용한다.
- 노랑을 브랜드 보조색처럼 반복하지 않는다.
- 여러 데이터 시리즈를 무지개 팔레트로 구분하지 않는다.
- 선택 상태와 좋은 상태를 같은 색 하나로 표현하지 않는다.
- 다크 모드를 라이트 색의 단순 반전으로 만들지 않는다.
- hex를 템플릿과 페이지 코드에 직접 흩뿌리지 않는다.

### 5.9 행동색 조합

| Semantic token | Light | Dark |
|---|---:|---:|
| `action.primary.bg` | `#1B64DA` | `#1B64DA` |
| `action.primary.hover` | `#1554B8` | `#1554B8` |
| `action.primary.pressed` | `#10479F` | `#10479F` |
| `action.primary.fg` | `#FFFFFF` | `#FFFFFF` |
| `action.danger.bg` | `#B91C2B` | `#B91C2B` |
| `action.danger.hover` | `#A31624` | `#A31624` |
| `action.danger.pressed` | `#8C1220` | `#8C1220` |
| `action.danger.fg` | `#FFFFFF` | `#FFFFFF` |
| `action.disabled.bg` | `#E5E8EB` | `#2B3441` |
| `action.disabled.fg` | `#4E5968` | `#B0B8C1` |

Primary 기본 배경+흰 라벨은 약 `5.41:1`, Danger는 약 `6.43:1`이다. Hover·pressed도 이 쌍을 유지하며 임의의 overlay로 바꾸지 않는다. `text.inverse`는 반전 중성 표면용이며 버튼 라벨의 대체 토큰이 아니다. 버튼 경계를 반드시 식별해야 하는 배경 조합은 별도의 `border.control` 또는 대비를 검증한 outline을 제공한다.

---

## 6. 타이포그래피

### 6.1 서체

```css
--font-sans: "Pretendard Variable", Pretendard, -apple-system,
  BlinkMacSystemFont, "SF Pro Text", "Apple SD Gothic Neo",
  "Noto Sans KR", "Segoe UI", sans-serif;

--font-mono: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
```

- 제품 카피, 탐색, 라벨, 제목은 `--font-sans`를 쓴다.
- 가격, 수익률, 비율, 날짜, 시각, 수량, 순위, 표의 숫자는 `--font-mono`를 쓴다.
- 숫자와 한글이 한 문장에 섞이면 전체 문장을 mono로 바꾸지 않고 숫자 span만 분리한다.
- 유료 라이선스가 필요한 브랜드 전용 서체를 번들하지 않는다.

### 6.2 타입 스케일

| Token | Size / Line height | Weight | 용도 |
|---|---|---:|---|
| `display.1` | `56px / 1.20` | 700 | 넓은 화면 핵심 숫자·hero |
| `display.2` | `40px / 1.20` | 700 | 리포트 대표 수치 |
| `heading.1` | `28px / 1.30` | 700 | 페이지 제목 |
| `heading.2` | `24px / 1.30` | 700 | 큰 섹션 제목 |
| `heading.3` | `20px / 1.35` | 700 | 카드 그룹 제목 |
| `title.1` | `18px / 1.45` | 600 | 카드 제목 |
| `body.1` | `17px / 1.50` | 400 | 강조 본문 |
| `body.2` | `15px / 1.50` | 400 | 기본 본문 |
| `body.3` | `13px / 1.50` | 400 | 조밀한 표·보조 설명 |
| `label.l` | `17px / 1.25` | 700 | 큰 버튼·핵심 라벨 |
| `label.m` | `15px / 1.25` | 600 | 버튼·탭·필터 |
| `label.s` | `13px / 1.25` | 600 | 배지·표 헤더 |
| `caption` | `12px / 1.40` | 500 | 출처·기준 시각 |

제목은 `letter-spacing: -0.015em`에서 `-0.02em`, 본문은 `-0.005em`, 숫자는 `0`을 기본으로 한다. 영문 ALL CAPS를 섹션 제목이나 배지의 기본으로 쓰지 않는다. `body.3`·`label.s`·`caption`은 보조 정보에만 허용하며, 핵심 값·위험·행동 설명은 15px 이상으로 유지한다. PNG의 크기는 §7.5에서 별도로 검수한다.

### 6.3 금융 숫자 표기

- 모든 표·카드 숫자에 `font-variant-numeric: tabular-nums slashed-zero`를 적용한다.
- 양수 변화량은 `+3.2%`, 음수는 하이픈이 아닌 유니코드 minus를 써 `−1.8%`로 적는다.
- 한국 원화는 `1,250,000원`, 달러는 `$1.25M`, 퍼센트는 `12.4%`처럼 단위 규칙을 통일한다.
- 값이 없으면 `—`, 아직 발표 전이면 `발표 전`, 수집 실패면 `불러오지 못했어요`를 쓴다.
- `0`은 실제 0일 때만 쓴다.
- 소수 자릿수는 비교 대상끼리 같게 맞춘다.
- 큰 숫자는 우측 정렬하고 단위는 숫자보다 한 단계 낮은 색과 크기로 둔다.

**비교·정밀도 계약**

- 원값의 단위와 표시 단위를 구분한다. 비율 `0.032`의 표시가 `3.2%`라면 변환은 한 번만 한다. `M`은 백만, `B`는 십억이며 요약의 축약값은 상세에서 원값을 확인할 수 있어야 한다.
- `%`는 상대 변화율, `%p`는 두 퍼센트 값의 차이다. 예: `4.0% → 4.2%`는 `+0.2%p`, 상대 변화는 `+5.0%`다. `1bp = 0.01%p`이며 금리 비교는 bp 또는 %p 중 하나로 통일한다.
- 비교 기준이 0이면 상대 변화율을 만들지 않는다. 기준이 음수인 증감률은 도메인 계산 계약을 따르고, 계약이 없으면 원값·절대 변화량 또는 `적자 축소`처럼 사실만 표시한다.
 - 반올림으로 0이 된 0이 아닌 값은 `0`으로 단정하지 않는다. `+0.0%` 대신 정밀도를 늘리거나 `0 < 증가율 < 0.1%`처럼 표시 단위에 맞는 범위를 쓴다. 실제 0은 부호 없이 `0.0%`로 표시한다.
- 색 판정은 포맷된 문자열이 아닌 원값·도메인 판정으로 결정한다. 여러 카드·표에서 같은 지표의 단위·반올림 방식·비교 기준을 공유한다. 주문 수량·한도는 임의 축약하지 않고 원장의 정밀도를 따른다.
- 통화가 섞이면 `USD`, `KRW`를 명시한다. 시각은 날짜와 시간대(예: `2026-09-05 10:42 KST`)를 함께 제공한다. ET는 미국 동부의 해당 날짜 서머타임을 반영하며 고정 UTC 오프셋으로 계산하지 않는다.
- 관측·거래 기준 시각, 공시·발표 시각, 수집 시각을 구분한다. 새로 수집했다는 이유로 오래된 관측값을 최신값처럼 표시하지 않는다.

---

## 7. 간격과 레이아웃

### 7.1 4px 간격 사다리

| Token | 값 | 대표 용도 |
|---|---:|---|
| `space.1` | 4px | 아이콘 내부, 아주 가까운 요소 |
| `space.2` | 8px | 라벨과 값, 아이콘과 텍스트 |
| `space.3` | 12px | 조밀한 행 내부 |
| `space.4` | 16px | 기본 요소 간격 |
| `space.5` | 20px | 카드 내부 소그룹 |
| `space.6` | 24px | 카드 padding, 화면 좌우 padding |
| `space.8` | 32px | 카드 그룹·모달 padding |
| `space.10` | 40px | 큰 블록 내부 |
| `space.12` | 48px | 섹션 간격 |
| `space.16` | 64px | 데스크톱 대섹션 |
| `space.20` | 80px | hero·리포트 섹션 최대값 |

### 7.2 정보 밀도

| 모드 | 쓰는 곳 | 규칙 |
|---|---|---|
| Comfortable | 요약, 모바일, 승인 화면 | 카드 padding 24px, 행 기본 56px, 내용이 길면 확장 |
| Compact | 표, 원자료, 운영 로그 | 카드 padding 16px, 행 기본 48px; 읽기 전용 한 줄 행은 40px 허용, body.3는 보조 정보에만 사용 |
| Poster | Discord PNG | 기준 폭 1080 CSS px, 32~48px 외곽, 실제 표시 크기로 검수(§7.5) |

밀도는 화면 전체가 아니라 영역 단위로 바꾼다. Compact 표 옆의 핵심 요약까지 작게 줄이지 않는다.

### 7.3 그리드

- 모바일 기본 외곽 padding은 20px, 데스크톱은 24~32px다.
- 콘텐츠 최대 폭은 일반 대시보드 1440px, 긴 산문 720px, 분석 본문 1200px다.
- 데스크톱은 12-column grid를 쓸 수 있지만 카드 최소 폭 280px을 지킨다.
- 요약 카드는 4열을 넘기지 않는다. 다섯 번째부터는 다음 행이나 그룹으로 나눈다.
- 같은 그룹의 카드는 가능한 한 높이와 내부 기준선을 맞추되, 긴 내용이나 확대 때문에 필요한 높이를 자르지 않는다.
- 상세 패널이 열려도 목록의 선택 위치를 잃지 않게 한다.

### 7.4 반응형

| 구간 | 폭 | 동작 |
|---|---:|---|
| Mobile | `< 640px` | 단일 컬럼, 표는 핵심 열만 남기고 행 상세로 이동, dialog보다 bottom sheet 우선 |
| Tablet | `640–1023px` | 1~2열, 보조 패널은 아래로 이동 |
| Desktop | `1024–1439px` | 2~4열, 목록+상세 병렬 가능 |
| Wide | `≥ 1440px` | 콘텐츠 폭을 고정하고 바깥 여백만 늘림 |

모바일에서 단순히 데스크톱을 축소하지 않는다. 중요도가 낮은 열을 숨기고, 라벨과 값을 두 줄로 쌓으며, 차트 범례는 하단으로 이동한다.

열을 숨기면 동일 정보를 행 상세 또는 접근 가능한 별도 표에서 제공한다. 의미상 2차원 배치가 필요한 표·차트는 해당 영역에만 가로 스크롤을 허용하며 페이지 전체는 가로로 밀리지 않게 한다.

### 7.5 PNG의 크기와 가독성

- 1080은 **레이아웃 폭**이며 PNG 출력 픽셀 수와 다르다. 예를 들어 1080 CSS px를 `device_scale_factor=2`로 캡처하면 출력 폭은 2160px다.
- 고해상도 캡처는 선명도를 높일 뿐 글자의 표시 크기를 키우지 않는다. `표시 글자 크기 = 레이아웃 글자 크기 × 표시 폭 / 레이아웃 폭`으로 확인한다.
- 기준 표시 폭 360px에서 핵심 요약을 읽을 수 있게 설계한다. 1080px 레이아웃의 45px 글자가 이때 15px로 보인다. 긴 표는 개요 카드와 상세 카드로 나누거나 상세 자료로 연결한다.
- 이미지 높이는 콘텐츠에 맞춘다. 긴 카드에는 논리적 구획별 페이지 분할을 적용하고 각 장에 제목·기준 시각·페이지 순서를 반복한다.
- 캡처 전 서체·이미지·차트 로딩 완료를 확인하고, 원본과 360px 축소본에서 잘림·누락을 검수한다. 글자가 작은 상세를 원본 확대만으로 읽게 하더라도 핵심 값·위험은 메시지 본문에 함께 제공한다.

---

## 8. 모양, 보더, 깊이

### 8.1 Radius

| Token | 값 | 용도 |
|---|---:|---|
| `radius.xs` | 4px | 작은 인라인 상태 |
| `radius.s` | 8px | 태그, 조밀한 셀 |
| `radius.m` | 12px | 입력, 작은 카드 |
| `radius.l` | 14px | 중간 크기 비행동 표면 |
| `radius.xl` | 16px | 기본 카드 |
| `radius.2xl` | 20px | dialog, sheet |
| `radius.3xl` | 24px | 큰 카드, 리포트 블록 |
| `radius.full` | 999px | CTA, chip, badge |

기본 카드는 16px, 중요한 리포트 카드와 모달은 20~24px다. CTA·chip·badge는 pill, 입력은 12px다. 일반 태그는 분류 배지가 아닌 보조 메타데이터 컨테이너일 때만 8px를 쓴다. Native 플랫폼 형태는 §2.4를 따른다.

### 8.2 보더

- 기본 장식 보더는 `1px solid var(--color-border-default)`다. 다크 값은 §5.7을 따른다.
- 회색 캔버스 위 흰 카드는 `border.subtle`을 쓸 수 있다.
- focus는 2px ring과 2px offset을 확보한다.
- 색이 있는 left rail, 2px 장식 보더, 이중 외곽선은 쓰지 않는다.
- 표의 모든 셀을 박스로 가두지 않고 행 구분선만 쓴다.

`border.default`·`border.strong`은 장식 구분선이며 이름이 strong이라고 접근성 통과를 뜻하지 않는다. 입력 경계·선택 표시처럼 식별에 필요한 선은 `border.control` 또는 해당 상태 토큰으로 인접 색 대비 `3:1`을 확보한다. Focus ring은 장식 보더 금지의 대상이 아니다.

### 8.3 그림자

```css
--shadow-1: 0 1px 2px rgba(15, 23, 42, .05);
--shadow-2: 0 4px 12px rgba(15, 23, 42, .08);
--shadow-3: 0 12px 32px rgba(15, 23, 42, .14);
```

- `shadow-1`: menu, 선택된 segmented item
- `shadow-2`: tooltip, hover 가능한 독립 카드
- `shadow-3`: dialog
- 일반 카드는 평면이 기본이다.
- 다크 모드는 그림자보다 표면 명도 차를 우선한다.
- inner shadow는 쓰지 않는다.

---

## 9. 핵심 컴포넌트

### 9.1 버튼

| Variant | 표면 | 텍스트 | 용도 |
|---|---|---|---|
| Primary | `action.primary.bg` | `action.primary.fg` | 화면의 핵심 행동, 최대 하나 |
| Secondary | `bg.surface.subtle` | `text.primary` | 보조 행동 |
| Ghost | transparent | `text.brand` | 낮은 위계 행동 |
| Danger | `action.danger.bg` | `action.danger.fg` | 취소 불가능하거나 파괴적인 행동 |

- XL 높이 56px / radius.full / label 17px 700
- L 높이 48px / radius.full / label 17px 700
- M 높이 40px / radius.full / label 15px 600
- 최소 hit area는 44×44px다. 작은 시각 버튼도 투명 padding으로 hit area를 확보한다.
- 채움 버튼의 기본·hover·pressed는 §5.9의 배경/라벨 쌍을 쓴다. Secondary·Ghost의 pressed는 중성 표면 변화로 표현하고 대비를 검수한다.
- disabled는 `action.disabled.bg`/`action.disabled.fg`를 사용하며 **전체 opacity를 낮추지 않는다**. 비활성 속성과 동작 불가 이유를 함께 제공한다.
- 버튼 문구는 “확인”보다 결과를 말한다: `제안 검토하기`, `주문 승인하기`, `다시 불러오기`.
- 하단 고정 CTA는 위치 변형이며 별도 행동이 아니다. 활성 문맥에 채움 Primary를 중복 노출하지 않는다. 파괴적 결정에서는 Danger가 주 행동 자리를 차지하며 Primary를 나란히 두지 않는다.

### 9.2 카드

**Summary card**

- 제목 → 핵심 값 → 변화/상태 → 기준 시각 순서다.
- 핵심 값은 가장 크고, 방향은 값 옆에 붙인다.
- 설명이 없으면 색으로 판단을 암시하지 않는다.
- 카드 전체 클릭이 가능하면 hover·focus를 제공하고, 선택을 유지하는 카드에만 selected를 제공한다. 탐색은 링크, 실행은 버튼 의미를 쓰며 내부 링크·버튼과 클릭 영역을 중첩하지 않는다.

**Detail card**

- 16~24px radius, 기본 24~32px padding을 쓴다. Compact 영역은 §7.2의 16px padding을 따른다.
- 제목 아래에 한 줄 요약을 먼저 두고 차트나 표를 배치한다.
- 여러 카드가 한 결론을 이루면 불필요한 개별 그림자를 제거한다.

**Risk card**

- 경고색 배경으로 전체를 칠하지 않는다.
- 아이콘, 제목, 짧은 상태 라벨에만 warning/danger를 쓰고 본문은 중성색으로 둔다.
- 무엇이 차단되었는지, 왜 차단되었는지, 다음에 무엇을 확인할지 적는다.

### 9.3 Metric

```text
평가 손익 · 취득원가 대비
$1,240.52   +3.8%
2026-09-04 종가 기준 · 16:00 ET
```

- 라벨은 `text.secondary`, 값은 `text.primary`, 메타데이터는 `text.tertiary`다.
- delta만 방향색을 쓴다. 본 값은 특별한 이유가 없으면 중립색이다.
- 상승/하락이 “좋음/나쁨”인지 별도 판정이 있으면 짧은 설명을 추가한다.
- `st.metric`의 delta 색도 동일한 방향 규칙을 따라야 한다.

### 9.4 Data row와 Table

- 행 전체가 하나의 탐색 대상이면 전체 행을 hit area로 만든다.
- 텍스트는 좌측, 비교 가능한 숫자는 우측 정렬한다.
- ticker, 가격, 수량, 퍼센트 열은 mono와 tabular 숫자를 쓴다.
- 행 높이는 §7.2를 따른다. 클릭 가능한 행은 최소 44px hit area를 지키며 작은 행끼리 투명 hit area가 겹치면 높이를 늘린다.
- hover는 `bg.surface.subtle`, selected는 `bg.brand.weak` + 명시적 check/indicator다. Focus ring은 키보드 위치이며 selected의 대체가 아니다.
- 상승/하락 셀은 텍스트만 색칠하고 배경은 투명하게 둔다.
- 모바일에서는 핵심 식별자와 값만 첫 줄에 남기고 나머지는 두 번째 줄이나 상세 화면으로 보낸다.

### 9.5 Chip, Badge, Status

- **Chip:** 사용자가 선택하거나 필터링한다. 시각 높이 34~40px, pill; 겹치지 않는 44×44px hit area를 확보한다.
- **Badge:** 읽기 전용의 짧은 분류다. 시각 높이 22~26px, pill; 클릭 동작이 있으면 Chip/버튼 규칙을 적용한다.
- **Status:** 시스템 상태다. 점/아이콘 + 텍스트 조합을 기본으로 한다.
- 시스템 상태 배지에만 해당 `status.*` 색의 최대 12% tint를 허용한다. 실제 배경에 합성한 뒤 텍스트 대비를 검증하고 실패하면 중성 표면을 쓴다. 방향 변화 배지는 투명/중성 배경이다.
- `확정`, `예정`, `추정`, `오래됨`, `차단됨`을 색만 다르게 한 동일 문구로 처리하지 않는다.

### 9.6 입력과 선택

- 입력 높이는 48px, radius 12px다.
- resting은 `bg.surface.subtle` + `border.control`, focus는 `bg.surface` + `focus.ring`이다.
- error는 danger border와 구체적인 helper text를 함께 쓴다.
- segmented control은 상호 배타적 단일 선택, chip은 다중 필터에 쓴다.
- select menu는 가능한 trigger 가까이에 연다. 모바일에서 선택지가 길거나 복잡할 때만 sheet로 보낸다.
- placeholder를 label 대체로 쓰지 않는다.

### 9.7 Navigation

- 페이지 제목은 현재 위치를, 탭은 같은 위치 안의 관점을 말한다.
- active navigation은 굵기, 아이콘 fill, indicator 중 두 가지 이하로 표현한다.
- active 항목마다 파란 pill 배경을 반복하지 않는다.
- 뒤로가기는 사용자가 보고 있던 목록 위치와 필터를 보존한다.

### 9.8 Toast, Dialog, Bottom sheet

- Toast는 짧은 결과 안내에 쓴다. 기본 4~6초 후 닫되 중요한 결과·실패·되돌리기 행동은 화면이나 기록에 남긴다. 시간 안에 Toast를 눌러야만 복구할 수 있게 만들지 않는다.
- Dialog는 확인이 필요한 고위험 결정에 쓴다. 제목에서 결과를 말한다.
- 모바일에서는 정보·선택 중심 상호작용에 bottom sheet를 우선한다.
- scrim은 라이트 56%, 다크 72% 검정을 쓴다.
- 파괴적 행동은 위험 버튼을 오른쪽/아래에 두되 기본 focus를 주지 않는다.
- Dialog·모달 sheet는 접근 가능한 제목, focus 이동·내부 순환·닫은 뒤 호출 지점 복귀를 제공한다. Escape/닫기로 UI를 닫는 것과 제출된 주문을 취소하는 것을 구분한다.

### 9.9 Empty, Loading, Error

**Empty**는 정상적으로 데이터가 없는 상태다.

> 조회된 보유 종목이 없어요. 보유 내역은 연결된 계좌의 다음 동기화 후 갱신돼요.

**Loading**은 `불러오는 중이에요` 라벨과 3-dot 또는 progress를 쓴다. 진행률을 모르면 임의의 퍼센트를 만들지 않는다. 기존 데이터가 있으면 기준 시각·갱신 중 표시와 함께 유지한다. skeleton shimmer는 사용하지 않는다.

**Error**는 Navigating Error 형식을 따른다.

```text
무슨 일이 생겼는지
왜 그럴 수 있는지 또는 마지막으로 확인된 시각
지금 할 수 있는 행동
```

> 계좌 정보를 갱신하지 못했어요. 마지막 확인은 2026-09-05 10:42 KST였어요. 다시 불러와 주세요.

**Partial / Stale**은 Empty나 전체 실패와 다르다. 성공한 범위·누락된 범위·마지막 유효 시각을 함께 표시한다. 오래됨은 데이터별 갱신 주기·거래일·발표 일정에 따른 도메인 판정이며 모든 지표에 같은 일수 기준을 만들지 않는다. 원인을 모르면 네트워크·권한 문제라고 단정하지 않는다.

### 9.10 승인·주문·위험 행동

이 절은 이미 승인 기능이 허용된 운영 채널의 **표현 계약**이다. 읽기 전용 대시보드에서는 상태와 근거만 표시한다. 권한·한도·실행 여부는 [실행 안전 계약](docs/EXECUTION_AND_SAFETY.md)이 결정하며, 화면의 문구나 버튼 상태가 이를 대체하지 않는다.

- 제안, 승인, 주문 제출, 체결을 하나의 “완료” 상태로 합치지 않는다.
- 승인 버튼에는 ticker, 방향, 수량 또는 금액, 유효시간을 근처에 둔다.
- `매수 승인하기`와 `매도 승인하기`를 구체적으로 구분한다.
- 매수/매도 버튼에 상승/하락 색을 자동 매핑하지 않는다. 기본 행동색은 Brand Blue다.
- 손실 한도, 집중도, kill switch는 방향색이 아니라 warning/danger 상태로 표현한다.
- 실제 주문 직전에는 결과 요약과 취소 가능 여부를 다시 보여준다.
- `execution_mode`의 paper/live를 명시하고 모델의 `stage`와 혼동하지 않는다. 화면 값은 원장에 기록된 값만 쓰며 승인 범위·만료 시각을 임의로 계산해 넓히지 않는다.
- `승인 대기`, `승인됨`, `제출됨`, `부분 체결`, `체결 완료`, `거절됨`, `만료됨`, `취소 요청 중`, `취소됨`, `결과 확인 중`을 실제 원장 상태에 맞춰 구분한다. 취소 요청을 취소 완료로 표시하지 않는다.
- 제출 후 응답이 불명확하면 실패나 미주문으로 단정하지 않고 `결과 확인 중`과 마지막 확인 시각을 표시한다. 새 주문 버튼으로 재시도를 유도하지 않는다.

---

## 10. 데이터 시각화

### 10.1 기본 원칙

- 차트는 결론을 장식하는 그림이 아니라 비교를 가능하게 하는 도구다.
- 제목은 무엇을 비교하는지 말하고, subtitle은 기간·단위·기준을 말한다.
- grid는 필요한 축에만 쓰고 §10.4의 장식용 토큰을 쓴다. 기준선·데이터 선과 위계를 구분한다.
- 선 끝 라벨이 겹치지 않으면 legend보다 우선한다. 복잡하면 범례·직접 라벨을 조합하고 hover는 보조 수단으로만 쓴다. PNG에는 필요한 값을 직접 적는다.
- tooltip에는 기준 시각, 원값, 변화량, 단위를 같은 순서로 표시한다.
- 누락 구간을 0으로 이어 그리지 않는다.
- 막대 길이로 비교하는 축은 0에서 시작한다. 선 차트 축을 제한하면 범위를 명확히 표시하고 비교 패널끼리 동일 축을 우선한다. 이중 축은 단위·축 대응을 표시할 수 있을 때만 쓴다.
- 실제·예상·이전 값은 동일 단위·기간·산출 기준인지 확인한다. 기준이 다르면 직접 차이를 계산하지 않고 차이를 설명한다.

### 10.2 차트 색 배정

1. 핵심 시리즈: `chart.series.primary`, 굵기와 직접 라벨로 강조
2. 비교 시리즈·벤치마크: `chart.series.secondary`, 마커 모양·라벨로 구분
3. 상승/하락: 선·막대는 중성색을 유지하고 변화량 **텍스트**에만 `data.direction.*` 적용
4. 경고 임계선: `status.warning` + 임계값·조건 라벨
5. 다중 시리즈: 중성 명도와 마커·직접 라벨을 조합; 식별이 어려우면 작은 개별 차트로 분리

브랜드 채움은 행동에 남겨두며 초록·빨강은 범주색이나 투자 해석용 시리즈로 쓰지 않는다. 핵심 선·마커는 인접 표면 대비 `3:1` 이상을 유지한다. 투명도로 핵심 시리즈를 흐리게 하지 않는다. 실측/추정의 실선/점선 의미는 범주 구분 때문에 바꾸지 않는다.

### 10.3 차트별 규칙

**Line chart**

- 기본 선 2px, 핵심 선 2.5~3px다.
- 실측과 추정은 실선/점선으로 구분한다.
- 범위 band는 중성색 8~14% alpha를 기본으로 하며 범위의 의미를 적는다. 경계 자체를 읽어야 하면 대비를 충족하는 경계선·수치 라벨도 제공한다.

**Bar chart**

- 기본 막대는 `chart.series.secondary`, 선택된 막대는 `chart.series.primary`와 선택 라벨로 구분한다.
- 양·음수는 0 기준선의 양쪽 위치와 부호로 표현한다. 방향색은 수치 라벨에만 쓴다.
- 모든 막대를 서로 다른 색으로 만들지 않는다.

**Area chart**

- fill은 중성 선 색의 8~16% alpha를 기본으로 한다. 면적 채움은 보조이며 윤곽선이 데이터를 전달한다.
- 방향색으로 면적을 채우지 않는다.

**Donut**

- `기타`를 포함해 표시 범주가 6개 이하일 때만 쓴다. 나머지는 `기타`로 묶거나 bar로 바꾼다.
- 비중 차이는 색뿐 아니라 순서와 직접 라벨로 표현한다.
- 음수 비중·합계 0에는 쓰지 않는다. 전체 분모·기타의 범위를 명시하고 반올림 때문에 합계가 100%와 다르면 주석으로 설명한다. 중성 조각 구분이 어려우면 막대 차트를 쓴다.

**Gauge**

- 객관적인 임계값이 있을 때만 쓴다.
- 업종마다 기준이 달라지는 지표는 중립값으로 두고 임계 판정을 꾸며내지 않는다.
- 임계값·현재값·단위·출처를 함께 적는다. 단계별 빨강/초록 구간 채움 대신 중성 눈금과 텍스트 상태를 쓴다.

### 10.4 테마별 Plotly 기준

| 렌더 역할 | Semantic token 또는 값 |
|---|---|
| paper / plot bg | transparent; 실제 부모는 §5.5의 허용 배경 |
| grid | `chart.grid`: Light `#E5E8EB`, Dark `#2B3441` (장식용) |
| 핵심 데이터·0 기준선 | `chart.series.primary` → `text.primary` |
| 비교 데이터 | `chart.series.secondary` → `text.tertiary` |
| axis text | `text.tertiary` |
| title | `text.primary` |
| hover bg | `bg.surface.elevated` |
| hover border | `border.default` |

이 표는 Plotly뿐 아니라 PNG 내부 차트에도 같은 의미로 적용한다. 표면 위 tint·band와 겹치는 텍스트·선의 대비는 별도로 검증한다. 장식 grid에는 `3:1`을 강제하지 않지만 정보를 전달하는 선에는 §13을 적용한다.

---

## 11. 라이트·다크 모드 운영

### 11.1 테마 선택

- 대시보드는 OS 설정을 기본값으로 따르고 사용자의 명시적 선택을 저장한다.
- 사용자 선호는 `light`, `dark`, `system` 세 상태로 구분하고, 실제 렌더러에는 해석된 `light` 또는 `dark`만 전달한다. 플랫폼이 테마 선택을 소유하면 그 설정을 사용하고 중복 선택기를 만들지 않는다.
- 테마 전환은 데이터 상태나 선택 상태를 초기화하지 않는다.
- Discord PNG는 발송 채널과 사용 환경에 맞춘 명시적 테마를 렌더링한다. 캡처 시 OS 자동 전환에 의존하지 않는다.
- 라이트 페이지 안의 다크 hero는 제한된 하위 테마 표면이다. 배경만 검게 바꾸지 않고 그 내부의 text·border·chart map도 함께 전환한다. Native embed의 테마는 수신자 플랫폼 설정을 따른다.

### 11.2 동일하게 유지할 것

- 정보 구조, 간격, 크기, radius
- 방향·상태의 의미
- primary action의 개수
- 차트 시리즈의 순서와 선 스타일
- 카피와 숫자 정밀도

### 11.3 테마마다 바꿀 것

- canvas와 surface의 명도 관계
- text·border·icon의 대비
- 방향색의 접근성 보정 alias
- shadow의 강도와 표면 분리 방식
- brand weak, status tint의 alpha

다크 모드에서 흰색 텍스트를 모두 같은 강도로 쓰지 않는다. primary, secondary, tertiary 계층을 유지해야 긴 분석 화면이 평평해지지 않는다.

---

## 12. 모션

```css
--motion-fast: 120ms;
--motion-base: 200ms;
--motion-slow: 320ms;
--ease-standard: cubic-bezier(.22, .61, .36, 1);
--ease-out: cubic-bezier(.16, 1, .3, 1);
```

- press·focus 120ms, toggle·hover 200ms, dialog·sheet 320ms다.
- 바운스 오버슈트, parallax, 320ms 초과 장식 fade를 쓰지 않는다.
- 숫자가 갱신될 때 레이아웃이 흔들리지 않게 tabular 숫자와 고정 폭을 쓴다.
- `prefers-reduced-motion: reduce`에서는 이동·확대·반복 점멸·장식 transition을 제거하고 즉시 상태를 바꾼다. Loading은 정적인 라벨/progress로 남긴다.
- 실시간 데이터 갱신을 깜박임으로 알리지 않는다. 기준 시각과 작은 상태 변화로 알린다.

---

## 13. 접근성

- 일반 텍스트는 최소 `4.5:1`, 큰 텍스트는 최소 `3:1` 대비를 확보한다. 큰 텍스트는 24 CSS px 이상 또는 굵은 글씨 18.67 CSS px 이상이며, 17px/700 버튼 라벨은 일반 텍스트다. PNG도 실제 표시 크기로 판정한다. 계산값은 반올림해서 합격시키지 않는다. [W3C 텍스트 대비 기준](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
- 컨트롤·상태 식별에 필요한 경계, focus, 차트 선·마커는 인접 색과 `3:1` 이상이다. 장식 구분선·grid·보조 tint에는 일괄 적용하지 않는다. [W3C 비텍스트 대비 기준](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)
- body 기본 크기는 15px 이상, 긴 설명은 17px를 권장한다. §6.2의 작은 보조 텍스트는 대비와 확대를 만족해야 하며 핵심 위험 문구를 작게 만드는 예외가 아니다.
- 직접 제어하는 버튼·칩·행 등 독립 컨트롤은 최소 44×44 CSS px hit area를 갖는다. 이는 제품 기준이며 WCAG AA 전체 충족 선언이 아니다. 문장 속 inline link와 플랫폼 소유 컨트롤은 해당 매체 제약을 따른다. [W3C Target Size (Enhanced)](https://www.w3.org/WAI/WCAG22/Understanding/target-size-enhanced.html)
- keyboard focus를 hover와 구분해 항상 보이게 한다.
- 색, 위치, 아이콘 중 하나만으로 상태를 전달하지 않는다.
- 차트에는 요약 문장이나 접근 가능한 표를 함께 제공한다.
- icon-only button은 접근 가능한 이름과 tooltip을 갖는다.
- 자동 갱신 영역은 사용자의 읽기를 방해하지 않도록 불필요한 live announcement를 하지 않는다.
- 텍스트 확대 200%와 viewport 폭 320 CSS px의 reflow를 각각 검수한다. 핵심 행동·값이 잘리지 않아야 하며 2차원 표·차트의 영역 스크롤 예외는 §7.4를 따른다. PNG는 §7.5의 축소 검수와 텍스트 대체를 적용한다. [W3C Reflow 기준](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html)
- disabled는 WCAG 텍스트 대비 의무의 예외지만, 이 제품은 직접 제어하는 비활성 라벨·이유에도 `4.5:1`을 적용한다. §5.9의 중성 토큰을 쓰고 opacity 0.30을 일괄 적용하지 않는다. 비활성은 속성·상태 문구로도 전달한다.
- pointer hover로 나타나는 정보는 keyboard focus로도 확인할 수 있어야 하며 닫을 수 있어야 한다. 중요한 값·위험·실패 이유를 tooltip에만 숨기지 않는다.

---

## 14. 보이스 앤 톤

### 14.1 기본 문체

- 안내·설명·오류 문장은 해요체로 쓴다. 제목·필드명·짧은 상태는 명사형, 버튼은 `다시 불러오기`처럼 행동형을 허용한다.
- 짧고 구체적인 일상어를 쓴다.
- 시스템이 할 일을 사용자에게 명령하지 않는다.
- 한 문장은 한 가지 사실만 전달한다.
- “혁신적”, “최고의”, “압도적” 같은 과장어를 쓰지 않는다.
- 느낌표·장식적 ALL CAPS·불필요한 이모지를 쓰지 않는다. `AAPL`, `USD`, `EPS`, `CPI` 같은 공식 식별자·약어의 대문자는 유지한다.

### 14.2 문장 순서

```text
결론 → 근거 또는 기준 → 다음 행동
```

좋은 예:

> 이번 주문은 한도를 넘어요. 주문 금액을 $2,000 이하로 줄이면 다시 검토할 수 있어요.

> CPI가 예상보다 0.2%p 높게 나왔어요. 금리 민감 자산의 변동성을 함께 확인해 보세요.

피할 예:

> 오류가 발생했습니다.

> 위험! 시장이 급락했습니다!!!

> 여기를 눌러주세요.

### 14.3 데이터 확실성 문구

아래 문구는 실제 데이터 상태와 제공 기능이 일치할 때 사용하는 예시다. 안내를 자연스럽게 만들기 위해 원인·갱신 예정·가능한 행동을 지어내지 않는다.

| 상태 | 권장 문구 |
|---|---|
| 예정 | `8월 28일 발표 예정이에요` |
| 추정 | `과거 일정으로 추정한 날짜예요` |
| 오래됨 | `마지막 확인이 7일 전이에요` |
| 빈 값 | 원인 미확인이면 `값이 없어요`; 미보고가 확인된 경우에만 `이 기간에는 보고된 값이 없어요` |
| 미지원 | `이 지표는 아직 제공하지 않아요` |
| 부분 수집 | `10개 중 8개를 확인했어요. 2개는 갱신하지 못했어요` |
| 실패 | `데이터를 불러오지 못했어요` |
| 차단 | `안전 한도를 넘어 주문을 진행하지 않았어요` |

---

## 15. 아이콘과 일러스트

- 아이콘은 16/20/24/32px 그리드를 쓴다. 24px가 기본이다.
- stroke는 1.5~1.75px, rounded cap/join을 쓴다.
- 아이콘은 `currentColor`를 상속한다.
- filled icon은 active navigation이나 확정 상태처럼 제한된 곳에만 쓴다.
- 상승·하락 화살표는 텍스트 부호를 대체하지 않고 보조한다.
- emoji를 카피 문장부호처럼 쓰지 않는다.
- 일러스트는 빈 상태·완료 화면의 이해를 돕는 경우에만 쓰고 금융 위험을 귀엽게 만들지 않는다.

---

## 16. 구현 계약

### 16.1 CSS 변수 계약

§5.5·§5.6·§5.7·§5.9의 semantic key가 색 값의 기준이다. CSS 이름은 `--color-` 뒤에 key의 점을 하이픈으로 바꾼다. 예: `data.direction.up` → `--color-data-direction-up`. §10.4의 차트 alias도 같은 규칙을 쓴다. 아래는 이 표를 옮긴 참조 map이며 값을 바꾸면 표와 예제를 함께 검증한다.

`data-theme`에는 `light` 또는 `dark`만 넣는다. `system` 해석과 선호 저장은 호스트가 담당한다(§11.1). theme 속성이 없으면 이 참조 CSS는 light로 동작하므로, 자동 OS 테마 전환을 지원하는 완성 코드로 오해하지 않는다.

```css
:root,
[data-theme="light"] {
  color-scheme: light;
  --color-data-direction-up: #007A50;
  --color-data-direction-down: #CF202F;
  --color-data-direction-flat: #5E6B7A;
  --color-status-info: #1B64DA;
  --color-status-success: #00773A;
  --color-status-warning: #B54708;
  --color-status-danger: #D22030;
  --color-bg-canvas: #F9FAFB;
  --color-bg-surface: #FFFFFF;
  --color-bg-surface-subtle: #F2F4F6;
  --color-bg-surface-elevated: #FFFFFF;
  --color-bg-surface-strong: #E5E8EB;
  --color-bg-brand-weak: #E8F3FF;
  --color-text-primary: #191F28;
  --color-text-secondary: #4E5968;
  --color-text-tertiary: #5E6B7A;
  --color-text-disabled: #4E5968;
  --color-text-brand: #1B64DA;
  --color-text-inverse: #FFFFFF;
  --color-border-default: #E5E8EB;
  --color-border-subtle: rgba(0,0,0,.08);
  --color-border-strong: #B0B8C1;
  --color-border-control: #5E6B7A;
  --color-focus-ring: #1B64DA;
  --color-overlay-scrim: rgba(0,0,0,.56);
  --color-action-primary-bg: #1B64DA;
  --color-action-primary-hover: #1554B8;
  --color-action-primary-pressed: #10479F;
  --color-action-primary-fg: #FFFFFF;
  --color-action-danger-bg: #B91C2B;
  --color-action-danger-hover: #A31624;
  --color-action-danger-pressed: #8C1220;
  --color-action-danger-fg: #FFFFFF;
  --color-action-disabled-bg: #E5E8EB;
  --color-action-disabled-fg: #4E5968;
  --color-chart-grid: #E5E8EB;
  --color-chart-series-primary: var(--color-text-primary);
  --color-chart-series-secondary: var(--color-text-tertiary);
}

[data-theme="dark"] {
  color-scheme: dark;
  --color-data-direction-up: #05B169;
  --color-data-direction-down: #FF6673;
  --color-data-direction-flat: #8B95A1;
  --color-status-info: #64A8FF;
  --color-status-success: #4FD18B;
  --color-status-warning: #FFB454;
  --color-status-danger: #FF6673;
  --color-bg-canvas: #101318;
  --color-bg-surface: #171B22;
  --color-bg-surface-subtle: #202630;
  --color-bg-surface-elevated: #252D38;
  --color-bg-surface-strong: #2B3441;
  --color-bg-brand-weak: rgba(49,130,246,.16);
  --color-text-primary: #F2F4F6;
  --color-text-secondary: #B0B8C1;
  --color-text-tertiary: #8B95A1;
  --color-text-disabled: #B0B8C1;
  --color-text-brand: #64A8FF;
  --color-text-inverse: #191F28;
  --color-border-default: #333D4B;
  --color-border-subtle: rgba(255,255,255,.08);
  --color-border-strong: #4E5968;
  --color-border-control: #8B95A1;
  --color-focus-ring: #64A8FF;
  --color-overlay-scrim: rgba(0,0,0,.72);
  --color-action-primary-bg: #1B64DA;
  --color-action-primary-hover: #1554B8;
  --color-action-primary-pressed: #10479F;
  --color-action-primary-fg: #FFFFFF;
  --color-action-danger-bg: #B91C2B;
  --color-action-danger-hover: #A31624;
  --color-action-danger-pressed: #8C1220;
  --color-action-danger-fg: #FFFFFF;
  --color-action-disabled-bg: #2B3441;
  --color-action-disabled-fg: #B0B8C1;
  --color-chart-grid: #2B3441;
  --color-chart-series-primary: var(--color-text-primary);
  --color-chart-series-secondary: var(--color-text-tertiary);
}
```

### 16.2 코드 SSOT

- 문서는 의미와 기준의 SSOT다.
- Python/Jinja 구현에서는 공통 토큰 모듈 또는 패키지별 `palette.py`를 통해 값을 전달한다. 동일 semantic key의 기본 색을 패키지마다 재해석하지 않는다. 기존 상수명은 경계 adapter에서 canonical key로 명시적으로 매핑한다.
- 템플릿 안에 hex를 직접 넣지 않는다.
- 임계 판정은 도메인의 계산 계약 또는 `thresholds.py`, 표현 색은 `palette.py`가 맡는다. UI가 별도 임계값을 만들지 않는다. 판정 결과·기준·사유를 먼저 받아 토큰으로 매핑한다.
- 라이트·다크는 서로 다른 템플릿을 복제하지 않고 동일한 semantic key에 다른 theme map을 주입한다.
- Plotly, Streamlit, HTML 카드가 같은 semantic token 이름을 사용하도록 맞춘다.
- 네이티브 컴포넌트의 기본 delta 색·상태 배경이 계약과 다르면 지원하는 API로 조정하거나 중립 표시와 부호·문장으로 대체한다. 플랫폼이 지원하지 않는 서체·색을 준수한 것처럼 선언하지 않는다.
- 공유 범위·패키지 경계·렌더러 소유권은 CLAUDE.md를 따른다. 토큰 공유가 템플릿 복제나 알림 패키지 간 직접 import를 허용하지 않는다.

### 16.3 명명 규칙

좋음:

```text
text.primary                 # semantic key
data.direction.up            # semantic key
status.warning               # semantic key
button.primary.bg            # component alias → action.primary.bg
--color-data-direction-up    # CSS adapter 이름
```

나쁨:

```text
greenText
redCard
coinbaseGreen
darkGrey2
```

이름은 색이 아니라 역할을 말해야 한다.

### 16.4 구현 반영 시 확인할 항목

아래는 문서 검토 시 확인한 구현 차이이며 허용 예외가 아니다. **이 문서 개정만으로 코드 반영이 완료되지는 않는다.** 구현 작업에서는 해당 파일의 최신 상태를 다시 읽고 차이를 해소한 뒤 검수한다.

| 확인 대상 | 반영 시 확인할 계약 |
|---|---|
| `src/investment_agent/dashboard/theme.py` | 작은 글자용 보정색·상태색·중성 차트 토큰을 대조한다. 기존 `up=#00875A`, 라이트 `muted=#6B7684`, 다크 `status_danger=#F04452`, 파란 범주색은 이 계약과 차이가 있다. |
| `src/investment_agent/notifications/investment/palette.py` | 승인/거절 색을 `SEMANTIC_UP`/`SEMANTIC_DOWN`에서 만드는 매핑을 시스템 상태로 분리하고 native rail은 §2.4를 따른다. |
| `src/investment_agent/notifications/earnings_report/palette.py` | `direction(..., higher_better=...)`의 부호 반전과 투자 해석 색을 분리한다. 보합 임계값은 UI 팔레트가 아닌 도메인 계약인지 확인한다. |
| 각 PNG·embed·웹 adapter | 매체별 크기·서체·테마·상태 지원 범위를 명시하고 §18의 적용 항목을 검수한다. |

규칙을 바꿀 때에는 이 문서의 정의·토큰 표·CSS·컴포넌트·체크리스트를 함께 맞춘다. CLAUDE.md나 스킬의 요약과 충돌이 새로 생기면 구현을 임의로 예외 처리하지 말고 해당 문서의 우선순위에 따라 기준부터 정리한다.

---

## 17. 컴포넌트 상태 매트릭스

모든 인터랙티브 컴포넌트는 아래 상태 중 실제 동작에 해당하는 항목을 검토한다. 예를 들어 탐색 링크에는 selected가 없을 수 있고, PNG에는 이 매트릭스를 적용하지 않는다. 해당 없음은 사유를 남기며 가짜 동작 상태를 추가하지 않는다.

| 상태 | 필수 표현 |
|---|---|
| Rest | 기본 표면·텍스트·보더 |
| Hover | 미세한 surface 변화, 포인터 환경에서만 |
| Focus visible | 2px focus ring + offset |
| Pressed | §9.1의 토큰 또는 중성 표면 변화, 120ms; native 플랫폼은 기본 표현 |
| Selected | check/indicator + surface 변화 |
| Disabled | 중성 disabled 배경/라벨 + 비활성 속성 + 인접 이유; 전체 opacity 유지 |
| Loading | label 안정, 3-dot/progress, 중복 제출 방지 |
| Error | 구체적 메시지와 회복 행동 |

hover만 있고 keyboard focus가 없는 웹 컴포넌트는 완료된 것으로 보지 않는다. Focus와 selected/error는 동시에 존재할 수 있다. Focus ring을 오류 보더로 덮지 않으며 loading 중에도 초점·라벨을 유지하고 중복 실행을 막는다. 비활성 이유는 비활성 요소의 hover에만 두지 않는다.

---

## 18. 검수 체크리스트

검수 대상의 매체·테마·데이터 상태·표시 폭을 먼저 적는다. 항목은 `통과 / 실패 / 해당 없음(사유)`으로 기록한다. 문서 수정만 한 경우 문서 내부 검증과 구현 검증을 구분하며, 아래 UI 검수를 실행한 것으로 표시하지 않는다.

**최소 검수 조합:** 직접 제어하는 웹은 라이트·다크 × 정상·빈 값·부분 실패·전체 실패·오래됨, PNG는 지원 테마 × 정상·긴 내용·누락 데이터와 원본/360px 표시 폭, native embed는 본문·부호·상태 라벨·실제 링크를 확인한다. 상호작용이 있으면 키보드·focus·loading·disabled를 추가한다.

### 철학과 정보 구조

- [ ] 첫 화면만 보고 현재 상태와 핵심 위험을 알 수 있는가?
- [ ] 더 깊은 근거만 접혀 있고 기본 사실은 보이는가?
- [ ] 빈 값, 0, 오류, 미발표가 서로 구분되는가?
- [ ] 사용자가 다음에 할 수 있는 행동이 구체적인가?

### 색

- [ ] Brand Blue가 유일한 브랜드 강조색인가?
- [ ] 활성 작업 문맥의 채움 Primary는 최대 하나이며, 읽기 전용 화면에 불필요한 CTA를 만들지 않았는가?
- [ ] 상승·하락은 방향색과 부호를 함께 쓰는가?
- [ ] 방향색을 성공·실패·매수·매도에 오용하지 않았는가?
- [ ] 방향색은 텍스트에만 사용하고, 상태 tint·Danger 행동은 별도 토큰과 조건을 지키는가?
- [ ] 실제 배경·tint·hover·pressed를 포함해 텍스트 및 필요한 비텍스트 대비를 통과하는가?

### 타이포와 숫자

- [ ] 서체를 제어하는 매체에서 본문은 Pretendard 계열 또는 명시된 fallback으로 렌더되는가?
- [ ] 금융 숫자는 JetBrains Mono/fallback과 tabular 숫자를 쓰며, native embed는 읽기 가능한 대체를 제공하는가?
- [ ] 단위, 부호, 소수 자릿수가 비교 대상끼리 일관적인가?
- [ ] 실제 0이 아닌 빈 값을 `0`으로 만들지 않았는가?
- [ ] 반올림된 비영 값·0 기준 증감률·%와 %p·통화·시간대·관측/수집 시각을 구분하는가?

### 컴포넌트와 접근성

- [ ] 직접 제어하는 독립 컨트롤에 겹치지 않는 44×44px hit area와 keyboard focus가 있는가?
- [ ] 선택·상태를 색 하나로만 말하지 않는가?
- [ ] 웹은 320px reflow와 텍스트 확대 200%, PNG는 §7.5의 축소 가독성과 텍스트 대체를 만족하는가?
- [ ] 적용되는 loading, empty, partial/stale, error, disabled 상태를 구분했는가?
- [ ] reduce motion을 존중하는가?

### 카피

- [ ] 설명 문장은 해요체·일상어를 쓰며, 제목·상태·버튼은 §14.1의 허용 형태를 따르는가?
- [ ] 버튼이 일어날 일을 직접 말하는가?
- [ ] 에러가 원인 또는 맥락과 다음 행동을 함께 안내하는가?
- [ ] 과장, 느낌표, 모호한 “확인”에 의존하지 않는가?

### 사실성과 구현 계약

- [ ] 방향·투자 해석·작업 상태가 분리되고 임계값·사유가 원천 계약에서 오는가?
- [ ] paper/live와 승인·제출·부분 체결·취소 요청·결과 불명확 상태를 구분하는가?
- [ ] CSS 변수·차트 alias가 토큰 표와 일치하고 임의 hex·미정의 변수가 없는가?
- [ ] 구현 차이를 규칙의 예외나 완료 상태로 오인하지 않았는가?
- [ ] UI 변경 시 렌더 미리보기·대비 계산·해당 상태 검증을 기록했는가?

---

## 19. 절대 하지 않는 것

- 두 번째 브랜드 색을 추가한다.
- 초록은 매수, 빨강은 매도로 고정한다.
- 상승을 무조건 긍정, 하락을 무조건 부정으로 해석한다.
- 다크 모드에서 모든 표면을 같은 검정으로 만든다.
- 카드마다 그림자, 보더, 색 배경을 동시에 쓴다.
- 모든 정보를 첫 화면에 같은 크기로 나열한다.
- 원자료 표를 설명 없이 노출하고 사용자가 의미를 찾게 한다.
- skeleton shimmer, 과도한 glow, gradient chrome, parallax를 쓴다.
- 에러 문구를 `오류가 발생했습니다`로 끝낸다.
- 샘플 값, 가짜 가격, 임의의 0으로 실패 상태를 숨긴다.

---

## 20. 설계 근거

이 시스템의 각 결정은 임의로 고른 것이 아니라 아래 문제를 풀기 위한 것이다.

- **브랜드 강조색은 한 계열이다.** Brand Blue 계열을 주 행동에 집중하고 차트는 중성색으로 비교한다. 방향·시스템 상태는 각자의 의미가 있는 색이며 두 번째 브랜드 장식으로 쓰지 않는다(§5).
- **이 제품은 상승을 초록, 하락을 빨강으로 고정한다.** 지역별 금융 색 관습이 다르므로 보편적 의미라고 가정하지 않는다. 방향은 부호·문장과 함께 표시하고(§5.4), 성공·실패·경고와 투자 해석을 분리한다(§5.6).
- **차갑고 낮은 채도의 중성색 위에 평면 표면을 쓴다.** 투자 데이터는 이미 정보 밀도가 높다. 따뜻한 색조나 강한 그림자, 화려한 장식을 더하면 판단에 필요한 것과 아닌 것을 구분하기 더 어려워진다. 깊이는 그림자가 아니라 표면 단계(§8.3)로 표현한다.
- **서체를 제어할 수 있는 금융 숫자는 고정폭을 쓴다.** JetBrains Mono와 tabular 숫자(§6.3)로 자릿수 비교를 돕고, 제어할 수 없는 native embed에는 비교 가능한 텍스트 구조를 제공한다(§2.4).
- **해요체와 Navigating Error 원칙을 쓴다.** 사용자가 오류나 위험한 상황을 만났을 때 필요한 건 사과나 과장이 아니라 "무슨 일인지, 왜 그런지, 지금 뭘 할 수 있는지" 세 가지뿐이다(§9.9, §14).
- 다크 모드 중성색(§5.3)과 컴포넌트 기본값은 이 제품의 설계 결정이다. 대비·reflow·target size는 §13의 W3C 기준과 제품의 추가 기준을 구분하고, 승인·주문 표현(§9.10)은 실행 안전 계약을 따른다. 문서의 토큰 검증과 실제 UI의 접근성 검수는 각각 필요하다.

이 시스템의 최종 인상은 “거래 화면처럼 흥분시키는 앱”이 아니라 **복잡한 금융 상황을 빠르게 이해하고 안전하게 판단하게 돕는 차분한 도구**여야 한다.

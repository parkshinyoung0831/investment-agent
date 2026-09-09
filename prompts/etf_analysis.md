# ETF 분석 하네스 — 세팅 팩 (US v1)

> 사용법: `{TICKER}` 자리에 분석할 미국 상장 ETF 티커를 넣어 AI에게 전달하세요.
> 예) `VOO`, `QQQ`, `SOXX`

---

## 1. 공통 시스템 프롬프트 (그대로 복사)

Claude·ChatGPT 양쪽에 공통으로 넣는 본문입니다.

```
당신은 ETF를 정량·정성 양면에서 분석하는 전문 애널리스트입니다.
아래 "미국 상장 ETF" 티커 1개를, 코드 실행으로 확보한 실측 데이터에 근거해 한국어 심층 보고서로 분석하세요.

분석 대상 티커: {TICKER}   (미국 상장 ETF 1개)

────────────────────────
[ 시점 기준 ]
────────────────────────
- 먼저 오늘 날짜(분석 실행일)를 확인해 보고서 상단에 "분석 실행일: YYYY-MM-DD"로 명시한다.
- "현재·최근·올해·현 정부" 등 모든 표현은 학습 시점이 아니라 분석 실행일 기준이다.
- 학습 컷오프 이후의 사실(정책·세법·시세)은 반드시 검색/연결 도구로 확인하고, 못 하면 "확인 불가"로 둔다.

────────────────────────
[ 데이터 소스 원칙 ]
────────────────────────
- 우선순위: ① 코드 실행 결과(아래 '데이터 수집 모드'의 yfinance 스크립트 출력) → ② 운용사 공식 공시·펀드 페이지(보유종목·보수·분배·가중지표) → ③ 거래소·금융정보 사이트 → ④ 웹 검색.
- 시세·수익률·기술적 지표·가중 밸류에이션 등 정량 수치는 추측·스크래핑하지 말고 코드 실행 결과로 확보한다.
- 보유 종목과 비중은 코드 결과(또는 운용사 공식 데이터)를 최우선으로 하고, 보유 종목 기준일(as-of)을 표기한다.
- 모든 핵심 수치 옆에 데이터 기준일(YYYY-MM-DD)과 신뢰도 태그를 단다.
  · [실측·코드]=코드 실행 결과 / [공식]=운용사·거래소 공식 / [2차]=금융정보 사이트 / [추정]=직접 계산·추정치
- 신뢰 우선순위: [실측·코드] > 공식 웹 > 2차 웹 > [추정].
- ETF 집계 PER/PBR의 과거 시계열은 무료 소스가 없다. 따라서 역사적 밸류에이션 비교는 ① '배당수익률 밴드'(접근 B, [추정])를 기본 프록시로 쓰고, ② 주식형 ETF면 edgartools(SEC EDGAR 래퍼)로 상위 보유종목의 분기 순이익·자기자본·주식수를 받아 종목별 PER(=가격/TTM-EPS)·PBR(=가격/BVPS)을 계산하고 '현재 비중 고정'으로 재구성한 PER/PBR 밴드(접근 C, [추정])를 함께 제시한다. 두 접근의 가정·한계(비중 고정·커버리지·해외(SEC 미제출) 종목 제외·SEC XBRL ~2009년부터 등)를 §3에 명시한다.

────────────────────────
[ 데이터 수집 모드: 코드 실행 — 단계별 진행 ]
────────────────────────
정확한 숫자는 추측·스크래핑 대신 "코드 실행 → 결과 붙여넣기"로 확보한다. 아래 단계로 나눠 진행하며, 각 단계 끝에서 반드시 멈춘다(분석대상 수집 → §0~2 작성·동종 ETF 추천 → 비교 스크립트 출력 → §3부터 최종 분석).

● 1단계 — 분석 대상 데이터 요청 (이 턴에서는 보고서를 쓰지 않는다):
- 티커와 자산군만 먼저 확인한다.
- 분석 대상의 숫자를 한 번에 가져오는 표준 수집 스크립트(§2-1) 1개만 출력한다(무료 yfinance 사용, API 키 불필요).
- 스크립트는 결과를 "한글 요약(텍스트)" 한 덩어리로 print 하고, 각 값에 기준일(as_of)이 포함되게 한다.
- 출력 끝에 "이 코드를 실행하고 출력(요약 텍스트) 전체를 그대로 붙여넣어 주세요"라고 안내하고 멈춘다.
- 이 단계에서 숫자를 지어내 미리 채우지 않는다.

● 2단계 — §0~2 작성 + 동종 ETF 추천 (여기서 멈춘다):
- 붙여넣은 요약을 사실 근거로 §0(TL;DR)·§1(기본 개요)·§2(구성 종목 분석)까지만 작성한다(요약 값엔 [실측·코드] 태그 + 기준일 as_of).
- 이어서 §3 비교에 쓸 동종/벤치마크 ETF 후보 3~5개(분석 대상 포함)를 ETF 성격에 맞게 "추천"하고, 각 선정 이유를 한 줄씩 단다.
- 추천만 하고 비교 스크립트는 아직 출력하지 않는다. "비교할 ETF 티커를 확정해 보내주세요(추천 후보를 그대로 써도 됩니다)"라고 안내한 뒤 멈춘다.

● 3단계 — 비교 스크립트 출력 (사용자가 티커를 보낸 뒤, 여기서 다시 멈춘다):
- 사용자가 보낸 티커(분석 대상 + 동종/벤치마크)를 동종/벤치마크 비교 스크립트(§2-2)의 PEERS 리스트에 채워 그 스크립트 1개만 출력한다.
- "이 코드를 실행하고 출력(요약)을 그대로 붙여넣어 주세요"라고 안내하고 멈춘다.
- 동종 ETF의 TER·AUM·수익률·PER 등 비교 수치는 절대 지어내지 않는다.

● 4단계 — §3부터 최종 보고서 (사용자가 비교 요약을 붙여넣은 뒤):
- 붙여넣은 비교 실측값으로 §3(ETF 종합 밸류에이션·비중 가중)부터 자세히 분석을 이어간다. §3 동종 ETF 비교표를 완성한 뒤 §4~11을 순서대로 마저 작성한다.
- 요약에서 온 값에는 [실측·코드] 태그 + 기준일(as_of)을 단다.
- 요약에 없거나 '—'로 표시된 값은 "확인 불가"로 두거나, 정성 정보(정책·세금 등)는 웹으로 보완하고 [2차]로 구분한다.
- 붙여넣은 데이터가 비었거나 깨졌으면 추측하지 말고, 어떤 항목이 비었는지 알리고 재실행(또는 운용사 페이지 보완)을 요청한다.

────────────────────────
[ 반드시 지킬 실행 원칙 ]
────────────────────────
1. 추측 금지. 못 찾으면 "확인 불가"라고 명시한다. 숫자를 지어내지 않으며, 정량 수치는 코드 실행 결과를 근거로 한다.
2. 사실(검증 가능)과 전망(의견)을 항상 구분 표기한다. 전망에는 근거와 출처를 단다.
3. 객관적·균형적으로 쓴다. 강세 논리와 약세 논리를 둘 다 제시하고 홍보성 표현을 쓰지 않는다.
4. 모든 정성 분석(정책·지정학)에는 출처(매체명·날짜)를 단다.
5. 한국 거주 투자자 관점(세금·환율)을 포함한다. 이 ETF는 미국 상장이므로 "해외상장 ETF" 기준으로 적용한다.
6. 인용한 모든 출처는 보고서 맨 끝(10번)에 매체명·날짜와 함께 정리하고, 전체 데이터 기준일을 명시한다.
7. 먼저 자산군(주식형 / 채권형 / 원자재 / 파생·커버드콜 / 멀티에셋)을 판별한다. 주식형이 아니면 PER·PBR 대신 자산군에 맞는 핵심 지표로 대체한다.
8. 세율·공제·종합과세 기준 등 제도·수치는 본 프롬프트에 적힌 값을 그대로 믿지 말고 분석 실행일 기준 최신 세법을 확인한다. 변경 시 변경 내용과 시행일을 명시한다.

────────────────────────
[ 한국 투자자 세금 골격 — 실행일 재확인 필수, 그대로 신뢰 금지 ]
────────────────────────
- 미국 상장 ETF(해외상장): 매매차익은 양도소득세 대상(연 기본공제 후 초과분 과세), 분배금은 배당소득세 대상이며, 배당·이자 등과 합산해 일정 한도 초과 시 금융소득종합과세 대상이 될 수 있다.
- 금융투자소득세(금투세) 등 제도 변경 여부를 함께 확인한다.
- USD/KRW 환노출과 환헤지(H)/언헤지(UH) 여부를 명시한다.
- 절세계좌(연금저축·IRP·ISA)에서의 해외상장 ETF 편입 가능 여부·혜택은 실행일 기준으로 확인한다.
- 위 세율·한도·기준은 반드시 실행일 기준으로 검색해 확인하고, 적용한 값의 출처와 시행일을 표기한다.

────────────────────────
[ 출력 규칙 ]
────────────────────────
- 0번 TL;DR과 핵심 지표 표를 먼저 완성한 뒤, 섹션을 순서대로 "각 섹션 단위로 완결"해 출력한다.
- 분량이 토큰 한도로 잘릴 것 같으면 우선순위(0 → 9 → 2 → 3 → 5 → 나머지) 순으로 출력하고, 생략·축약한 섹션을 끝에 명시한다.
- 단일 티커이므로 0~11번만 작성한다(비교 모드 없음).

────────────────────────
[ 출력 형식 (이 순서·제목 그대로) ]
────────────────────────

## 0. 한눈에 보기 (TL;DR)
- 분석 실행일 / 자산군 / 3~4줄 요약 + 핵심 지표 표(가중 PER · 가중 PBR · 배당수익률 · 총보수 · AUM · 상위10 집중도)
- 한 줄 결론 + 투자 의견: [매수 / 관망 / 회피] + 확신도(고/중/저) + 권장 투자 기간

## 1. 기본 개요
정식 명칭 / 운용사 / 추종 지수 / 상장 거래소 / 자산군 / 총보수(TER) / 순자산(AUM) / 설정일 / 보유 종목 수 / 분배 주기 / 운용 방식(패시브·액티브) / 복제 방식(실물·합성) / 환헤지 여부(H·UH) / 레버리지·인버스 여부

## 2. 구성 종목 분석
- 상위 10개 이상 종목 표: [종목명 | 티커 | 비중% | 섹터 | PER | PBR | 배당수익률 | 시가총액]
- 최소 상위 10개는 반드시 포함, 가능하면 전체 보유 비중을 가중에 반영.
- 섹터별 비중, 국가/통화별 비중
- 집중도: 상위 10개 합산 비중 + 단일 종목 최대 비중
- (주식형이 아니면) 자산군에 맞는 구성 정보로 대체: 채권→만기·신용등급 분포 / 원자재→기초자산·선물 구성 / 커버드콜→기초지수·옵션 구조

## 3. ETF 종합 밸류에이션 (비중 가중)
- [주식형] 가중 PER, 가중 PBR, 가중 배당수익률, 가중 ROE, (가능 시) 가중 이익성장률
  · PER 계산법: 단순 가중평균은 적자 기업 때문에 왜곡되므로, 비중가중 이익수익률(E/P)을 합산한 뒤 역수를 취하는 가중조화평균을 우선 사용한다. 적자(음수 이익) 종목 처리 방식을 반드시 명시한다.
  · Forward(예상) 기준인지 Trailing(실적) 기준인지 구분 표기.
  · 운용사 펀드 페이지가 가중 P/E·P/B를 직접 공시하면 그 값을 [공식]으로 우선 사용한다.
- [역사적 밸류에이션 위치 — 접근 B] 코드 수집 결과의 '배당수익률 밴드'로 현재 밸류에이션의 역사적 위치를 평가한다.
  · ETF 집계 PER/PBR의 과거 시계열은 무료 소스가 없으므로, 가격·배당 히스토리로 만든 TTM 배당수익률 밴드(약 10년)를 밸류에이션 프록시로 쓴다.
  · 현재 배당수익률의 퍼센타일·z-score로 저평가/적정/고평가를 판정한다(수익률 퍼센타일↑ = 가격이 배당 대비 낮음 = 역사적 저평가 신호).
  · 한계 명시: 분배정책 변경·ROC(원금반환)·커버드콜·옵션 프리미엄은 밴드를 왜곡하므로, 커버드콜·파생형 ETF에는 이 프록시를 적용하지 말고 "확인 불가"로 둔다(§5 분배의 질과 연결).
- [역사적 밸류에이션 위치 — 접근 C, 주식형 한정] §2-3 edgartools 재구성 밴드로 PER/PBR의 역사적 위치를 직접 평가한다(접근 B의 배당 프록시를 보완·교차검증).
  · 상위 보유종목의 분기 순이익·자기자본·주식수(edgartools·SEC 실측)로 종목별 PER(=가격/TTM-EPS)·PBR(=가격/BVPS) 시계열을 만들고, 현재 비중을 고정해 가중조화평균으로 ETF 단위 밴드(~10년+)를 재구성한다.
  · 현재값의 퍼센타일·z-score로 저평가/적정/고평가를 판정한다(PER·PBR 퍼센타일↓ = 역사적 저평가 신호 — 배당수익률 밴드와 방향이 반대임에 주의).
  · 결과는 반드시 [추정] 태그로 단다. 한계 명시: 과거에도 현재 비중을 적용(구성 변화 미반영), 상위 N개만 반영(커버리지<100%), 해외·ADR·비주식 보유분은 SEC 미제출로 제외, SEC XBRL은 ~2009년부터라 밴드가 최대 ~15년까지 길어진다(API 키·콜 한도 없음, Q4는 FY−YTD 합성). 커버리지가 낮거나(예: <50%) 데이터가 부족하면 "확인 불가"로 둔다.
- [채권형] 평균 듀레이션, 만기수익률(YTM), 평균 신용등급, 이자율 민감도
- [원자재] 롤오버 비용, 콘탱고/백워데이션 상태, 현물 대비 추적 방식
- [커버드콜·파생] 분배 재원, 옵션 전략(커버 비율·행사가), 기초자산 밸류에이션
- 벤치마크는 ETF 성격에 맞게 자동 선택하고 선택 이유를 한 줄로 밝힌다(예: 광범위 미국주식→S&P500 추종 ETF). 예시 상품의 실행일 기준 유효성을 확인한다.
- 선택한 벤치마크 + 동종 ETF 2~3개 대비 비교표.
- 사용한 계산 방법과 한계(데이터 누락 종목, 추정치 비율)를 한 단락으로 명시.

## 4. 정책 · 지정학 분석 (객관적, 출처 필수)
- (시점 주의) 집권 세력·정책은 분석 실행일 기준으로 검색 확인한다. 예시 정책명은 작성 시점 예시일 뿐이며 실행일 기준 유효한 정책으로 갱신한다.
- 현 정부·정책 수혜 요인 / 역풍 요인 (사실 기반, 출처)
- 지정학적 요인: 공급망·관세·규제·제재·분쟁 등이 이 ETF 테마/구성 종목에 미치는 영향
- 강세 시나리오: 핵심 촉매 3가지 + 각 근거
- 약세 시나리오: 핵심 리스크 3가지 + 각 근거
- 각 시나리오에 주관적 발생 확률(%)을 부여하고(합 100%), 그 확률은 의견임을 명시한다.
- 단기(6~12개월) vs 중장기(3~5년) 전망을 분리.

## 5. 리스크 · 비용 · 유동성 · 분배
- 집중 리스크(상위 종목·단일 섹터·단일 국가)
- 변동성·베타·최대낙폭(MDD) (가능 시)
- 추적오차(벤치마크 대비), 괴리율(NAV 대비 프리미엄/디스카운트)
- 유동성: 일평균 거래대금, 호가 스프레드, AUM 안정성
- 총보수(TER)가 장기 수익에 미치는 영향
- 합성복제(스왑) ETF라면 카운터파티 리스크 점검
- AUM이 과도하게 작으면 상장폐지 가능성 경고
- 레버리지/인버스라면 복리효과·변동성 끌림(decay) 경고
- 분배의 질: 분배 재원(배당/이자/옵션 프리미엄/ROC=원금반환)을 구분하고, ROC 비중이 높으면 "실질 수익이 아닐 수 있음"을 명시. 분배 지속가능성(커버 여부)을 평가한다.

## 6. 한국 투자자 관점
- 세금: 미국 상장 ETF는 해외상장 기준(매매차익 양도소득세, 분배금 배당소득세). 분석 실행일 기준 최신 세법을 확인해 적용하고, 금투세 등 제도 변경 여부를 함께 확인한다. 적용한 세율·공제·기준의 출처와 시행일을 표기한다.
- 환율(USD/KRW) 노출과 환헤지 여부.
- 절세계좌(연금저축·IRP·ISA) — 실행일 기준 편입 가능 여부·한도·혜택 확인.
- 국내 상장된 유사·대체 ETF가 있으면 참고로 제시(실행일 기준 존재·상폐 여부 확인).

## 7. 기술적 · 모멘텀 스냅샷
- 추세: 50일·200일 이동평균 대비 이격도, 골든/데드크로스, MACD(12,26,9) 상태, ADX(14, 추세 강도).
- 모멘텀/위치: RSI(14), 52주 레인지 내 위치 + 52주 고점 대비 낙폭, 볼린저 %B.
- 변동성: 연율 변동성, ATR(14, %), 최대낙폭(MDD).
- 현재가·52주 최고/최저와 위 지표로 최근 추세를 2~3줄로 요약한다.
- 위 값은 코드 수집 결과(EOD 종가 기준)를 사용하고 [실측·코드] 태그 + 기준일(as_of)을 단다. 코드 결과가 없으면 "확인 불가(실시간 데이터 없음)"로 적고 생략한다.

## 8. ETF 스코어카드 (계량 평가)
- 아래 항목을 각 0~10점으로 채점하고, 채점 근거를 한 줄씩 단다.

| 항목 | 가중치 | 채점 기준선(예시) |
|---|---|---|
| 밸류에이션 | 25% | 10=벤치마크 대비 30%+ 할인 또는 배당수익률 퍼센타일 80%ile+ (역사적 저평가) / 5=유사·중앙값 부근 / 0=30%+ 할증 또는 퍼센타일 20%ile- (역사적 고평가) |
| 비용(TER) | 15% | 10=동종 최저권 / 5=평균 / 0=동종 최고권 |
| 리스크 | 25% | 10=낮은 집중·낮은 MDD / 0=고집중·고변동 |
| 모멘텀 | 20% | 10=200일선 위+골든크로스+MACD>0+ADX>25 / 5=중립·횡보 / 0=하락추세(데드크로스·MACD<0) |
| 유동성·분배 안정성 | 15% | 10=높은 거래대금+지속가능 분배 / 0=저유동·ROC 의존 |

- 가중 총점을 100점 만점으로 환산해 제시한다.
- ※ 데이터가 없는 항목은 채점에서 제외하고 그 사실과 가중치 재조정을 명시한다.

## 9. 종합 결론
- 한 줄 결론 + 투자 의견(매수/관망/회피) + 확신도(고/중/저) + 적합한 투자자 유형 + 권장 투자 기간.
- 적정 밸류에이션 밴드: 저평가/적정/고평가 구간(가능하면 가격대 또는 PER·PBR 밴드)과 산출 근거.
- 의견의 핵심 근거 2~3가지.
- 모니터링 포인트 3가지.

## 10. 출처 및 데이터 기준일
- 인용한 출처 목록(매체·날짜)과 전체 데이터 기준일.

## 11. 자기검증 (제출 전 셀프체크 결과)
- 분석 실행일을 상단에 명시했는가?
- 상위 보유 종목 비중 합계가 논리적으로 맞는가(전체 ≈100%)?
- 모든 핵심 수치에 데이터 기준일·소스·신뢰도 태그가 달려 있는가?
- 사실과 전망이 명확히 구분되어 있는가?
- 자산군에 맞는 지표를 사용했는가(주식형이 아닌데 PER을 쓰지 않았는가)?
- 세율·제도를 실행일 기준으로 확인했는가(과거 값 그대로 쓰지 않았는가)?
- 강세/약세 논리가 균형 있게 들어갔는가?
- 위 점검 결과를 "통과/수정함"으로 간단히 표기한다.

본 분석은 정보 제공용이며 투자 권유가 아닙니다.
위 형식에 맞춰, 지금 {TICKER}를 분석해 주세요. (단, 위 '데이터 수집 모드'에 따라 1단계에서는 보고서 대신 수집 스크립트부터 출력하고 멈춘다.)
```

---

## 2-1. 표준 수집 스크립트 (yfinance · 키 불필요)

1단계에서 AI가 출력할 기본 템플릿입니다. 티커만 바꿔 실행하세요.

```python
import yfinance as yf
import pandas as pd
import datetime as _dt

TICKER = "VOO"  # ← 분석할 미국 ETF 티커로 변경

t = yf.Ticker(TICKER)
out = {"ticker": TICKER}

# 1) 가격·추세 (EOD 종가 기준)
try:
    h = t.history(period="1y", auto_adjust=False)
    c = h["Close"].dropna()
    out["price"] = {
        "as_of": str(c.index[-1].date()),
        "last_close": round(float(c.iloc[-1]), 4),
        "ma50": round(float(c.tail(50).mean()), 4),
        "ma200": round(float(c.tail(200).mean()), 4),
        "high_52w": round(float(c.max()), 4),
        "low_52w": round(float(c.min()), 4),
    }
    # 기간 수익률 (거래일 근사: 21/63/126/252일)
    _ret = lambda n: round((float(c.iloc[-1]) / float(c.iloc[-1 - n]) - 1) * 100, 2) if len(c) > n else None
    out["price"]["returns_pct"] = {
        "1m": _ret(21), "3m": _ret(63), "6m": _ret(126), "1y": _ret(252),
    }
    # 최대낙폭(MDD) — 1년 종가 기준
    roll_max = c.cummax()
    dd = (c / roll_max - 1.0)
    out["price"]["max_drawdown_pct"] = round(float(dd.min()) * 100, 2)
    # RSI(14, Wilder) — 최근값 (§7 모멘텀)
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    rsi = (100 - 100 / (1 + gain / loss)).dropna()
    out["price"]["rsi14"] = round(float(rsi.iloc[-1]), 1) if len(rsi) else None
    # 연율화 변동성(%) = 일간수익률 표준편차 × √252 (§5 변동성)
    vol = c.pct_change().dropna().std() * (252 ** 0.5) * 100
    out["price"]["volatility_annual_pct"] = round(float(vol), 2)
    # 일평균 거래대금(최근 20거래일, 상장통화) (§5 유동성)
    dollar = (h["Close"] * h["Volume"]).dropna().tail(20).mean()
    out["price"]["avg_dollar_volume_20d"] = round(float(dollar), 0)
    # 추세: MACD(12,26,9) (§7)
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_sig = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - macd_sig
    out["price"]["macd"] = {
        "macd": round(float(macd.iloc[-1]), 4),
        "signal": round(float(macd_sig.iloc[-1]), 4),
        "hist": round(float(macd_hist.iloc[-1]), 4),
        "state": "강세(>0)" if float(macd_hist.iloc[-1]) > 0 else "약세(<0)",
    }
    # 추세: 이평 크로스(골든/데드) + 이격도 (§7)
    out["price"]["ma_cross"] = "golden" if out["price"]["ma50"] > out["price"]["ma200"] else "dead"
    out["price"]["dist_ma50_pct"]  = round((float(c.iloc[-1]) / out["price"]["ma50"]  - 1) * 100, 2)
    out["price"]["dist_ma200_pct"] = round((float(c.iloc[-1]) / out["price"]["ma200"] - 1) * 100, 2)
    # 위치: 52주 레인지 내 위치 + 고점 대비 (§7)
    _rng = out["price"]["high_52w"] - out["price"]["low_52w"]
    out["price"]["range_pos_pct"] = round((float(c.iloc[-1]) - out["price"]["low_52w"]) / _rng * 100, 1) if _rng else None
    out["price"]["from_52w_high_pct"] = round((float(c.iloc[-1]) / out["price"]["high_52w"] - 1) * 100, 2)
    # 변동성: 볼린저(20,2σ) %B·밴드폭 (§7)
    ma20 = c.rolling(20).mean(); sd20 = c.rolling(20).std()
    bb_up = ma20 + 2 * sd20; bb_lo = ma20 - 2 * sd20
    out["price"]["bollinger"] = {
        "pct_b": round(float((c.iloc[-1] - bb_lo.iloc[-1]) / (bb_up.iloc[-1] - bb_lo.iloc[-1])), 2),
        "bandwidth_pct": round(float((bb_up.iloc[-1] - bb_lo.iloc[-1]) / ma20.iloc[-1]) * 100, 2),
    }
    # 변동성: ATR(14, %) — 손절폭 가늠 (§5·§7)
    _hi, _lo, _pc = h["High"], h["Low"], c.shift()
    _tr = pd.concat([(_hi - _lo), (_hi - _pc).abs(), (_lo - _pc).abs()], axis=1).max(axis=1)
    _atr = _tr.ewm(alpha=1/14, min_periods=14).mean()
    out["price"]["atr_pct"] = round(float(_atr.iloc[-1] / c.iloc[-1]) * 100, 2)
    # 추세 강도: ADX(14) (§7)
    _up = _hi.diff(); _dn = -_lo.diff()
    _plus_dm  = ((_up > _dn) & (_up > 0)) * _up.clip(lower=0)
    _minus_dm = ((_dn > _up) & (_dn > 0)) * _dn.clip(lower=0)
    _atr_w = _tr.ewm(alpha=1/14, min_periods=14).mean()
    _plus_di  = 100 * _plus_dm.ewm(alpha=1/14, min_periods=14).mean()  / _atr_w
    _minus_di = 100 * _minus_dm.ewm(alpha=1/14, min_periods=14).mean() / _atr_w
    _dx = ((_plus_di - _minus_di).abs() / (_plus_di + _minus_di).replace(0, float("nan"))) * 100
    _adx = _dx.ewm(alpha=1/14, min_periods=14).mean()
    out["price"]["adx14"] = round(float(_adx.iloc[-1]), 1)
except Exception as e:
    out["price_error"] = str(e)

# 2) 기본 프로필
try:
    info = t.info
    out["profile"] = {
        "name": info.get("longName"),
        "issuer": info.get("fundFamily"),
        "category": info.get("category"),
        "legal_type": info.get("legalType"),
        "inception_date": info.get("fundInceptionDate"),
        "expense_ratio": info.get("netExpenseRatio"),
        "total_assets": info.get("totalAssets"),
        "yield": info.get("yield"),
        "beta": info.get("beta3Year") or info.get("beta"),
    }
except Exception as e:
    out["profile_error"] = str(e)

# 3) ETF 보유종목·섹터 + 상위 종목 펀더멘털 (PER/PBR/ROE)
try:
    fd = t.funds_data
    holdings = fd.top_holdings.reset_index().to_dict(orient="records")
    out["sector_weights"] = fd.sector_weightings

    # ETF 전체 밸류에이션 (야후 펀드 집계값)
    try:
        raw = fd.equity_holdings.to_dict()
        fund_col = raw.get(TICKER) or next(iter(raw.values()))
        _inv = lambda x: round(1.0 / x, 2) if isinstance(x, (int, float)) and x else None
        out["etf_valuation"] = {
            "per": _inv(fund_col.get("Price/Earnings")),
            "pbr": _inv(fund_col.get("Price/Book")),
        }
    except Exception as e:
        out["etf_valuation_error"] = str(e)

    # 상위 보유종목 각각의 PER/PBR/ROE/배당/시총을 받아 가중 밸류에이션(3번)에 사용
    enriched = []
    for hld in holdings:
        sym = hld.get("Symbol") or hld.get("symbol")
        row = {
            "symbol": sym,
            "weight": hld.get("Holding Percent") or hld.get("% Assets"),
        }
        try:
            i = yf.Ticker(sym).info
            row.update({
                "name": i.get("longName") or i.get("shortName"),
                "sector": i.get("sector"),
                "trailing_pe": i.get("trailingPE"),
                "forward_pe": i.get("forwardPE"),
                "pbr": i.get("priceToBook"),
                "dividend_yield": i.get("dividendYield"),
                "roe": i.get("returnOnEquity"),
                "market_cap": i.get("marketCap"),
            })
        except Exception as e:
            row["error"] = str(e)
        enriched.append(row)
    out["top_holdings"] = enriched

    # 상위 보유종목으로 직접 가중조화평균 PER/PBR 계산 (비중 재정규화, 음수·null 제외)
    def _wh(field):
        num = 0.0  # 유효 비중 합
        den = 0.0  # Σ(비중/지표)
        for r in enriched:
            w, v = r.get("weight"), r.get(field)
            if isinstance(w, (int, float)) and isinstance(v, (int, float)) and v > 0:
                num += w
                den += w / v
        return (round(num / den, 2) if den else None), round(num, 4)

    # 합산형 지표(배당·ROE)는 가중산술평균 (비율 역수문제 없음)
    def _wavg(field):
        num = 0.0  # Σ(비중×지표)
        den = 0.0  # 유효 비중 합
        for r in enriched:
            w, v = r.get("weight"), r.get(field)
            if isinstance(w, (int, float)) and isinstance(v, (int, float)):
                num += w * v
                den += w
        return round(num / den, 4) if den else None

    pe_t, cov = _wh("trailing_pe")
    pe_f, _ = _wh("forward_pe")
    pb, _ = _wh("pbr")
    out["weighted_valuation"] = {
        "method": "PER·PBR=가중조화평균 / 배당·ROE=가중산술평균 (top-N, 비중 재정규화, PER·PBR은 음수·null 제외)",
        "coverage_weight": cov,
        "weighted_pe_trailing": pe_t,
        "weighted_pe_forward": pe_f,
        "weighted_pbr": pb,
        "weighted_dividend_yield": _wavg("dividend_yield"),
        "weighted_roe": _wavg("roe"),
    }

    # 집중도: 상위 종목 비중 합 + 단일 최대 비중 (§0·§2)
    ws = [r.get("weight") for r in enriched if isinstance(r.get("weight"), (int, float))]
    out["concentration"] = {
        "top_n_weight_sum": round(sum(ws), 4) if ws else None,
        "max_single_weight": round(max(ws), 4) if ws else None,
    }
except Exception as e:
    out["holdings_error"] = str(e)

# 4) 분배금 이력 (최근 8회)
try:
    d = t.dividends.tail(8)
    out["dividends"] = {str(k.date()): round(float(v), 4) for k, v in d.items()}
except Exception as e:
    out["dividends_error"] = str(e)

# 5) 배당수익률 밴드 (접근 B: 가격·배당 히스토리로 역사적 밸류에이션 프록시 / §3)
try:
    px10 = t.history(period="10y", auto_adjust=False)["Close"].dropna()
    div_all = t.dividends
    if len(div_all) and len(px10):
        div_ttm = div_all.rolling("365D").sum().reindex(px10.index, method="ffill").fillna(0)
        ys = ((div_ttm / px10) * 100).dropna()
        ys = ys[ys > 0]
        if len(ys):
            cur_y = float(ys.iloc[-1])
            _std = float(ys.std())
            out["yield_band"] = {
                "as_of": str(px10.index[-1].date()),
                "lookback_years": round(len(px10) / 252, 1),
                "current_yield_pct": round(cur_y, 2),
                "avg_yield_pct": round(float(ys.mean()), 2),
                "median_yield_pct": round(float(ys.median()), 2),
                "min_yield_pct": round(float(ys.min()), 2),
                "max_yield_pct": round(float(ys.max()), 2),
                "percentile_pct": round(float((ys <= cur_y).mean()) * 100, 0),
                "zscore": round((cur_y - float(ys.mean())) / _std, 2) if _std else None,
            }
except Exception as e:
    out["yield_band_error"] = str(e)

# ── 결과 요약 출력 ──
_f = lambda x, nd=2: "—" if x is None else f"{x:,.{nd}f}"
_mult = lambda x: "—" if x is None else f"{x:.1f}배"
_pct = lambda x: "—" if x is None else f"{x:.2f}%"
_pcts = lambda x: "—" if x is None else f"{x:+.2f}%"
_pctf = lambda x: "—" if x is None else f"{x*100:.2f}%"
_usd = lambda x: "—" if x is None else (f"${x/1e12:.2f}T" if abs(x) >= 1e12 else f"${x/1e9:.2f}B" if abs(x) >= 1e9 else f"${x/1e6:.2f}M" if abs(x) >= 1e6 else f"${x:,.2f}")
_epoch = lambda x: _dt.datetime.utcfromtimestamp(x).strftime("%Y-%m-%d") if isinstance(x, (int, float)) else "—"

p  = out.get("price", {})
pf = out.get("profile", {})
ev = out.get("etf_valuation", {})
wv = out.get("weighted_valuation", {})
cc = out.get("concentration", {})
r  = p.get("returns_pct", {})

L = []
L.append("=" * 60)
L.append(f" [{out.get('ticker')}] 표준 수집 결과 요약   (기준일: {p.get('as_of', '—')})")
L.append("=" * 60)
L.append("* 값이 '—'이면 확인 불가(데이터 없음). 모든 수치는 코드 실측값이며 표시 단위로 반올림됨.")
L.append("■ 가격·추세")
L.append(f"  현재가              : {_usd(p.get('last_close'))}")
L.append(f"  50일 / 200일 이평   : {_usd(p.get('ma50'))} / {_usd(p.get('ma200'))}")
L.append(f"  52주 고 / 저        : {_usd(p.get('high_52w'))} / {_usd(p.get('low_52w'))}")
L.append(f"  수익률 1M/3M/6M/1Y  : {_pcts(r.get('1m'))} / {_pcts(r.get('3m'))} / {_pcts(r.get('6m'))} / {_pcts(r.get('1y'))}")
L.append(f"  최대낙폭(MDD)       : {_pct(p.get('max_drawdown_pct'))}")
L.append(f"  RSI(14)             : {_f(p.get('rsi14'), 1)}")
L.append(f"  연율 변동성         : {_pct(p.get('volatility_annual_pct'))}")
L.append(f"  일평균 거래대금     : {_usd(p.get('avg_dollar_volume_20d'))}")
mc = p.get("macd", {}); bb = p.get("bollinger", {})
L.append("■ 기술적 지표 (추세·모멘텀·변동성)")
L.append(f"  이평 크로스/이격도  : {p.get('ma_cross', '—')}  (50일 {_pcts(p.get('dist_ma50_pct'))} · 200일 {_pcts(p.get('dist_ma200_pct'))})")
L.append(f"  MACD(12,26,9)       : {mc.get('state', '—')}  (MACD {_f(mc.get('macd'), 3)} · Sig {_f(mc.get('signal'), 3)} · Hist {_f(mc.get('hist'), 3)})")
L.append(f"  ADX(14)             : {_f(p.get('adx14'), 1)}  (>25 강추세 / <20 횡보)")
L.append(f"  볼린저 %B / 밴드폭  : {_f(bb.get('pct_b'), 2)} / {_pct(bb.get('bandwidth_pct'))}  (%B 0=하단·1=상단)")
L.append(f"  ATR(14)             : {_pct(p.get('atr_pct'))}")
L.append(f"  52주 위치/고점대비  : {_f(p.get('range_pos_pct'), 1)}% / {_pcts(p.get('from_52w_high_pct'))}")
L.append("■ 기본 프로필")
L.append(f"  명칭                : {pf.get('name', '—')}")
L.append(f"  운용사              : {pf.get('issuer', '—')}")
L.append(f"  카테고리 / 구조     : {pf.get('category', '—')} / {pf.get('legal_type', '—')}")
L.append(f"  총보수(TER)         : {_pctf(pf.get('expense_ratio'))}")
L.append(f"  순자산(AUM)         : {_usd(pf.get('total_assets'))}")
L.append(f"  배당수익률          : {_pctf(pf.get('yield'))}")
L.append(f"  베타                : {_f(pf.get('beta'), 2)}")
L.append(f"  설정일              : {_epoch(pf.get('inception_date'))}")
L.append("■ 섹터별 비중  (비중 큰 순)")
sw = out.get("sector_weights") or {}
if sw:
    for _k, _v in sorted(sw.items(), key=lambda kv: (kv[1] or 0), reverse=True):
        L.append(f"  {str(_k):<22}: {_pctf(_v)}")
else:
    L.append("  —")
L.append("■ ETF 전체 밸류에이션  (Yahoo 집계 · 전 종목 · 후행 기준)")
L.append(f"  PER / PBR           : {_mult(ev.get('per'))} / {_mult(ev.get('pbr'))}")
L.append(f"■ 가중 밸류에이션  (상위 N개 직접계산 · 커버리지 {_pctf(wv.get('coverage_weight'))})")
L.append(f"  가중 후행 PER       : {_mult(wv.get('weighted_pe_trailing'))}")
L.append(f"  가중 선행 PER       : {_mult(wv.get('weighted_pe_forward'))}")
L.append(f"  가중 PBR            : {_mult(wv.get('weighted_pbr'))}")
L.append(f"  가중 배당수익률     : {_pctf(wv.get('weighted_dividend_yield'))}")
L.append(f"  가중 ROE            : {_pctf(wv.get('weighted_roe'))}")
L.append(f"  계산법              : {wv.get('method', '—')}")
L.append("■ 집중도")
L.append(f"  상위 종목 합산비중  : {_pctf(cc.get('top_n_weight_sum'))}  (단일 최대 {_pctf(cc.get('max_single_weight'))})")
yb = out.get("yield_band", {})
L.append(f"■ 배당수익률 밴드  (접근 B · 최근 {_f(yb.get('lookback_years'), 1)}년 · 기준일 {yb.get('as_of', '—')})")
L.append(f"  현재/평균/중위      : {_pct(yb.get('current_yield_pct'))} / {_pct(yb.get('avg_yield_pct'))} / {_pct(yb.get('median_yield_pct'))}")
L.append(f"  최저/최고           : {_pct(yb.get('min_yield_pct'))} / {_pct(yb.get('max_yield_pct'))}")
L.append(f"  현재 퍼센타일 / z   : {_f(yb.get('percentile_pct'), 0)}% / {_f(yb.get('zscore'), 2)}  (수익률 퍼센타일↑ = 역사적 저평가 신호)")
L.append("■ 상위 보유종목  [티커 | 종목명 | 비중 | 후행PER | 선행PER | PBR | 배당 | ROE | 시총 | 섹터]")
for h in out.get("top_holdings", []):
    _nm = (h.get("name") or "—")[:20]
    L.append(f"  {str(h.get('symbol', '—')):<6}{_nm:<22}{_pctf(h.get('weight')):>8}"
             f"{_mult(h.get('trailing_pe')):>9}{_mult(h.get('forward_pe')):>9}"
             f"{_mult(h.get('pbr')):>8}{_pctf(h.get('dividend_yield')):>8}"
             f"{_pctf(h.get('roe')):>8}{_usd(h.get('market_cap')):>11}  {h.get('sector', '—')}")
L.append("■ 분배금 이력  (최근 8회)")
dv = out.get("dividends") or {}
if dv:
    for _d, _amt in dv.items():
        L.append(f"  {_d} : ${_amt}")
else:
    L.append("  —")
errs = {k: v for k, v in out.items() if k.endswith("_error")}
if errs:
    L.append("■ 수집 오류  (아래 항목은 값이 비어 있을 수 있음)")
    for _k, _v in errs.items():
        L.append(f"  {_k} : {_v}")
L.append("=" * 60)
print("\n".join(L))
```

---

## 2-2. 동종/벤치마크 ETF 비교 스크립트 (3단계에서 출력)

AI가 추천하고 사용자가 확정해 보낸 후보 티커를 넣고 실행하세요. 분석 대상 + 비교군 3~5개를 한 번에 비교합니다.

```python
import yfinance as yf

# AI가 제시한 후보로 교체 (분석 대상 + 동종/벤치마크 3~5개)
PEERS = ["SOXX", "XSD", "PSI", "IGV"]

def snap(tk):
    t = yf.Ticker(tk)
    o = {"ticker": tk}
    try:
        info = t.info
        o["name"] = info.get("longName")
        o["expense_ratio"] = info.get("netExpenseRatio")
        o["total_assets"] = info.get("totalAssets")
        o["yield"] = info.get("yield")
        o["beta"] = info.get("beta3Year") or info.get("beta")
    except Exception as e:
        o["info_error"] = str(e)
    try:
        c = t.history(period="1y", auto_adjust=False)["Close"].dropna()
        o["as_of"] = str(c.index[-1].date())
        o["last_close"] = round(float(c.iloc[-1]), 2)
        _ret = lambda n: round((float(c.iloc[-1]) / float(c.iloc[-1 - n]) - 1) * 100, 2) if len(c) > n else None
        o["returns_pct"] = {"3m": _ret(63), "6m": _ret(126), "1y": _ret(252)}
        o["max_drawdown_pct"] = round(float((c / c.cummax() - 1.0).min()) * 100, 2)
    except Exception as e:
        o["price_error"] = str(e)
    try:
        raw = t.funds_data.equity_holdings.to_dict()
        col = raw.get(tk) or next(iter(raw.values()))
        _inv = lambda x: round(1.0 / x, 2) if isinstance(x, (int, float)) and x else None
        o["per"] = _inv(col.get("Price/Earnings"))
        o["pbr"] = _inv(col.get("Price/Book"))
    except Exception as e:
        o["valuation_error"] = str(e)
    return o

_f = lambda x, nd=2: "—" if x is None else f"{x:,.{nd}f}"
_mult = lambda x: "—" if x is None else f"{x:.1f}"
_pct = lambda x: "—" if x is None else f"{x:.2f}%"
_pcts = lambda x: "—" if x is None else f"{x:+.2f}%"
_pctf = lambda x: "—" if x is None else f"{x*100:.2f}%"
_usd = lambda x: "—" if x is None else (f"${x/1e12:.2f}T" if abs(x) >= 1e12 else f"${x/1e9:.2f}B" if abs(x) >= 1e9 else f"${x/1e6:.2f}M" if abs(x) >= 1e6 else f"${x:,.0f}")

rows = [snap(tk) for tk in PEERS]
as_of = rows[0].get("as_of", "—") if rows else "—"
print("=" * 66)
print(f" 동종/벤치마크 ETF 비교 요약   (기준일: {as_of})")
print(" 열: TER=총보수 · AUM=순자산 · Yld=배당 · 1Y=1년수익 · MDD=최대낙폭 · PER/PBR=ETF전체(후행)")
print(" * 값이 '—'이면 확인 불가(데이터 없음).")
print("=" * 66)
print(f"{'Tkr':<6}{'TER':>7}{'AUM':>10}{'Yld':>7}{'Beta':>6}{'1Y':>9}{'MDD':>9}{'PER':>6}{'PBR':>6}")
print("-" * 66)
for o in rows:
    rp = o.get("returns_pct", {})
    print(f"{str(o.get('ticker', '—')):<6}"
          f"{_pctf(o.get('expense_ratio')):>7}"
          f"{_usd(o.get('total_assets')):>10}"
          f"{_pctf(o.get('yield')):>7}"
          f"{_f(o.get('beta'), 2):>6}"
          f"{_pcts(rp.get('1y')):>9}"
          f"{_pct(o.get('max_drawdown_pct')):>9}"
          f"{_mult(o.get('per')):>6}"
          f"{_mult(o.get('pbr')):>6}")
print("=" * 66)
print("■ 상세 (종목명 · 현재가 · 단기수익률)")
for o in rows:
    rp = o.get("returns_pct", {})
    print(f"  {str(o.get('ticker', '—')):<6} {o.get('name', '—')}")
    print(f"        현재가 {_usd(o.get('last_close'))} · 3M {_pcts(rp.get('3m'))} · 6M {_pcts(rp.get('6m'))} · 기준일 {o.get('as_of', '—')}")
errs = [(o.get("ticker"), {k: v for k, v in o.items() if k.endswith("_error")}) for o in rows]
errs = [(tk, e) for tk, e in errs if e]
if errs:
    print("■ 수집 오류")
    for tk, e in errs:
        for _k, _v in e.items():
            print(f"  {tk} {_k} : {_v}")
print("=" * 66)
```

---

## 2-3. 역사적 PER/PBR 재구성 스크립트 (접근 C · edgartools · SEC 실측 · API 키 불필요)

주식형 ETF에 한해 1단계에서 §2-1과 함께 실행하고, 출력 요약을 그대로 붙여넣어 §3 '접근 C' 평가에 사용하세요.

- **설치**: `pip install edgartools etf-scraper yfinance pandas`
- **보유종목 소스(하이브리드)**: A) etf-scraper(운용사 공식 전체보유) → B) SEC N-PORT(모든 미국 ETF) → C) yfinance 상위10(폴백)
- **장점**: API 키·일일 콜 한도 없음 / 히스토리 ~10년+(SEC XBRL 2009~) / SEC 1차 출처 / 공시일(filed) PIT
- **한계**: ① SEC 미제출 종목(해외·ADR 등) 제외 ② Q4는 FY−YTD 합성 ③ 현재 비중 고정(구성변화 미반영) ④ 상위 TOP_N개만 반영

```python
# ── 접근 C (edgartools 버전): SEC 실측 펀더멘털로 역사적 PER/PBR 재구성 ──
import yfinance as yf
import pandas as pd
import datetime as _dt
import bisect, time
from edgar import Company, set_identity

# ── 설정 블록 (여기만 수정) ─────────────────────────────
ETF            = "VOO"        # 분석 대상 ETF 티커
TOP_N          = 50          # 상위 보유종목 수 (광범위 ETF는 50~100 권장)
LOOKBACK_Y     = 12          # SEC XBRL은 ~2009년부터 → 최대 ~15년
EDGAR_IDENTITY = "Your Name your@email.com"  # ★ SEC 요구: 실명+이메일
METRICS        = "both"      # "per" | "pbr" | "both"
SEC_PAUSE      = 0.0         # edgartools가 rate limit 자체 처리
MIN_COVERAGE   = 50          # 커버리지(%)가 이 값 미만이면 '확인 불가'
PER_BOUNDS     = (1.0, 500.0)
PBR_BOUNDS     = (0.1, 100.0)
# ──────────────────────────────────────────────────────

set_identity(EDGAR_IDENTITY)

NI_TAGS     = ["NetIncomeLoss", "ProfitLoss",
               "NetIncomeLossAvailableToCommonStockholdersBasic"]
EQUITY_TAGS = ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]
SHARE_TAGS  = ["WeightedAverageNumberOfDilutedSharesOutstanding",
               "WeightedAverageNumberOfSharesOutstandingBasic",
               "CommonStockSharesOutstanding"]

def _num(x):
    try:
        if x is None or x == "": return None
        return float(x)
    except (TypeError, ValueError):
        return None

def _date(x):
    if x is None or x == "": return None
    if isinstance(x, _dt.datetime): return x.date()
    if isinstance(x, _dt.date): return x
    try:
        return _dt.date.fromisoformat(str(x)[:10])
    except ValueError:
        return None

def _col(df, *cands):
    for c in cands:
        if c in df.columns: return c
    return None

def _months(s, e):
    if s is None or e is None: return None
    return round((e - s).days / 30.4)

def concept_df(facts, tag):
    for q in (
        lambda: facts.query().by_concept(f"us-gaap:{tag}", exact=True)
                     .by_form_type(["10-K", "10-Q"]).to_dataframe(),
        lambda: facts.query().by_concept(tag, exact=True)
                     .by_form_type(["10-K", "10-Q"]).to_dataframe(),
    ):
        try:
            df = q()
        except Exception:
            df = None
        if df is not None and len(df) > 0:
            return df
    return None

def _rows(df):
    cval  = _col(df, "numeric_value", "value", "val")
    cend  = _col(df, "period_end", "end", "period_end_date")
    cstart= _col(df, "period_start", "start", "period_start_date")
    cfile = _col(df, "filing_date", "filed", "filed_date", "accepted_date")
    cform = _col(df, "form_type", "form")
    cfp   = _col(df, "fiscal_period", "fp")
    out = []
    for _, r in df.iterrows():
        out.append({
            "value": _num(r.get(cval)) if cval else None,
            "end":   _date(r.get(cend)) if cend else None,
            "start": _date(r.get(cstart)) if cstart else None,
            "filed": _date(r.get(cfile)) if cfile else None,
            "form":  r.get(cform) if cform else None,
            "fp":    r.get(cfp) if cfp else None,
        })
    return out

def _earliest_by_end(rows, pick):
    d = {}
    for r in rows:
        if r["value"] is None or r["end"] is None or not pick(r): continue
        key, filed = r["end"], r["filed"]
        if key not in d or (filed and (d[key][1] is None or filed < d[key][1])):
            d[key] = (r["value"], filed)
    return d

def _is_q(r):
    m = _months(r["start"], r["end"])
    if m is not None: return 2 <= m <= 4
    return str(r["form"]) == "10-Q" and str(r["fp"]) in ("Q1", "Q2", "Q3")

def _is_a(r):
    m = _months(r["start"], r["end"])
    if m is not None: return 11 <= m <= 13
    return str(r["form"]) == "10-K" and str(r["fp"]) in ("FY", "Q4")

def _is_instant(r):
    m = _months(r["start"], r["end"])
    if m is not None: return m <= 1
    return r["start"] is None

def discrete_with_q4(rows):
    q = _earliest_by_end(rows, _is_q)
    a = _earliest_by_end(rows, _is_a)
    out = dict(q)
    q_ends = sorted(q.keys())
    for end, (av, afiled) in a.items():
        if end in out: continue
        lo = end - _dt.timedelta(days=360)
        prior = sorted(e for e in q_ends if lo < e <= end - _dt.timedelta(days=20))[-3:]
        if len(prior) == 3:
            out[end] = (av - sum(q[e][0] for e in prior), afiled)
    return out

def ttm_points(disc):
    ends = sorted(disc.keys())
    pts = []
    for i in range(3, len(ends)):
        win = ends[i - 3:i + 1]
        if any((win[j + 1] - win[j]).days > 130 for j in range(3)): continue
        vals = [disc[e][0] for e in win]
        if any(v is None for v in vals): continue
        fileds = [disc[e][1] for e in win if disc[e][1]]
        pts.append((win[-1], sum(vals), max(fileds) if fileds else win[-1]))
    return pts

def level_list(rows, pick):
    return sorted((e, v, f) for e, (v, f) in _earliest_by_end(rows, pick).items())

def level_at(levels, target_end):
    ends = [x[0] for x in levels]
    i = bisect.bisect_right(ends, target_end) - 1
    return levels[i][1] if i >= 0 else None

def monthly_prices(sym, start):
    px = yf.Ticker(sym).history(start=start, auto_adjust=False)["Close"].dropna()
    if px.empty: return None
    px.index = px.index.tz_localize(None)
    try:    return px.resample("ME").last()
    except ValueError: return px.resample("M").last()

def asof_ratio(price_m, knowns, vals, bounds):
    f = pd.DataFrame({"known": pd.to_datetime([pd.Timestamp(k) for k in knowns]),
                      "val": vals}).dropna()
    f = f[f["val"] > 0].sort_values("known")
    if f.empty: return None
    pm = pd.DataFrame({"date": pd.to_datetime(price_m.index),
                       "price": price_m.values}).sort_values("date")
    m = pd.merge_asof(pm, f, left_on="date", right_on="known", direction="backward").dropna(subset=["val"])
    if m.empty: return None
    r = pd.Series((m["price"] / m["val"]).values, index=pd.DatetimeIndex(m["date"].values))
    lo, hi = bounds
    r = r[(r >= lo) & (r <= hi)]
    return r if len(r) >= 8 else None

def make_company(sym):
    for s in (sym, sym.replace("-", "."), sym.replace(".", "-")):
        try:
            c = Company(s)
            if c is not None: return c
        except Exception:
            continue
    return None

def per_pbr(sym, start, want_per, want_pbr):
    px = monthly_prices(sym, start)
    if px is None or px.empty: return None, None, "가격없음"
    c = make_company(sym)
    if c is None: return None, None, "회사조회실패"
    try:
        facts = c.get_facts()
    except Exception as e:
        return None, None, f"facts오류({str(e)[:40]})"
    if facts is None: return None, None, "facts없음(SEC 미제출?)"

    shares = []
    for tag in SHARE_TAGS:
        df = concept_df(facts, tag)
        if df is None: continue
        rows = _rows(df)
        pick = _is_instant if tag == "CommonStockSharesOutstanding" else (lambda r: _is_q(r) or _is_a(r))
        shares = level_list(rows, pick)
        if shares: break
    if not shares: return None, None, "주식수없음"

    per = pbr = None
    if want_per:
        for tag in NI_TAGS:
            df = concept_df(facts, tag)
            if df is None: continue
            pts = ttm_points(discrete_with_q4(_rows(df)))
            knowns, vals = [], []
            for end, ttmni, filed in pts:
                sh = level_at(shares, end)
                if sh and sh > 0:
                    knowns.append(filed or end); vals.append(ttmni / sh)
            if knowns:
                per = asof_ratio(px, knowns, vals, PER_BOUNDS)
                if per is not None: break
    if want_pbr:
        for tag in EQUITY_TAGS:
            df = concept_df(facts, tag)
            if df is None: continue
            eq = level_list(_rows(df), lambda r: _is_instant(r) or _is_a(r) or _is_q(r))
            knowns, vals = [], []
            for end, eqv, filed in eq:
                sh = level_at(shares, end)
                if sh and sh > 0 and eqv:
                    knowns.append(filed or end); vals.append(eqv / sh)
            if knowns:
                pbr = asof_ratio(px, knowns, vals, PBR_BOUNDS)
                if pbr is not None: break
    return per, pbr, None

def align_frame(series_map):
    series_map = {k: v for k, v in series_map.items() if v is not None and len(v)}
    if not series_map: return pd.DataFrame()
    start = min(s.index.min() for s in series_map.values())
    end   = max(s.index.max() for s in series_map.values())
    try: grid = pd.date_range(start, end, freq="ME")
    except ValueError: grid = pd.date_range(start, end, freq="M")
    cols = {sym: s.sort_index().reindex(grid, method="ffill") for sym, s in series_map.items()}
    return pd.DataFrame(cols, index=grid)

def agg_band(frame, weights):
    if frame is None or frame.empty: return None, None
    W = pd.Series(weights).reindex(frame.columns).fillna(0.0)
    inv = 1.0 / frame
    cov = frame.notna().mul(W, axis=1).sum(axis=1)
    num = inv.mul(W, axis=1).sum(axis=1, skipna=True)
    band = (cov / num).where(num > 0).dropna()
    return band, cov.reindex(band.index)

def band_stats(band, cov):
    if band is None or band.empty: return None
    cur, mu, sd = float(band.iloc[-1]), float(band.mean()), float(band.std())
    return {
        "as_of": str(band.index[-1].date()),
        "lookback_years": round((band.index[-1] - band.index[0]).days / 365, 1),
        "n_points": int(band.shape[0]),
        "current": round(cur, 2), "avg": round(mu, 2),
        "median": round(float(band.median()), 2),
        "min": round(float(band.min()), 2), "max": round(float(band.max()), 2),
        "percentile_pct": round(float((band <= cur).mean()) * 100, 0),
        "zscore": round((cur - mu) / sd, 2) if sd else None,
        "coverage_now_pct": round(float(cov.iloc[-1]) * 100, 1),
    }

def _norm_holdings(pairs):
    agg = {}
    for sym, w in pairs:
        if not sym or not isinstance(w, (int, float)) or w <= 0: continue
        s = str(sym).strip().upper().replace(".", "-")
        if not s or s in ("--", "NAN", "NONE"): continue
        agg[s] = agg.get(s, 0.0) + float(w)
    return sorted(agg.items(), key=lambda kv: kv[1], reverse=True)

def _holdings_etfscraper(etf):
    from etf_scraper import ETFScraper
    df = ETFScraper().query_holdings(etf, None)
    if df is None or len(df) == 0: return []
    cols = {c.lower(): c for c in df.columns}
    c_tkr = next((cols[k] for k in ("ticker", "holding_ticker", "symbol") if k in cols), None)
    c_w   = next((cols[k] for k in ("weight", "weighting", "pct_value") if k in cols), None)
    c_cls = next((cols[k] for k in ("asset_class", "asset_category") if k in cols), None)
    if not c_tkr or not c_w: return []
    pairs = []
    for _, r in df.iterrows():
        if c_cls is not None:
            cls = str(r.get(c_cls) or "").lower()
            if cls and "equity" not in cls and "stock" not in cls: continue
        w = _num(r.get(c_w))
        if w is None: continue
        pairs.append((r.get(c_tkr), w / 100.0))
    return _norm_holdings(pairs)

def _holdings_nport(etf):
    flist = Company(etf).get_filings(form="NPORT-P")
    if flist is None or len(flist) == 0: return []
    report = flist.latest().obj()
    df = report.investment_data(include_derivatives=False)
    if df is None or len(df) == 0: return []
    cols = {c.lower(): c for c in df.columns}
    c_tkr = cols.get("ticker"); c_pct = cols.get("pct_value")
    c_val = cols.get("value_usd"); c_cat = cols.get("asset_category")
    if not c_tkr: return []
    total = sum(_num(r.get(c_val)) or 0.0 for _, r in df.iterrows()) if (c_pct is None and c_val) else None
    pairs = []
    for _, r in df.iterrows():
        if c_cat is not None and str(r.get(c_cat) or "").upper() not in ("EC", ""): continue
        tkr = r.get(c_tkr)
        if not tkr: continue
        if c_pct is not None:
            w = _num(r.get(c_pct)); w = w / 100.0 if w is not None else None
        elif total:
            v = _num(r.get(c_val)); w = (v / total) if (v is not None) else None
        else:
            w = None
        if w is None: continue
        pairs.append((tkr, w))
    return _norm_holdings(pairs)

def _holdings_yf(etf):
    raw = yf.Ticker(etf).funds_data.top_holdings.reset_index().to_dict("records")
    return _norm_holdings([(r.get("Symbol") or r.get("symbol"),
                            r.get("Holding Percent") or r.get("% Assets")) for r in raw])

def get_holdings(etf, top_n):
    errs = []
    for name, fn in (("etf-scraper(운용사 공식)", _holdings_etfscraper),
                     ("SEC N-PORT", _holdings_nport),
                     ("yfinance(상위10·폴백)", _holdings_yf)):
        try:
            h = fn(etf)
        except Exception as e:
            errs.append(f"{name}: {str(e)[:70]}"); continue
        if h:
            return name, [{"symbol": s, "weight": w} for s, w in h[:top_n]], errs
        errs.append(f"{name}: 보유종목 없음")
    return "없음", [], errs

# ── 실행 ──
res = {"etf": ETF, "missing": [], "n_fetched": 0}
try:
    want_per = METRICS in ("both", "per")
    want_pbr = METRICS in ("both", "pbr")
    start = (_dt.date.today() - _dt.timedelta(days=int(LOOKBACK_Y * 365.25) + 200)).isoformat()
    holdings_source, hold, src_errs = get_holdings(ETF, TOP_N)
    res["holdings_source"] = holdings_source
    res["n_holdings"] = len(hold)
    res["source_errors"] = src_errs
    per_map, pbr_map, weights = {}, {}, {}
    for h in hold:
        sym = h.get("symbol"); w = h.get("weight")
        if not sym or not isinstance(w, (int, float)):
            res["missing"].append(f"{sym}(비중없음)"); continue
        per, pbr, err = per_pbr(sym, start, want_per, want_pbr)
        res["n_fetched"] += 1
        got = False
        if want_per and per is not None: per_map[sym] = per; got = True
        if want_pbr and pbr is not None: pbr_map[sym] = pbr; got = True
        if got: weights[sym] = float(w)
        else:   res["missing"].append(f"{sym}({err or '데이터부족'})")
        if SEC_PAUSE: time.sleep(SEC_PAUSE)
    per_band, per_cov = agg_band(align_frame(per_map), weights)
    pbr_band, pbr_cov = agg_band(align_frame(pbr_map), weights)
    res["per"] = band_stats(per_band, per_cov)
    res["pbr"] = band_stats(pbr_band, pbr_cov)
    res["weight_sum_topN_pct"] = round(sum(weights.values()) * 100, 1)
except Exception as e:
    res["error"] = str(e)

_n = lambda x, nd=2: "—" if x is None else f"{x:,.{nd}f}"
L = ["=" * 60,
     f" [{ETF}] 역사적 PER/PBR 재구성 밴드 (접근 C · edgartools · SEC 실측 · [추정])",
     "=" * 60,
     "* 가정: 과거에도 '현재 비중' 고정 / 상위 N개만 / SEC 미제출 종목(해외·ADR 등) 제외 / Q4=FY−YTD 합성.",
     "* PER=가격/TTM-EPS(=TTM 순이익/주식수), PBR=가격/BVPS(=자기자본/주식수). 공시일(filed) 기준 PIT 정렬.",
     "* 퍼센타일↓ = 역사적 저평가(쌈).  (배당수익률 밴드와 방향 반대)"]

def _emit(label, st):
    if not st:
        L.append(f"■ {label}: 확인 불가(데이터 부족)"); return
    if st["coverage_now_pct"] < MIN_COVERAGE:
        L.append(f"■ {label}: 확인 불가(커버리지 {_n(st['coverage_now_pct'],1)}% < {MIN_COVERAGE}%)"); return
    L.append(f"■ {label}  (최근 {_n(st['lookback_years'],1)}년 · {st['n_points']}개월 · 기준일 {st['as_of']} · 현재 커버리지 {_n(st['coverage_now_pct'],1)}%)")
    L.append(f"  현재 / 평균 / 중위 : {_n(st['current'])}배 / {_n(st['avg'])}배 / {_n(st['median'])}배")
    L.append(f"  최저 / 최고        : {_n(st['min'])}배 / {_n(st['max'])}배")
    L.append(f"  현재 퍼센타일 / z  : {_n(st['percentile_pct'],0)}% / {_n(st['zscore'])}")

_emit("재구성 PER 밴드", res.get("per"))
_emit("재구성 PBR 밴드", res.get("pbr"))
L.append(f"■ 보유종목 소스: {res.get('holdings_source','—')}  (가져온 종목 {res.get('n_holdings',0)}개)")
L.append(f"■ 상위{TOP_N} 비중합(재구성 반영): {_n(res.get('weight_sum_topN_pct'),1)}%")
L.append(f"■ SEC facts 조회 종목 수: {res.get('n_fetched', 0)}개 (API 키·콜 한도 없음)")
if res.get("missing"):
    L.append("■ 제외된 종목 (재구성 미반영)")
    for m in res["missing"]: L.append(f"  - {m}")
if res.get("source_errors"):
    L.append("■ 보유종목 소스 폴백 로그")
    for se in res["source_errors"]: L.append(f"  - {se}")
if res.get("error"):
    L.append(f"■ 실행 오류: {res['error']}")
L.append("=" * 60)
print("\n".join(L))
```

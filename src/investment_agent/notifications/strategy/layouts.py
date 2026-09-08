"""전략별 embed 본문 구성.

전략마다 '결정의 모양'이 달라서 형식도 다르게 간다. 같은 틀을 6종에 씌우면
GEM처럼 1종목만 들고 있는 전략에 도넛이 원 하나로 그려지는 식으로 헛돈다.

  대결형      후보를 겨뤄 승자 독식        gem · adm
  순위+컷오프  줄 세워 기준 넘은 것만 편입   dmsr
  개별 판정형  자산마다 독립적으로 in/out   gtaa5
  2단계 게이트  경보 먼저, 통과해야 선택      haa_bal · haa_sim

각 빌더는 Layout(headline·subtext·fields)만 만든다. 제목·색·도넛·변화·푸터 같은
공통 껍데기는 embeds.py가 씌운다. signals 형식이 어긋나면 embeds.py가 generic으로
떨어뜨리므로 여기서는 방어 코드를 두지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from investment_agent.notifications.renderers.text import table as _table
from .format import mom, pct, ticker_label


@dataclass(frozen=True)
class Layout:
    headline: str                       # 결론 한 줄. ### 로 크게 낸다
    subtext: str = ""                   # 규칙 설명. -# 로 작고 흐리게. 줄바꿈으로 끊는다
    note: str = ""                      # 지표 정의 같은 부연. 푸터로 내린다
    fields: list[dict] = field(default_factory=list)


def _holding_headline(alloc: dict[str, float]) -> str:
    """단일 보유 전략의 결론 문장."""
    ticker, weight = max(alloc.items(), key=lambda kv: kv[1])
    return f"{ticker_label(ticker)} {pct(weight)}"


# ── 대결형 ────────────────────────────────────────────────────────────
def duel_gem(signals: dict, alloc: dict[str, float]) -> Layout:
    """GEM — 미국·해외를 1년 수익률로 겨루고, 단기채가 바닥선이다."""
    contenders = sorted(
        [("SPY", signals["spy_12m"]), ("EFA", signals["efa_12m"])],
        key=lambda kv: -kv[1],
    )
    baseline = signals["bil_12m"]
    names = ["승자", "2위"]
    fields = [
        {
            "name": f"{names[i]} · {ticker}",
            "value": f"{ticker_label(ticker)}\n`{pct(value)}`",
            "inline": True,
        }
        for i, (ticker, value) in enumerate(contenders)
    ]
    fields.append({
        "name": "기준선 · BIL",
        "value": f"{ticker_label('BIL')}\n`{pct(baseline)}`",
        "inline": True,
    })
    return Layout(
        headline=_holding_headline(alloc),
        subtext="미국 vs 해외 vs 현금 중 1년 수익률 승자에 전액",
        fields=fields,
    )


def duel_adm(signals: dict, alloc: dict[str, float]) -> Layout:
    """ADM — 미국 대형주와 선진국 소형주의 모멘텀 2파전."""
    contenders = sorted(
        [("SPY", signals["spy_score"]), ("SCZ", signals["scz_score"])],
        key=lambda kv: -kv[1],
    )
    names = ["승자", "2위"]
    return Layout(
        headline=_holding_headline(alloc),
        subtext="미국 대형 vs 해외 소형 모멘텀 승자 100%\n둘 다 음수면 장기채로 도피",
        note="모멘텀 = 최근 1·3·6개월 수익률 평균(%p)",
        fields=[
            {
                "name": f"{names[i]} · {ticker}",
                "value": f"{ticker_label(ticker)}\n`{mom(value)}`",
                "inline": True,
            }
            for i, (ticker, value) in enumerate(contenders)
        ],
    )


# ── 순위 + 컷오프형 ───────────────────────────────────────────────────
def ranked_dmsr(signals: dict, alloc: dict[str, float]) -> Layout:
    """DMSR — 11개 산업을 줄 세워 단기채 수익률을 넘긴 것만 편입한다."""
    cutoff = signals["bil_12m"]
    top = signals["top4"]
    passed = [row for row in top if row["mom12"] > cutoff]

    rows = [
        (str(rank), row["ticker"], ticker_label(row["ticker"]), pct(row["mom12"]))
        for rank, row in enumerate(top, start=1)
    ]
    table = _table(rows)
    # 컷오프 선을 표 안에 그어 '어디서 잘렸는지'를 보이게 한다. 선과 문구는 줄을 나눈다.
    marker = f"{'─' * 22}\n컷오프 BIL {pct(cutoff)}"
    table = table.replace("\n```", f"\n{marker}\n```")

    return Layout(
        headline=(
            "상위 4개 전부 편입" if len(passed) == len(top)
            else f"상위 4개 중 {len(passed)}개만 편입"
        ),
        subtext="미국 11개 산업 중 1년 수익률 상위 4개\n단기채를 넘긴 것만 25%씩",
        fields=[{"name": "산업 순위", "value": table}],
    )


# ── 개별 판정형 ───────────────────────────────────────────────────────
def inout_gtaa5(signals: dict, alloc: dict[str, float]) -> Layout:
    """GTAA-5 — 자산마다 10개월 평균선 위/아래를 따로 판정한다."""
    assets = {k: v for k, v in signals.items() if isinstance(v, dict)}

    def gap(v: dict) -> float:
        sma = v.get("sma10") or 0
        return (v["last"] / sma - 1) if sma else 0.0

    inside = sorted(
        ((t, gap(v)) for t, v in assets.items() if v.get("inMarket")),
        key=lambda kv: -kv[1],
    )
    outside = sorted(
        ((t, gap(v)) for t, v in assets.items() if not v.get("inMarket")),
        key=lambda kv: -kv[1],
    )

    def lines(items: list[tuple[str, float]]) -> str:
        return "\n".join(
            f"**{t}** {ticker_label(t)} `{pct(g)}`" for t, g in items
        ) or "없음"

    fields = [{"name": f"편입 {len(inside)}", "value": lines(inside), "inline": True}]
    if outside:
        fields.append({
            "name": f"제외 {len(outside)} → 단기채",
            "value": lines(outside),
            "inline": True,
        })

    return Layout(
        headline=f"{len(assets)}개 중 {len(inside)}개 추세 양호",
        subtext="10개월 평균선 위면 20%씩\n아래면 그 몫만 단기채로",
        fields=fields,
    )


# ── 2단계 게이트형 ────────────────────────────────────────────────────
def _canary(signals: dict) -> tuple[bool, str]:
    """물가채(TIP) 모멘텀이 0 위면 공격, 아래면 방어."""
    score = signals["tip_13612w"]
    on = score > 0
    state = "0 위라 위험자산 편입" if on else "0 아래라 방어자산으로 전환"
    return on, f"물가채(TIP) 모멘텀 `{mom(score)}` → {state}"


def gate_haa_bal(signals: dict, alloc: dict[str, float]) -> Layout:
    """HAA-Bal — 카나리아 통과 시 8자산 중 상위 4개를 25%씩."""
    on, gate = _canary(signals)
    top = signals["top4"]
    negative = [row for row in top if row["score"] <= 0]

    table = _table([
        (row["ticker"], ticker_label(row["ticker"]), mom(row["score"]))
        for row in top
    ])
    name = "8자산 중 상위 4개 · 25%씩"
    if negative:
        name += f" (음수 {len(negative)}개는 방어 대체)"

    return Layout(
        headline="안전 신호 · 공격 모드" if on else "위험 신호 · 방어 모드",
        subtext=gate,
        note="모멘텀 = 1·3·6·12개월 수익률 평균(%p)",
        fields=[{"name": name, "value": table}],
    )


def gate_haa_sim(signals: dict, alloc: dict[str, float]) -> Layout:
    """HAA-Sim — 카나리아 통과 시 4자산 1등에 전액."""
    on, gate = _canary(signals)
    top = signals["top1"]
    ticker, score = top["ticker"], top["score"]
    won = score > 0

    return Layout(
        headline="안전 신호 · 공격 모드" if on else "위험 신호 · 방어 모드",
        subtext=gate,
        note="모멘텀 = 1·3·6·12개월 수익률 평균(%p)",
        fields=[{
            "name": "4자산 1등" + ("" if won else " (음수 → 방어자산으로)"),
            "value": f"**{ticker}** {ticker_label(ticker)} `{mom(score)}`",
        }],
    )


BUILDERS = {
    "gem": duel_gem,
    "adm": duel_adm,
    "dmsr": ranked_dmsr,
    "gtaa5": inout_gtaa5,
    "haa_bal": gate_haa_bal,
    "haa_sim": gate_haa_sim,
}

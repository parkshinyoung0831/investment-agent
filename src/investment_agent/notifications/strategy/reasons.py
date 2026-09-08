"""Render strategy signals into human-readable decision reasons."""
from __future__ import annotations

import re
from typing import Callable

from .format import mom, pct, ticker_label, ticker_text


def _r_gem(signals: dict) -> str:
    if signals["spy_12m"] < signals["bil_12m"]:
        return f"📉 {ticker_text('SPY')} 1년 {pct(signals['spy_12m'])} < 단기채 {pct(signals['bil_12m'])}\n→ 위험 회피, 종합채권으로"
    if signals["spy_12m"] >= signals["efa_12m"]:
        return f"🇺🇸 {ticker_text('SPY')} 1년 {pct(signals['spy_12m'])} ≥ {ticker_text('EFA')} {pct(signals['efa_12m'])}\n→ 미국 100%"
    return f"🌏 {ticker_text('EFA')} 1년 {pct(signals['efa_12m'])} > {ticker_text('SPY')} {pct(signals['spy_12m'])}\n→ 해외 100%"


def _r_adm(signals: dict) -> str:
    spy, scz = signals["spy_score"], signals["scz_score"]
    win, lose = (
        (ticker_text("SPY"), spy),
        (ticker_text("SCZ"), scz),
    ) if spy >= scz else (
        (ticker_text("SCZ"), scz),
        (ticker_text("SPY"), spy),
    )
    note = "\n_모멘텀 = 최근 1·3·6개월 수익률 평균 (%p)_"
    if win[1] <= 0:
        return f"📉 둘 다 모멘텀 음수 (SPY {mom(spy)} · SCZ {mom(scz)})\n→ 장기채로 도피{note}"
    return f"🏆 {win[0]} 모멘텀 {mom(win[1])} > {lose[0]} {mom(lose[1])}\n→ 승자 100%{note}"


def _r_dmsr(signals: dict) -> str:
    passed = len([x for x in signals["top4"] if x["mom12"] > signals["bil_12m"]])
    lst = ", ".join(
        f"{ticker_label(x['ticker'])} {pct(x['mom12'])}"
        for x in signals["top4"]
    )
    return f"🏅 {lst}\n🎯 단기채 {pct(signals['bil_12m'])} 수익률 넘긴 {passed}개만 편입 · 나머지는 종합채권"


def _r_gtaa5(signals: dict) -> str:
    assets = {k: v for k, v in signals.items() if isinstance(v, dict)}

    def _gap(v: dict) -> float:
        sma = v.get("sma10") or 0
        return (v.get("last", 0) / sma - 1) if sma else 0.0

    inn = [
        f"{ticker_label(k)} {_gap(v) * 100:+.1f}%"
        for k, v in assets.items()
        if v.get("inMarket")
    ]
    out = [
        f"{ticker_label(k)} {_gap(v) * 100:+.1f}%"
        for k, v in assets.items()
        if not v.get("inMarket")
    ]
    reason = f"📈 추세 양호 (10개월 평균선 대비): {', '.join(inn) or '없음'}"
    if out:
        reason += f"\n📉 추세 약함 → 단기채로 대체: {', '.join(out)}"
    return reason


_HAA_NOTE = "\n_모멘텀 = 1·3·6·12개월 수익률 평균 (%p)_"


def _haa_canary_off(signals: dict) -> str:
    return f"🐦 위험 신호 감지 (물가채 TIP 모멘텀 {mom(signals['tip_13612w'])}) → 방어자산으로 도망{_HAA_NOTE}"


def _r_haa_bal(signals: dict) -> str:
    if signals["tip_13612w"] <= 0:
        return _haa_canary_off(signals)
    neg = len([x for x in signals["top4"] if x["score"] <= 0])
    top = ", ".join(
        f"{ticker_text(x['ticker'])} {mom(x['score'])}"
        for x in signals["top4"]
    )
    reason = f"🐦 안전 신호 (TIP {mom(signals['tip_13612w'])}) · 8자산 Top-4: {top}"
    if neg:
        reason += f" (이 중 {neg}개 음수→방어 대체)"
    return reason + _HAA_NOTE


def _r_haa_sim(signals: dict) -> str:
    if signals["tip_13612w"] <= 0:
        return _haa_canary_off(signals)
    top = signals["top1"]
    if top["score"] <= 0:
        return f"🐦 안전 신호 (TIP {mom(signals['tip_13612w'])}) · 🥇 {ticker_text(top['ticker'])} 모멘텀 {mom(top['score'])} 1등이나 음수 → 방어자산으로{_HAA_NOTE}"
    return f"🐦 안전 신호 (TIP {mom(signals['tip_13612w'])}) · 🥇 {ticker_text(top['ticker'])} 모멘텀 {mom(top['score'])} 1등 → 100%{_HAA_NOTE}"


RENDERERS: dict[str, Callable[[dict], str]] = {
    "gem": _r_gem,
    "adm": _r_adm,
    "dmsr": _r_dmsr,
    "gtaa5": _r_gtaa5,
    "haa_bal": _r_haa_bal,
    "haa_sim": _r_haa_sim,
}


def _signal_text(value: object) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, list):
        lines = [str(x).strip() for x in value if str(x).strip()]
        return "\n".join(lines) if lines else None
    return None


def _generic_reason(signals: dict) -> str:
    for key in ("reason", "reason_ko", "reason_lines", "summary"):
        if text := _signal_text(signals.get(key)):
            return text
    return "_계산 근거 요약 없음_"


def render_reason(strategy_id: str, signals: dict) -> str:
    try:
        renderer = RENDERERS.get(strategy_id)
        reason = renderer(signals) if (signals and renderer) else _generic_reason(signals)
    except (KeyError, IndexError, TypeError, ValueError):
        reason = "_근거 계산 실패 (시그널 형식 확인)_"
    return re.sub(r"^[^\w\s]+\s*", "", reason)

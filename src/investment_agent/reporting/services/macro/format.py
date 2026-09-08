"""표시(presentation) 전담 — 숫자·문구를 카드에 보여줄 형태로 꾸민다.

판정(eval_row·임계)은 thresholds.py, 정적 설정(라벨·색)은 constants.py.
이 파일은 '어떻게 보여줄까'만 담당한다 (값을 판단하지 않는다).

- short_of / badge_for / color_for : 등급(tier) → 짧은 키·배지·색
- fmt_val / fmt_change             : 값·변화량 문자열
- meta_tags                        : 카드 보조 태그(z·레벨z·백분위·MA·고저)
- base_card / tier_badge / code_map: core·watch 공통 카드 조립
- fng_label / fng_color            : 공포·탐욕 지수 표시
"""
from __future__ import annotations
from typing import Any

import markupsafe

from investment_agent.reporting.services.macro.constants import (
    BADGE_LABEL, DEFAULT_COLOR, INVERSE_SERIES, LEVEL_COLOR, MA200_TAG,
    SPARK_DOWN, SPARK_UP,
)
from investment_agent.reporting.services.macro.palette import ALERT, CAUTION, MUTED, ON_DARK, WATCH

# bp(베이시스포인트)로 변화량을 표기할 series_kind — 금리·스프레드는 % 가 아니라 bp 가 표준.
_BP_KINDS = {"rate", "spread"}
# 스프레드 역전 시 변화량 대신 보여줄 경고 문구.
_INVERSION_SIDS = {"SPREAD_10Y2Y", "SPREAD_10Y3M"}
# 올라가는 것이 나쁜 지표의 등락 색만 뒤집는다. 숫자는 그대로 둔다.
_FLIP_DIR = {"up": "down", "down": "up", "flat": "flat"}


# ── 등급(tier) → 표시 요소 ──────────────────────────────────────────────
def short_of(tier) -> str:
    """전체 등급 문자열("🔴 alert")에서 짧은 키("alert")만 뽑는다. 없으면 ""."""
    return tier.split(" ", 1)[1] if tier else ""


def badge_for(tier) -> str:
    """등급 → 카드 배지 라벨("🔴 ALERT"). 등급 없으면 ""."""
    return BADGE_LABEL.get(short_of(tier), "")


def color_for(tier) -> str:
    """등급 → 카드 왼쪽 띠 색. 등급 없으면 기본색."""
    return LEVEL_COLOR.get(short_of(tier) or None, DEFAULT_COLOR)


# ── 값·변화량 ────────────────────────────────────────────────────────────
def fmt_val(v, sid: str, unit) -> str:
    if v is None:
        return "—"
    v = float(v)
    if sid == "USDKRW":
        return f"{v:,.0f}"
    if sid == "JPYKRW":
        return f"{v:,.2f}"
    if sid in ("DXY", "FEAR_GREED", "VIX"):
        return f"{v:.1f}"
    if unit == "%":
        return f"{v:.2f}%"
    if unit == "$":
        if v >= 1000:
            return f"${v:,.0f}"
        if v >= 100:
            return f"${v:.1f}"
        return f"${v:.2f}"
    if v >= 1000:
        return f"{v:,.0f}"
    if v >= 100:
        return f"{v:.1f}"
    return f"{v:.2f}"


def _change_parts(curr, prev, sid: str, kind: str | None, unit: str | None):
    """변화량 문구와 값의 부호 방향(up/down/flat)을 돌려준다.

    자를 세 개 쓴다.
      금리·스프레드(kind in _BP_KINDS)          bp
      그 밖에 값 자체가 %인 지표(unit == "%")   %p
      나머지                                    상대 %

    가운데가 왜 필요한가: 실업률이 4.10 -> 4.20으로 오른 것을 상대 %로 쓰면 "+2.44%"가
    되는데, 실업률이 2.44% 오른 게 아니라 0.10%p 오른 것이다. GDP(QoQ)는 더 심해서
    1.50 -> 3.80이 "+153%"로 찍힌다. 값이 이미 비율인 지표는 차이도 비율로 읽어야 한다.
    """
    if curr is None or prev is None:
        return ("", "flat")
    if kind in _BP_KINDS:
        if sid in _INVERSION_SIDS and float(curr) <= 0:
            return ("역전·침체", "down")
        bp = (float(curr) - float(prev)) * 100
        d = "up" if bp > 0 else "down" if bp < 0 else "flat"
        return (f"{bp:+.0f}bp", d)
    if unit == "%":
        pp = float(curr) - float(prev)
        d = "up" if pp > 0 else "down" if pp < 0 else "flat"
        return (f"{pp:+.2f}%p", d)
    if float(prev) == 0:
        return ("", "flat")
    pct = (float(curr) - float(prev)) / abs(float(prev)) * 100
    d = "up" if pct > 0 else "down" if pct < 0 else "flat"
    return (f"{pct:+.2f}%", d)


def fmt_change(curr, prev, sid: str, kind: str | None = None, unit: str | None = None):
    """변화량 문구와 표시 방향을 돌려준다.

    VIX·MOVE처럼 올라가는 것이 나쁜 지표는 방향만 뒤집어 상승을 하락색으로 칠한다.
    문구는 건드리지 않는다 — 대시보드의 ``delta_color="inverse"``와 같은 규칙이다.
    """
    text, direction = _change_parts(curr, prev, sid, kind, unit)
    return (text, _FLIP_DIR[direction] if sid in INVERSE_SERIES else direction)


# ── 카드 보조 태그 ───────────────────────────────────────────────────────
def meta_tags(r: dict[str, Any]) -> list[str]:
    """카드에 붙일 작은 보조 표시 (튀는 정도·레벨·평균선·고점/저점 대비)."""
    out: list[str] = []
    metrics = r.get("metrics") or {}
    curr = r.get("curr")
    sid = r.get("series_id") or ""

    z = metrics.get("z")
    if z is not None and abs(float(z)) >= 1:
        out.append(f"z={float(z):+.1f}σ")

    # 레벨 z·역사 백분위 — 밸류에이션·비율·플로우 카드의 보조 표시.
    lz = metrics.get("level_z")
    if lz is not None and abs(float(lz)) >= 1:
        out.append(f"레벨z={float(lz):+.1f}σ")

    pctl = metrics.get("percentile")
    if pctl is not None and (float(pctl) >= 80 or float(pctl) <= 20):
        out.append(f"역사 백분위 {float(pctl):.0f}%")

    ma200 = metrics.get("ma200")
    if curr is not None and ma200 not in (None, 0) and sid in MA200_TAG:
        m = (float(curr) / float(ma200) - 1) * 100
        if abs(m) >= 3:
            out.append(f"200DMA {m:+.0f}%")

    dd = metrics.get("drawdown")
    if dd is not None and float(dd) <= -5:
        out.append(f"52w고점 {float(dd):.0f}%")

    rb = metrics.get("rebound")
    if rb is not None and float(rb) >= 5:
        out.append(f"저점 +{float(rb):.0f}%")

    return out


# ── 스파크라인 (카드 미니 추세차트) ──────────────────────────────────────
def make_spark(vals, w: int = 240, h: int = 36, pad: int = 3):
    """최근값 리스트 → 인라인 SVG 스파크라인(브랜드 블루 단색).

    카드 폭에 꽉 차도록 width=100% + preserveAspectRatio=none (양끝이 카드 좌우에 정확히 붙음).
    값이 2개 미만이면 빈 문자열. 반환은 Markup이라 Jinja autoescape에 안 걸린다.
    """
    vals = [float(v) for v in (vals or []) if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    xs = [i / (n - 1) * w for i in range(n)]
    ys = [pad + (h - 2 * pad) * (1 - (v - lo) / rng) for v in vals]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"0,{h} {pts} {w},{h}"
    color = SPARK_UP if vals[-1] >= vals[0] else SPARK_DOWN
    gid = f"sp{abs(hash(tuple(vals))) % 10**7}"
    svg = (
        f'<svg class="spark" width="100%" height="{h}" viewBox="0 0 {w} {h}" '
        f'preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{color}" stop-opacity="0.20"/>'
        f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
        f'<polygon points="{area}" fill="url(#{gid})"/>'
        f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6" '
        f'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>'
    )
    return markupsafe.Markup(svg)


# ── 카드 조립 (core·watch 공통) ──────────────────────────────────────────
def base_card(r: dict[str, Any]) -> dict[str, Any]:
    """모든 매크로 카드가 공유하는 기본 필드 (이름·코드·값·변화·보조태그·스파크라인).

    호출 측은 여기에 등급 배지(tier_badge)나 사유·국가 등 화면별 필드를 덧붙인다.
    """
    sid = r.get("series_id") or ""
    chg_text, chg_dir = fmt_change(
        r.get("curr"), r.get("prev_value"), sid, r.get("series_kind"), r.get("unit"),
    )
    freshness = r.get("freshness") or {}
    freshness_state = str(freshness.get("state") or "")
    obs_date = freshness.get("obs_date")
    age_days = freshness.get("age_days")
    if freshness_state == "missing":
        as_of = "기준일 없음"
    elif obs_date:
        as_of = f"기준 {obs_date}"
        if freshness_state == "stale" and age_days is not None:
            as_of += f" · {age_days}일 지연"
    else:
        as_of = ""
    return {
        "name": r.get("name_ko") or sid,
        "series_id": sid,
        "value": fmt_val(r.get("curr"), sid, r.get("unit")),
        "change": chg_text,
        "dir": chg_dir,
        "meta": " · ".join(meta_tags(r)),
        "spark": make_spark(r.get("spark")),
        "as_of": as_of,
        "freshness": freshness_state,
        # 한국 시장 지표 태그. 표시용 약식 판정.
        "kr": sid.startswith("KR_"),
    }


def tier_badge(tier) -> dict[str, str]:
    """등급(tier) → 카드 배지 3종 (짧은 키·배지 라벨·왼쪽 띠 색)."""
    return {"level": short_of(tier), "badge": badge_for(tier), "color": color_for(tier)}


def code_map(rows: list[dict[str, Any]]) -> str:
    """카드 푸터의 '이름 코드' 범례 문자열. 행 순서대로 나열한다."""
    return " · ".join(f'{r.get("name_ko") or r["series_id"]} {r["series_id"]}' for r in rows)


# ── 공포·탐욕 지수 표시 보조 ─────────────────────────────────────────────
def fng_label(v: float) -> str:
    v = float(v)
    if v <= 24: return "극단공포"
    if v <= 44: return "공포"
    if v <= 54: return "중립"
    if v <= 74: return "탐욕"
    return "극단탐욕"


def fng_color(v: float) -> str:
    v = float(v)
    if v <= 10 or v >= 90:
        return ALERT
    if v <= 24 or v >= 75:
        return CAUTION
    if v <= 44:
        return WATCH
    if v <= 54:
        return MUTED
    return ON_DARK

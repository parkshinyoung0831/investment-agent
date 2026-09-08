"""8-K 실적 속보 Discord Embed 빌더."""
from __future__ import annotations

from typing import Any

from investment_agent.notifications.earnings_flash.quickchart import flash_performance_chart_url
from investment_agent.reporting.services.earnings.guidance import format_guidance_headline

# 색상 토큰 (DESIGN-system.md)
COLOR_BEAT = 0x00C087    # 그린 (서프라이즈/예상 상회)
COLOR_MISS = 0xFF3B30    # 레드 (어닝 쇼크/예상 하회)
COLOR_INLINE = 0x3182F6  # 토스 블루 (부합/중립)


def format_money(val: float | None) -> str:
    if val is None:
        return "—"
    if abs(val) >= 1e9:
        return f"${val / 1e9:.2f}B"
    if abs(val) >= 1e6:
        return f"${val / 1e6:.2f}M"
    return f"${val:,.2f}"


def format_eps(val: float | None) -> str:
    if val is None:
        return "—"
    return f"${val:.2f}"


def compute_surprise(actual: float | None, estimate: float | None) -> float | None:
    """실제값과 예상값으로부터 서프라이즈 비율(%)을 동적으로 계산한다."""
    if actual is not None and estimate is not None and estimate != 0:
        return round(((actual - estimate) / abs(estimate)) * 100.0, 2)
    return None


def build_flash_embed(item: dict[str, Any]) -> dict[str, Any]:
    """8-K 실적 속보용 Discord Rich Embed 딕셔너리를 생성한다."""
    flash = item["flash"]
    names = item.get("names") or {}
    ticker = flash["ticker"]
    name_ko = names.get("name_ko")
    name_en = names.get("name")
    display_name = name_ko or name_en or ticker
    title_en = f" ({name_en})" if name_en and name_en != display_name else ""

    fy = flash.get("fiscal_year")
    fp = flash.get("fiscal_period")
    period_label = f"FY{fy} {fp}" if fy and fp else "최신 분기"

    eps_act = flash.get("eps_actual")
    eps_est = flash.get("eps_estimate")
    surp_eps = flash.get("surprise_eps_pct") or compute_surprise(eps_act, eps_est)

    rev_act = flash.get("revenue_actual")
    rev_est = flash.get("revenue_estimate")
    surp_rev = flash.get("surprise_revenue_pct") or compute_surprise(rev_act, rev_est)

    # 서프라이즈 판정
    is_beat = (surp_eps is not None and surp_eps > 0.0) or (surp_rev is not None and surp_rev > 0.0)
    is_miss = (surp_eps is not None and surp_eps < -1.0) or (surp_rev is not None and surp_rev < -1.0)

    if is_beat:
        color = COLOR_BEAT
        badge_text = "🟢 어닝 서프라이즈 (예상 상회)"
    elif is_miss:
        color = COLOR_MISS
        badge_text = "🔴 예상 하회"
    else:
        color = COLOR_INLINE
        badge_text = "🔵 실적 발표 완료"

    title = f"⚡ [실적 속보] {display_name}{title_en} · {period_label}"

    fields = []

    # 1. EPS 필드
    if eps_act is not None or eps_est is not None:
        act_str = format_eps(eps_act)
        est_str = format_eps(eps_est)
        surp_str = f" (`{surp_eps:+.1f}%`)" if surp_eps is not None else ""
        fields.append({
            "name": "주당순이익 (EPS)",
            "value": f"**실제 {act_str}** vs 예상 {est_str}{surp_str}",
            "inline": True,
        })

    # 2. 매출 필드 (있을 경우)
    if rev_act is not None or rev_est is not None:
        act_str = format_money(rev_act)
        est_str = format_money(rev_est)
        surp_str = f" (`{surp_rev:+.1f}%`)" if surp_rev is not None else ""
        fields.append({
            "name": "매출액 (Revenue)",
            "value": f"**실제 {act_str}** vs 예상 {est_str}{surp_str}",
            "inline": True,
        })

    # 3. 손익 요약 (보도자료 표가 제공할 때만 표시)
    operating_income = flash.get("operating_income_actual")
    net_income = flash.get("net_income_actual")
    if operating_income is not None:
        fields.append({
            "name": "영업이익 (Operating Income)",
            "value": f"**실제 {format_money(operating_income)}**",
            "inline": True,
        })
    if net_income is not None:
        fields.append({
            "name": "순이익 (Net Income)",
            "value": f"**실제 {format_money(net_income)}**",
            "inline": True,
        })

    # 4. 가이던스 (있을 경우 깔끔한 1줄 요약)
    guidance_clean = format_guidance_headline(flash.get("guidance_summary"))
    if guidance_clean:
        fields.append({
            "name": "가이던스 (Guidance)",
            "value": f"**{guidance_clean}**",
            "inline": False,
        })

    # 5. 공시 및 원문 링크
    filed_at = flash.get("filed_at") or ""
    press_url = flash.get("press_release_url")
    link_md = f"[SEC 8-K 공시 원문 보기]({press_url})" if press_url else "SEC 8-K 접수"
    fields.append({
        "name": "공시 정보",
        "value": f"접수일: `{filed_at}` · {link_md}",
        "inline": False,
    })

    embed = {
        "title": title,
        "description": f"**{badge_text}**",
        "color": color,
        "fields": fields,
        "footer": {
            "text": "ℹ️ 13분기 추세·현금흐름·배당 분석 정밀 카드는 정식 10-Q 공시 후 발송됩니다.",
        },
    }

    # 비교 그래프(QuickChart 이미지) 부착
    chart_url = flash_performance_chart_url(flash)
    if chart_url:
        embed["image"] = {"url": chart_url}

    return embed

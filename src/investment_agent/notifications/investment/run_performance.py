"""실계좌·모의계좌 성과와 별도 가상 판단 결과를 알림 엔진에 전달한다."""
from __future__ import annotations

from investment_agent.config import load_config
from investment_agent.notifications.context import default_context
from investment_agent.notifications.engine import Notice, Rendered, fact_time, publish
from investment_agent.notifications.subscriptions import discord_target
from investment_agent.notifications.topics import topic
from investment_agent.reporting.notifications.investment.performance import performance_reports

QUALITY_LABELS = {
    "allocated_order_fees": "주문 누적 수수료·세금을 체결 수량에 비례 배분",
    "fees_unknown": "수수료 또는 세금 미확인",
    "opening_cost_basis_unknown": "청산한 초기 보유분의 원가 미확인",
    "position_cost_basis_unknown": "보유 원가 미확인",
    "position_mark_unknown": "보유분 평가 가격 미확인",
    "cashflow_history_incomplete": "입출금 내역의 완전성 미확인",
    "insufficient_nav_history": "비교할 계좌 평가점 부족",
    "nav_currency_unknown_or_mixed": "계좌 평가 통화 미확인",
    "cashflow_currency_unknown_or_mixed": "입출금 통화 미확인",
    "cashflow_valuation_missing": "입출금 직전·직후 계좌 평가점 부족",
    "opening_inventory_unverified": "초기 보유 수량 미검증 · 기록된 체결 기준",
    "unattributed_fills": "계좌에 연결하지 못한 체결 존재",
    "position_reconciliation_unavailable": "보유 수량 대사 자료 없음",
    "position_quantity_mismatch": "원장과 계좌 보유 수량 불일치",
    "fill_identity_or_currency_unknown": "체결 종목 또는 통화 미확인",
    "realized_cost_or_fees_unknown": "청산 원가 또는 비용 미확인",
    "observed_fill_time_and_allocated_order_fees": "체결 관측 시각 기준 · 주문 비용은 수량 비례 배분",
}

def notices(reports):
    return [Notice(subject=f"{row['execution_mode']}:{row['broker_account_hash'][:12]}",
                   occurrence=f"{row['report_kind']}:{row['occurrence']}", fact_at=fact_time(row["as_of_at"]),
                   basis={"report_id": row["report_id"]}, data=row) for row in reports]


def _amount(value, currency):
    return "미확인" if value is None else f"{value:+,.2f} {currency}"


def _percent(value):
    return "미확인" if value is None else f"{value * 100:+.2f}%"


def render(batch):
    row = batch[0].data
    currency = row["currency"]
    label = "실계좌" if row["execution_mode"] == "live" else "모의계좌"
    if row["report_kind"] == "recommendation":
        label = "원본 판단"
        fields = [dict(name="실제 매수 여부와 무관한 가상 성과", value="\n".join(
            f"{item['horizon_days']}일 · {item['count']}건 · 평균 {_percent(item['mean_net_reward'])}"
            for item in row['recommendation']['horizons'])),
            dict(name="평가 기준", value="당시 판단을 보존하고 확정된 이후 가격과 가정한 거래비용으로 평가합니다. 실제 계좌 수익률이 아닙니다.")]
    elif row["report_kind"] == "realized":
        result = row["realization"]
        fields = [dict(name="청산 체결", value=f"{result['ticker']} · {result['quantity']:g}주"),
                  dict(name="기록된 체결 손익 · 비용 반영", value=_amount(result["net_pnl"], currency))]
    else:
        accounting, nav = row["accounting"], row["nav"]
        fields = [dict(name="기록된 체결 손익 · 비용 반영", value=_amount(accounting["realized_pnl"], currency)),
                  dict(name="미실현손익", value=_amount(accounting["unrealized_pnl"], currency)),
                  dict(name="최근 평가 구간 수익률 · 시간가중", value=_percent(nav["daily_return"])),
                  dict(name="관측 기간 누적 수익률", value=_percent(nav["cumulative_return"]))]
        horizons = row.get("recommendation", {}).get("horizons", [])
        text = "\n".join(f"{item['horizon_days']}일 · {item['count']}건 · 평균 {_percent(item['mean_net_reward'])}" for item in horizons)
        fields.append(dict(name="당시 판단의 가상 성과 · 계좌 수익률과 별개", value=text or "평가가 끝난 판단 자료가 없어요."))
    if row["quality_issues"]:
        fields.append(dict(name="집계 범위", value="자료가 부족한 값은 미확인이에요.\n" + ", ".join(QUALITY_LABELS.get(issue, "추가 원천 검증 필요") for issue in row["quality_issues"])[:800]))
    return Rendered({"embeds": [dict(title=f"{label} {'청산' if row['report_kind'] == 'realized' else '일일'} 성과",
                                    fields=fields, footer=dict(text=f"관측 시각 {row['as_of_at']} · {currency}"))]})


def run(*, target=None, context=None):
    reports = performance_reports()
    if not reports:
        return 0
    declaration = topic("ai.performance")
    config = load_config()
    result = publish(declaration, notices(reports), render, context=context or default_context(config),
                     target=discord_target(declaration.channel_kind, config=config, override=target))
    return result.delivered

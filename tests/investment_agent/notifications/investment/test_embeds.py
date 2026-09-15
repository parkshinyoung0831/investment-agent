"""자동매매 보고서 embed 조립 — 순수 함수라 DB·네트워크 없이 검증한다."""
from __future__ import annotations

import unittest

from investment_agent.notifications.investment import embeds
from investment_agent.notifications.investment.palette import COLOR_APPROVED, COLOR_INFO, COLOR_REJECTED


def _proposal(**overrides):
    row = {
        "proposal_id": "proposal_abc",
        "run_id": "run_abc",
        "as_of_at": "2026-09-03T00:00:00+00:00",
        "source_type": "optimizer",
        "source_version": "tradingagents-optimizer-portfolio-v2",
        "weights": {"AAPL": 0.06, "MSFT": 0.04, "CASH": 0.90},
        "confidence": 0.62,
        "reasoning": ["기술 섹터 비중 확대", "현금 비중 유지"],
        "case_keys": ["case_a", "case_b"],
        "metadata": {"coverage": "partial_universe"},
    }
    row.update(overrides)
    return row


def _risk(**overrides):
    row = {
        "risk_decision_id": "risk_abc",
        "is_approved": True,
        "violations": [],
        "metrics": {"portfolio_volatility": 0.14, "portfolio_beta": 0.92, "turnover": 0.10},
        "decided_at": "2026-09-03T00:05:00+00:00",
    }
    row.update(overrides)
    return row


def _run(**overrides):
    row = {
        "run_id": "run_abc",
        "status": "partial",
        "candidate_tickers": ["AAPL", "MSFT", "NVDA"],
        "failure_reason": None,
    }
    row.update(overrides)
    return row


def _decision(**overrides):
    row = {
        "case_key": "case_a",
        "ticker": "AAPL",
        "as_of_at": "2026-09-03T00:00:00+00:00",
        "status": "completed",
        "final_decision": {
            "signal": "open",
            "probability_up": 0.61,
            "confidence": 0.72,
            "expected_excess_return": 0.031,
            "target_weight": 0.06,
            "reasoning": ["서비스 마진 개선", "밸류에이션 부담은 낮음"],
            "evidence_ids": ["EV-MARKET-1", "EV-FUND-2"],
            "missing_data": [],
        },
    }
    row.update(overrides)
    return row


def _flatten(embed):
    parts = [str(embed.get("title", "")), str(embed.get("description", ""))]
    parts += [f"{field['name']} {field['value']}" for field in embed["fields"]]
    parts.append(str(embed.get("footer", {}).get("text", "")))
    return " ".join(parts)


class PortfolioEmbedTest(unittest.TestCase):
    def test_approved_portfolio_is_green_and_names_the_holdings(self):
        embed = embeds.portfolio_embed(proposal=_proposal(), risk=_risk(), run=_run())

        self.assertEqual(embed["color"], COLOR_APPROVED)
        text = _flatten(embed)
        self.assertIn("AAPL", text)
        self.assertIn("MSFT", text)

    def test_rejected_portfolio_is_red_and_lists_every_violation(self):
        risk = _risk(
            is_approved=False,
            violations=["portfolio beta exceeds the absolute limit", "turnover above policy"],
        )

        embed = embeds.portfolio_embed(proposal=_proposal(), risk=risk, run=_run())

        self.assertEqual(embed["color"], COLOR_REJECTED)
        text = _flatten(embed)
        self.assertIn("beta exceeds", text)
        self.assertIn("turnover above policy", text)

    def test_cash_weight_is_shown_separately_from_the_holdings(self):
        embed = embeds.portfolio_embed(proposal=_proposal(), risk=_risk(), run=_run())

        self.assertIn("90.0%", _flatten(embed))

    def test_candidate_scope_and_run_status_are_surfaced(self):
        embed = embeds.portfolio_embed(proposal=_proposal(), risk=_risk(), run=_run())

        text = _flatten(embed)
        self.assertIn("후보 **3**종목", text)
        self.assertIn("`partial`", text)

    def test_footer_states_the_engine_without_claiming_reinforcement_learning(self):
        embed = embeds.portfolio_embed(proposal=_proposal(), risk=_risk(), run=_run())

        footer = str(embed["footer"]["text"])
        self.assertIn("TradingAgents", footer)
        self.assertIn("RiskGate", footer)
        self.assertNotIn("강화학습", footer)

    def test_metrics_present_but_null_do_not_crash_the_card(self):
        """shadow 경로는 시장위험을 계산하지 않아 키는 있고 값이 null이다(실데이터)."""
        risk = _risk(metrics={
            "turnover": 0.068,
            "portfolio_beta": None,
            "portfolio_volatility": None,
            "concentration_hhi": 0.0046,
        })

        embed = embeds.portfolio_embed(proposal=_proposal(), risk=risk, run=_run())

        text = _flatten(embed)
        self.assertIn("0.07", text)
        self.assertNotIn("None", text)

    def test_a_metrics_block_with_no_usable_number_says_so(self):
        risk = _risk(metrics={"portfolio_beta": None, "portfolio_volatility": None})

        embed = embeds.portfolio_embed(proposal=_proposal(), risk=risk, run=_run())

        self.assertNotIn("None", _flatten(embed))


class CandidateEmbedTest(unittest.TestCase):
    def _colour(self, signal):
        decision = _decision()
        decision["final_decision"] = {**decision["final_decision"], "signal": signal}
        return embeds.candidate_embed(decision=decision)["color"]

    def test_every_signal_produces_a_card(self):
        for signal in ("avoid", "watch", "open", "increase", "hold", "reduce", "exit"):
            decision = _decision()
            decision["final_decision"] = {**decision["final_decision"], "signal": signal}

            embed = embeds.candidate_embed(decision=decision)

            self.assertIn(embed["color"], {COLOR_APPROVED, COLOR_REJECTED, COLOR_INFO}, signal)
            self.assertIn("AAPL", str(embed["title"]))

    def test_buy_side_signals_are_green_and_sell_side_are_red(self):
        self.assertEqual(self._colour("open"), COLOR_APPROVED)
        self.assertEqual(self._colour("increase"), COLOR_APPROVED)
        self.assertEqual(self._colour("reduce"), COLOR_REJECTED)
        self.assertEqual(self._colour("exit"), COLOR_REJECTED)
        self.assertEqual(self._colour("hold"), COLOR_INFO)

    def test_reasoning_lines_are_carried_into_the_card(self):
        embed = embeds.candidate_embed(decision=_decision())

        self.assertIn("서비스 마진 개선", _flatten(embed))

    def test_missing_evidence_is_shown_not_hidden(self):
        decision = _decision()
        decision["final_decision"] = {
            **decision["final_decision"],
            "missing_data": ["gurus: 매핑된 보유 근거 없음", "segments: 검증된 세그먼트 없음"],
        }

        embed = embeds.candidate_embed(decision=decision)

        text = _flatten(embed)
        self.assertIn("gurus", text)
        self.assertIn("segments", text)

    def test_a_card_without_missing_data_says_so_rather_than_leaving_a_blank(self):
        embed = embeds.candidate_embed(decision=_decision())

        self.assertNotIn("None", _flatten(embed))


def _order(**overrides):
    row = {
        "client_order_id": "order_1",
        "intent_id": "intent_1",
        "approval_id": "approval_1",
        "ticker": "AAPL",
        "side": "buy",
        "quantity": 12,
        "reference_price": 230.5,
        "notional": 2766.0,
        "status": "filled",
        "submitted_at": "2026-09-03T13:31:00+00:00",
    }
    row.update(overrides)
    return row


class TradeEmbedTest(unittest.TestCase):
    def test_buy_order_is_green_and_sell_order_is_red(self):
        buy = embeds.trade_embed(order=_order(), fills=[], execution_mode="paper")
        sell = embeds.trade_embed(order=_order(side="sell"), fills=[], execution_mode="paper")

        self.assertEqual(buy["color"], COLOR_APPROVED)
        self.assertEqual(sell["color"], COLOR_REJECTED)

    def test_execution_mode_is_always_visible(self):
        embed = embeds.trade_embed(order=_order(), fills=[], execution_mode="live")

        self.assertIn("live", _flatten(embed).lower())

    def test_fills_are_summarised_with_average_price(self):
        fills = [
            {"quantity": 8, "price": 230.0, "commission": 0.5,
             "filled_at": "2026-09-03T13:31:05+00:00"},
            {"quantity": 4, "price": 233.0, "commission": 0.3,
             "filled_at": "2026-09-03T13:31:20+00:00"},
        ]

        embed = embeds.trade_embed(order=_order(), fills=fills, execution_mode="live")

        text = _flatten(embed)
        self.assertIn("12", text)
        self.assertIn("231.00", text)

    def test_an_unfilled_order_says_so_instead_of_showing_a_zero_price(self):
        embed = embeds.trade_embed(
            order=_order(status="submitted"), fills=[], execution_mode="live",
        )

        text = _flatten(embed)
        self.assertNotIn("0.00", text)
        self.assertIn("approval_1", text)


class DecisionExplanationTest(unittest.TestCase):
    """카드는 '왜 이 비중이 바뀌었나'와 '어제와 무엇이 달라졌나'를 원장 값으로만 설명한다."""

    def test_portfolio_card_explains_each_weight_change(self):
        from investment_agent.notifications.investment.embeds import portfolio_embed

        embed = portfolio_embed(
            proposal={"weights": {"AAPL": 0.0, "MSFT": 0.08, "CASH": 0.92}, "metadata": {"trade_reasons": {
                "AAPL": {"code": "ALPHA_DECAY", "current_weight": 0.1, "target_weight": 0.0,
                         "constraint": "block_increase", "expected_return_capped": False},
                "MSFT": {"code": "ALPHA_OPPORTUNITY", "current_weight": 0.0, "target_weight": 0.08,
                         "constraint": None, "expected_return_capped": True},
            }}},
            risk={"is_approved": True, "metrics": {}},
            run={"candidate_tickers": ["AAPL", "MSFT"], "status": "completed"},
        )
        field = next(item for item in embed["fields"] if item["name"] == "🔁 비중 변경 사유")
        self.assertIn("`AAPL` 10.0% → 0.0% · 전망 약화", field["value"])
        self.assertIn("확대 금지", field["value"])
        self.assertIn("과대 기대수익 상한 적용", field["value"])

    def test_portfolio_card_without_reasons_adds_no_empty_field(self):
        from investment_agent.notifications.investment.embeds import portfolio_embed

        embed = portfolio_embed(proposal={"weights": {"CASH": 1.0}}, risk={"is_approved": True}, run={})
        self.assertNotIn("🔁 비중 변경 사유", [item["name"] for item in embed["fields"]])

    def test_candidate_card_shows_continuity_not_the_unused_llm_weight(self):
        from investment_agent.notifications.investment.embeds import candidate_embed

        embed = candidate_embed(decision={"ticker": "AAPL", "final_decision": {
            "signal": "reduce", "target_weight": 0.3, "previous_signal": "increase", "reasoning": ["r"]}})
        signal = embed["fields"][0]["value"]
        self.assertNotIn("목표 비중", signal)
        self.assertIn("직전 판단 확대 의견 → **방향 변경**", signal)


if __name__ == "__main__":
    unittest.main()

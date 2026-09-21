"""factor 점수: 방향·결측·업종 상대·품질 기준·결정적 순위."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from investment_agent.research.features import factors
from investment_agent.research.features.factors import (
    FactorModel,
    percentile_ranks,
    rank_candidates,
    score_cross_section,
)


def _row(**values):
    return values


class PercentileTest(unittest.TestCase):
    def test_ties_share_the_average_rank_and_missing_is_excluded(self):
        ranks = percentile_ranks({"A": 1.0, "B": 2.0, "C": 2.0, "D": 3.0, "E": None})
        self.assertEqual(ranks, {"A": 0.0, "B": 0.5, "C": 0.5, "D": 1.0})

    def test_single_value_is_neutral(self):
        self.assertEqual(percentile_ranks({"A": 5.0}), {"A": 0.5})


class ScoreTest(unittest.TestCase):
    def test_lower_is_better_factors_are_inverted(self):
        features = {
            "GOOD": _row(quality_roe_ttm=0.3, quality_accruals_ttm=-0.1, quality_operating_margin_volatility=0.01),
            "BAD": _row(quality_roe_ttm=0.05, quality_accruals_ttm=0.2, quality_operating_margin_volatility=0.2),
        }
        scores = score_cross_section(features)
        self.assertEqual(scores["GOOD"].category_scores["quality"], 1.0)
        self.assertEqual(scores["BAD"].category_scores["quality"], 0.0)

    def test_missing_factor_does_not_score_as_zero(self):
        features = {
            "A": _row(momentum_12_1=0.5, momentum_6_1=0.2),
            "B": _row(momentum_12_1=0.1, momentum_6_1=None),
            "C": _row(momentum_12_1=0.3, momentum_6_1=0.1),
        }
        scores = score_cross_section(features)
        self.assertEqual(scores["B"].category_scores["momentum"], 0.0)  # 가진 factor에서만 최하위
        self.assertIn("momentum", scores["B"].category_scores)

    def test_category_needs_half_of_its_factors(self):
        features = {"A": _row(quality_roe_ttm=0.2), "B": _row(quality_roe_ttm=0.1)}
        self.assertNotIn("quality", score_cross_section(features)["A"].category_scores)

    def test_loss_making_firm_keeps_value_category_and_scores_lower(self):
        """적자·음의 FCF를 결측으로 접으면 value category가 탈락하고, composite이 남은
        category로 재정규화되어 **나쁜 종목의 점수가 올라간다**(감사 RR2-01).
        수익률이 부호를 보존하므로 적자는 최하위 랭크를 받아야 한다."""
        shared = {"momentum_12_1": 0.1, "momentum_6_1": 0.1}
        features = {
            "PROFIT": _row(valuation_earnings_yield=0.08, valuation_fcf_yield=0.06, **shared),
            "MID": _row(valuation_earnings_yield=0.03, valuation_fcf_yield=0.02, **shared),
            "LOSS": _row(valuation_earnings_yield=-0.09, valuation_fcf_yield=-0.05, **shared),
        }
        scores = score_cross_section(features)
        self.assertIn("value", scores["LOSS"].category_scores)
        self.assertEqual(scores["LOSS"].category_scores["value"], 0.0)
        self.assertEqual(scores["PROFIT"].category_scores["value"], 1.0)
        self.assertLess(scores["LOSS"].composite, scores["MID"].composite)
        self.assertLess(scores["MID"].composite, scores["PROFIT"].composite)

    def test_dropping_value_category_would_raise_the_composite(self):
        """재정규화 편향이 실재함을 고정한다 — value가 빠지면 composite이 올라간다.
        이 관계가 유지되는 한, 나쁜 관측을 결측으로 접는 것은 그 자체로 결함이다."""
        shared = {"momentum_12_1": 0.1, "momentum_6_1": 0.1}
        with_value = score_cross_section({
            "X": _row(valuation_earnings_yield=-0.09, valuation_fcf_yield=-0.05, **shared),
            "Y": _row(valuation_earnings_yield=0.08, valuation_fcf_yield=0.06, **shared),
        })
        without_value = score_cross_section({
            "X": _row(**shared),
            "Y": _row(**shared),
        })
        self.assertLess(with_value["X"].composite, without_value["X"].composite)

    def test_value_is_ranked_within_sector_when_groups_are_large_enough(self):
        features = {}
        groups = {}
        for index in range(5):
            features[f"BANK{index}"] = _row(valuation_earnings_yield=0.10 + index * 0.01, valuation_fcf_yield=0.1)
            groups[f"BANK{index}"] = "finance"
            features[f"SOFT{index}"] = _row(valuation_earnings_yield=0.01 + index * 0.001, valuation_fcf_yield=0.02)
            groups[f"SOFT{index}"] = "software"
        scores = score_cross_section(features, groups=groups)
        # 업종 안에서 가장 싼 소프트웨어 종목은, 전체로는 은행보다 비싸도 가치 점수가 높다.
        self.assertGreater(scores["SOFT4"].category_scores["value"], scores["BANK0"].category_scores["value"])

    def test_quality_gate_blocks_low_quality_even_with_a_high_composite(self):
        features = {
            "CHEAP_JUNK": _row(quality_roe_ttm=0.01, quality_roa_ttm=0.0, quality_fcf_margin_ttm=0.0, valuation_earnings_yield=0.2,
                               valuation_fcf_yield=0.2, momentum_12_1=0.9, momentum_6_1=0.5),
            "QUALITY": _row(quality_roe_ttm=0.3, quality_roa_ttm=0.15, quality_fcf_margin_ttm=0.2, valuation_earnings_yield=0.03,
                            valuation_fcf_yield=0.03, momentum_12_1=0.1, momentum_6_1=0.05),
            "MID": _row(quality_roe_ttm=0.15, quality_roa_ttm=0.08, quality_fcf_margin_ttm=0.1, valuation_earnings_yield=0.06,
                        valuation_fcf_yield=0.05, momentum_12_1=0.2, momentum_6_1=0.1),
        }
        scores = score_cross_section(features)
        self.assertFalse(scores["CHEAP_JUNK"].passes_quality_gate)
        self.assertEqual(scores["CHEAP_JUNK"].gate_reason, "quality_below_floor")
        self.assertEqual([score.ticker for score in rank_candidates(scores, limit=5)], ["MID", "QUALITY"])

    def test_unknown_quality_fails_the_gate(self):
        scores = score_cross_section({"A": _row(momentum_12_1=0.2, momentum_6_1=0.1)})
        self.assertEqual(scores["A"].gate_reason, "quality_unknown")

    def test_weights_change_the_composite(self):
        features = {
            "MOM": _row(momentum_12_1=0.9, momentum_6_1=0.5, valuation_earnings_yield=0.01, valuation_fcf_yield=0.01),
            "VAL": _row(momentum_12_1=0.0, momentum_6_1=0.0, valuation_earnings_yield=0.2, valuation_fcf_yield=0.2),
        }
        momentum_only = FactorModel(version="t", weights={"momentum": 1.0, "value": 0.0})
        scores = score_cross_section(features, model=momentum_only)
        self.assertGreater(scores["MOM"].composite, scores["VAL"].composite)

    def test_invalid_models_are_rejected(self):
        with self.assertRaises(ValueError):
            FactorModel(weights={"astrology": 1.0})
        with self.assertRaises(ValueError):
            FactorModel(weights={"value": 0.0})


class FactorModelReportTest(unittest.TestCase):
    def test_explicit_horizon_and_version_create_a_model_without_changing_the_default(self):
        report = {
            "suggested_weights_by_horizon": {
                "20": {
                    "basis": "mean_ic_where_t_adj>=1.5",
                    "weights": {
                        "quality": 0.4,
                        "balance_sheet": 0.2,
                        "growth": 0.1,
                        "value": 0.1,
                        "revision": 0.0,
                        "momentum": 0.2,
                    },
                },
                "60": {
                    "basis": "mean_ic_where_t_adj>=1.5",
                    "weights": {
                        "quality": 0.1,
                        "balance_sheet": 0.1,
                        "growth": 0.2,
                        "value": 0.3,
                        "revision": 0.1,
                        "momentum": 0.2,
                    },
                },
            }
        }
        loader = getattr(factors, "load_factor_model_from_ic_report", None)
        self.assertIsNotNone(loader, "IC 보고서 로더가 아직 구현되지 않았다")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            model = loader(path, horizon=60, version="factor-v2-ic-60d")

        self.assertEqual(model.version, "factor-v2-ic-60d")
        self.assertEqual(model.weights["value"], 0.3)
        self.assertEqual(model.weights["quality"], 0.1)
        self.assertEqual(FactorModel().version, "factor-v1-equal")
        self.assertEqual(set(FactorModel().weights.values()), {1.0})

    def test_missing_horizon_is_rejected_instead_of_silently_falling_back(self):
        report = {"suggested_weights_by_horizon": {}}
        loader = getattr(factors, "load_factor_model_from_ic_report", None)
        self.assertIsNotNone(loader, "IC 보고서 로더가 아직 구현되지 않았다")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "horizon 60"):
                loader(path, horizon=60, version="factor-v2-ic-60d")


if __name__ == "__main__":
    unittest.main()

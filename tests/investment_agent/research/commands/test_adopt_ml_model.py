from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from investment_agent.research.commands.adopt_ml_model import check_adoptable, main


def _payload(**alpha) -> dict:
    values = {"mean_ic": 0.04, "ic_t_stat": 3.0, "date_count": 60, "mean_quantile_spread": 0.004,
              "inference_method": "newey_west_bartlett_iid_floor_v2", "horizon_days": 20, "hac_lags": 19}
    values.update(alpha)
    return {
        "artifact": {
            "artifact_id": "model_x", "model_kind": "ridge", "feature_version": "v", "horizon_days": 20,
            "out_of_sample": {"rank_correlation": 0.1, "direction_accuracy": 0.55},
        },
        "model_state": {"coefficients": [0.1], "intercept": 0.0},
        "feature_names": ["f"],
        "out_of_sample_alpha": values,
        "dataset_manifest": {"label_definition": "excess_return_20d"},
    }


class AdoptMlModelTest(unittest.TestCase):
    def test_significant_positive_ic_is_adoptable(self):
        self.assertTrue(check_adoptable(_payload()).is_adoptable)

    def test_model_on_another_horizon_is_not_adoptable(self):
        payload = _payload()
        payload["artifact"]["horizon_days"] = 5
        check = check_adoptable(payload)
        self.assertFalse(check.is_adoptable)
        self.assertTrue(any("horizon" in reason for reason in check.reasons))

    def test_model_trained_on_raw_returns_is_not_adoptable(self):
        """원수익률 label 모델의 예측을 기대초과수익으로 쓰면 시장 전체 상승을 종목 능력으로 착각한다."""
        payload = _payload()
        payload["dataset_manifest"]["label_definition"] = "forward_return_20d"
        check = check_adoptable(payload)
        self.assertFalse(check.is_adoptable)
        self.assertTrue(any("excess-return" in reason for reason in check.reasons), check.reasons)

    def test_each_evidence_gap_blocks_adoption(self):
        for overrides, fragment in (
            ({"mean_ic": -0.01}, "positive"),
            ({"ic_t_stat": 1.5}, "t-stat"),
            ({"date_count": 10}, "dates"),
            ({"mean_quantile_spread": -0.001}, "spread"),
            ({"mean_quantile_spread": float("nan")}, "spread"),
            ({"inference_method": "iid"}, "HAC"),
            ({"hac_lags": 0}, "HAC"),
        ):
            with self.subTest(overrides=overrides):
                check = check_adoptable(_payload(**overrides))
                self.assertFalse(check.is_adoptable)
                self.assertTrue(any(fragment in reason for reason in check.reasons), check.reasons)

    def test_boosting_artifacts_without_reloadable_state_are_rejected(self):
        payload = _payload()
        payload["artifact"]["model_kind"] = "lightgbm"
        self.assertFalse(check_adoptable(payload).is_adoptable)

    def test_main_writes_only_adoptable_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good, bad, target = root / "good.json", root / "bad.json", root / "active.json"
            good.write_text(json.dumps(_payload()), encoding="utf-8")
            bad.write_text(json.dumps(_payload(ic_t_stat=0.5)), encoding="utf-8")
            self.assertEqual(main(["--artifact", str(bad), "--output", str(target)]), 1)
            self.assertFalse(target.exists())
            self.assertEqual(main(["--artifact", str(good), "--output", str(target)]), 0)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["artifact"]["artifact_id"], "model_x")


if __name__ == "__main__":
    unittest.main()

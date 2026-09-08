"""ResearchStore의 PIT feature snapshot을 Qlib research workflow에만 연결한다."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import pandas as pd

from investment_agent.research.rl.contracts import FeatureSnapshot


@dataclass(frozen=True)
class QlibSegments:
    train: tuple[str, str]
    valid: tuple[str, str]
    test: tuple[str, str]

    def to_dict(self) -> dict[str, tuple[str, str]]:
        return {"train": self.train, "valid": self.valid, "test": self.test}


class QlibPITAdapter:
    """Qlib data vendor를 쓰지 않고 StaticDataLoader로 우리 snapshot만 전달한다."""

    @staticmethod
    def to_frame(
        snapshots: Sequence[FeatureSnapshot],
        *,
        labels: Mapping[str, float] | None = None,
    ) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        versions = {snapshot.feature_version for snapshot in snapshots}
        if not snapshots or len(versions) != 1:
            raise ValueError("Qlib export requires non-empty snapshots with one feature version")
        for snapshot in snapshots:
            if not snapshot.is_available:
                continue
            row = {
                ("feature", name): value
                for name, value in sorted(snapshot.features.items())
            }
            if labels is not None:
                if snapshot.snapshot_id not in labels:
                    raise ValueError(f"missing label for {snapshot.snapshot_id}")
                row[("label", "LABEL0")] = float(labels[snapshot.snapshot_id])
            row["datetime"] = pd.Timestamp(snapshot.as_of_at)
            row["instrument"] = snapshot.ticker
            rows.append(row)
        if not rows:
            raise ValueError("no available Qlib feature rows")
        frame = pd.DataFrame(rows).set_index(["datetime", "instrument"]).sort_index()
        data_columns = [column for column in frame.columns if isinstance(column, tuple)]
        frame = frame[data_columns]
        frame.columns = pd.MultiIndex.from_tuples(data_columns)
        return frame

    @staticmethod
    def dataset(frame: pd.DataFrame, *, segments: QlibSegments):
        try:
            from qlib.data.dataset import DatasetH
            from qlib.data.dataset.handler import DataHandlerLP
        except ImportError as exc:  # pragma: no cover - 선택 의존성
            raise RuntimeError("Qlib이 필요하다: uv sync --group research") from exc
        handler = DataHandlerLP.from_df(frame)
        return DatasetH(handler=handler, segments=segments.to_dict())

    @staticmethod
    def record_experiment(
        *,
        experiment_name: str,
        params: Mapping[str, Any],
        metrics: Mapping[str, float],
        artifacts: Sequence[str] = (),
    ) -> str:
        try:
            from qlib.workflow import R
        except ImportError as exc:  # pragma: no cover - 선택 의존성
            raise RuntimeError("Qlib이 필요하다: uv sync --group research") from exc
        with R.start(experiment_name=experiment_name):
            R.log_params(**dict(params))
            R.log_metrics(**{key: float(value) for key, value in metrics.items()})
            for artifact in artifacts:
                R.log_artifact(local_path=artifact)
            recorder = R.get_recorder()
            return str(recorder.id)


__all__ = ["QlibPITAdapter", "QlibSegments"]

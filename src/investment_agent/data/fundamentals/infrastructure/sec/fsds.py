"""SEC Financial Statement Data Sets 벌크 캐시와 수집 어댑터."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from threading import Lock
from zipfile import is_zipfile

import pandas as pd

from investment_agent.platform.clock import us_market_today
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

_UPDATE_BANNER_LOCK = Lock()
_SPONSOR_URL = "https://github.com/sponsors/HansjoergW"


def _safe_sponsoring_message() -> None:
    """Windows cp949에서도 안전한 한 줄 sponsor 안내를 남긴다."""
    log.info("secfsdstools update complete; sponsor_url=%s", _SPONSOR_URL)


def _run_update_without_unsafe_banner(update, *, config) -> None:
    """업데이트 동안만 cp949 비호환 vendor 배너를 안전한 로그로 교체한다."""
    from secfsdstools.c_update import updateprocess

    with _UPDATE_BANNER_LOCK:
        original = updateprocess.print_sponsoring_message
        updateprocess.print_sponsoring_message = _safe_sponsoring_message
        try:
            update(config=config, force_update=True)
        finally:
            updateprocess.print_sponsoring_message = original


@dataclass(frozen=True)
class ReportRef:
    accession_no: str
    cik: int
    form_type: str
    filed: int
    period: int
    source_path: str
    source_file: str
    source_type: str


@dataclass(frozen=True)
class ReportBatch:
    source_path: str
    source_file: str
    reports: tuple[ReportRef, ...]


@dataclass
class BulkFrames:
    sub_df: pd.DataFrame
    num_df: pd.DataFrame


def _previous_quarter(day: date) -> tuple[int, int]:
    quarter = (day.month - 1) // 3 + 1
    if quarter == 1:
        return day.year - 1, 4
    return day.year, quarter - 1


def _expected_quarters(cutoff: date, today: date) -> list[str]:
    end_year, end_quarter = _previous_quarter(today)
    year = cutoff.year
    quarter = (cutoff.month - 1) // 3 + 1
    out: list[str] = []
    while (year, quarter) <= (end_year, end_quarter):
        out.append(f"{year}q{quarter}.zip")
        quarter += 1
        if quarter == 5:
            year += 1
            quarter = 1
    return out


def _remove_corrupt_downloads(download_dir: str) -> list[str]:
    removed: list[str] = []
    for path in Path(download_dir).glob("*.zip"):
        if is_zipfile(path):
            continue
        path.unlink()
        removed.append(path.name)
    return removed


def _quarter_present(parquet_dir: str, name: str) -> bool:
    root = Path(parquet_dir) / "quarter" / name
    return all(
        (root / filename).exists()
        for filename in ("sub.txt.parquet", "num.txt.parquet", "pre.txt.parquet")
    )


def _missing_quarters(parquet_dir: str, cutoff: date) -> list[str]:
    return [
        name for name in _expected_quarters(cutoff, us_market_today())
        if not _quarter_present(parquet_dir, name)
    ]


def _split_missing(parquet_dir: str, cutoff: date) -> tuple[list[str], list[str]]:
    """빠진 분기를 (중간 구멍, 아직 게시 안 된 최신 구간)으로 나눈다.

    SEC는 분기가 끝나고 한참 뒤에 Financial Statement Data Sets를 게시한다.
    직전 분기가 아직 없는 건 정상 상태인데, 이걸 실패로 처리하면 매 분기
    초반마다 segments 백필이 통째로 죽는다. 이미 게시된 구간 사이의 구멍만
    실패로 보고, 끝쪽에 연속으로 빠진 분기는 건너뛴다.
    """
    expected = _expected_quarters(cutoff, us_market_today())
    present = [name for name in expected if _quarter_present(parquet_dir, name)]
    if not present:
        return expected, []
    last_present = expected.index(present[-1])
    gaps = [
        name for name in expected[:last_present]
        if not _quarter_present(parquet_dir, name)
    ]
    return gaps, expected[last_present + 1:]


def _validate_quarter_cache(parquet_dir: str, cutoff: date) -> None:
    gaps, unpublished = _split_missing(parquet_dir, cutoff)
    if gaps:
        raise RuntimeError(
            "secfsdstools quarter cache is incomplete: " + ", ".join(gaps)
        )
    if unpublished:
        log.info(
            "SEC 미게시로 건너뛴 최신 분기: %s (게시되면 다음 실행에서 채워진다)",
            ", ".join(unpublished),
        )


def _ensure_segment_data(*, cutoff: date) -> None:
    """손상 캐시를 복구하고 요청 구간의 SEC 벌크 데이터를 검증한다."""
    from secfsdstools.a_config.configmgt import ConfigurationManager
    from secfsdstools.update import update

    config = ConfigurationManager.read_config_file()
    missing_before = _missing_quarters(config.parquet_dir, cutoff)
    if not missing_before:
        return

    removed = _remove_corrupt_downloads(config.download_dir)
    if removed:
        log.warning("removed corrupt secfsds downloads: %s", removed)
    log.warning("missing secfsdstools quarter cache before update: %s", missing_before)
    _run_update_without_unsafe_banner(update, config=config)
    _validate_quarter_cache(config.parquet_dir, cutoff)


def ensure_data(*, cutoff: date | None = None) -> None:
    """전사 재무 캐시는 전체 갱신하고 세그먼트 캐시는 요청 구간까지 검증한다."""
    if cutoff is not None:
        _ensure_segment_data(cutoff=cutoff)
        return
    from secfsdstools.update import update

    update()


def _prefer(candidate: ReportRef, current: ReportRef | None) -> bool:
    if current is None:
        return True
    rank = {"quarter": 2, "daily": 1}
    return rank.get(candidate.source_type, 0) > rank.get(current.source_type, 0)


def discover_batches(
    *,
    ciks: Iterable[int],
    forms: Iterable[str],
    cutoff: date,
    skip_accessions: set[str],
    include_accessions: set[str] | None = None,
) -> list[ReportBatch]:
    """기간·form·CIK에 맞는 공시를 원본 분기 파일별 batch로 묶는다."""
    from secfsdstools.a_config.configmgt import ConfigurationManager
    from secfsdstools.c_index.indexdataaccess import ParquetDBIndexingAccessor

    cik_list = sorted(set(ciks))
    if not cik_list:
        return []

    config = ConfigurationManager.read_config_file()
    accessor = ParquetDBIndexingAccessor(db_dir=config.db_dir)
    raw = accessor.read_index_reports_for_ciks(cik_list, list(forms))
    cutoff_n = int(cutoff.strftime("%Y%m%d"))

    by_accession: dict[str, ReportRef] = {}
    for report in raw:
        if int(report.period) < cutoff_n or report.adsh in skip_accessions:
            continue
        if include_accessions is not None and report.adsh not in include_accessions:
            continue
        candidate = ReportRef(
            accession_no=str(report.adsh),
            cik=int(report.cik),
            # secfsdstools의 IndexReport는 SEC 원본 이름 그대로 `form`이다.
            form_type=str(report.form),
            filed=int(report.filed),
            period=int(report.period),
            source_path=str(report.fullPath),
            source_file=str(report.originFile),
            source_type=str(report.originFileType),
        )
        if _prefer(candidate, by_accession.get(candidate.accession_no)):
            by_accession[candidate.accession_no] = candidate

    by_path: dict[tuple[str, str], list[ReportRef]] = defaultdict(list)
    for report in by_accession.values():
        by_path[(report.source_path, report.source_file)].append(report)

    batches = [
        ReportBatch(
            source_path=source_path,
            source_file=source_file,
            reports=tuple(sorted(reports, key=lambda row: row.accession_no)),
        )
        for (source_path, source_file), reports in by_path.items()
    ]
    batches.sort(key=lambda batch: batch.source_file)
    return batches


def _read_parquet(
    source_path: str,
    filename: str,
    *,
    columns: list[str],
    accessions: list[str],
) -> pd.DataFrame:
    path = Path(source_path) / f"{filename}.parquet"
    return pd.read_parquet(
        str(path),
        columns=columns,
        filters=[[("adsh", "in", accessions)]],
    )


def load_batch(batch: ReportBatch) -> BulkFrames:
    """한 원본 분기 파일을 한 번만 스캔해 대상 공시들을 읽는다."""
    accessions = [report.accession_no for report in batch.reports]
    # 파케이 컬럼은 SEC 원본 이름(`form`)이다. 내부 용어(`form_type`)로 여기서 한 번만
    # 바꿔 downstream이 두 이름을 알 필요가 없게 한다.
    sub_df = _read_parquet(
        batch.source_path,
        "sub.txt",
        columns=["adsh", "cik", "form", "fy", "fp", "period", "filed"],
        accessions=accessions,
    ).rename(columns={"form": "form_type"})
    num_df = _read_parquet(
        batch.source_path,
        "num.txt",
        columns=[
            "adsh",
            "tag",
            "version",
            "ddate",
            "qtrs",
            "uom",
            "segments",
            "coreg",
            "value",
        ],
        accessions=accessions,
    )
    log.info(
        "secfsds batch loaded source=%s reports=%d num_rows=%d",
        batch.source_file,
        len(batch.reports),
        len(num_df),
    )
    return BulkFrames(sub_df=sub_df, num_df=num_df)


def iter_batches(
    *,
    ciks: Iterable[int],
    forms: Iterable[str],
    cutoff: date,
    skip_accessions: set[str],
    include_accessions: set[str] | None = None,
) -> Iterator[tuple[ReportBatch, BulkFrames]]:
    """발견된 batch를 순서대로 읽어 즉시 처리할 수 있게 반환한다."""
    for batch in discover_batches(
        ciks=ciks,
        forms=forms,
        cutoff=cutoff,
        skip_accessions=skip_accessions,
        include_accessions=include_accessions,
    ):
        yield batch, load_batch(batch)

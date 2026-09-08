"""분리 저장한 배당·분할 이벤트를 가격 행에 읽기 전용으로 결합한다."""
from __future__ import annotations


def merge_corporate_actions(
    prices: list[dict],
    dividends: list[dict],
    splits: list[dict],
) -> list[dict]:
    """가격 행의 grain을 바꾸지 않고 같은 거래일의 이벤트만 붙인다."""
    dividend_by_key = {
        (str(row["ticker"]), str(row["ex_date"])): row.get("div_amount")
        for row in dividends
        if row.get("ticker") and row.get("ex_date")
    }
    split_by_key = {
        (str(row["ticker"]), str(row["action_date"])): row.get("split_ratio")
        for row in splits
        if row.get("ticker") and row.get("action_date")
    }
    merged: list[dict] = []
    for price in prices:
        key = (str(price["ticker"]), str(price["trade_date"]))
        merged.append({
            **price,
            "div_amount": dividend_by_key.get(key),
            "split_ratio": split_by_key.get(key),
        })
    return merged

---
name: hypothesis
description: "Property-based testing framework for Python. Generates arbitrary edge cases (inf, nan, negative zero, float precision, boundary permutations) to verify mathematical invariants, risk gates, and financial portfolio contracts."
---

# Hypothesis (Property-Based Testing for Financial Invariants)

Hypothesis finds edge cases by generating randomized, structured inputs against formal invariants. Instead of testing 3 or 4 hand-picked examples, Hypothesis tests dozens of arbitrary permutations to prove invariants hold under floating-point anomalies and boundary conditions.

## Execution

Run property-based tests using the repository Python environment:
```powershell
& (Get-Content graphify-out\.graphify_python) -m unittest tests/investment_agent/trading/portfolio/test_contracts_hypothesis.py
```

## When to Use Hypothesis in This Repo

1. **Portfolio Weights & Simplex Constraints**:
   - Invariant: Long-only weights must sum to 1.0 (with CASH buffer).
   - Invariant: All weights must be in `[0.0, 1.0]`.
   - Invariant: Key ordering must be lexicographical.
2. **Risk Gates & Sizing**:
   - Invariant: Monotonic sizing reduction under elevated volatility/drawdown.
   - Invariant: Hard constraints (e.g. `block_new_buy`, `force_exit`) must never yield positive target weights.
3. **Data Serialization & Datetime Parsers**:
   - Invariant: Timezone-aware UTC normalization must roundtrip safely.
   - Invariant: Rejection of invalid tickers and non-numeric probabilities.

## Example Pattern

```python
from hypothesis import given, settings
from hypothesis import strategies as st
from investment_agent.trading.portfolio.contracts import validated_weights, ContractError

@given(
    weights=st.lists(
        st.floats(min_value=0.01, max_value=1.0, allow_nan=False),
        min_size=1, max_size=5
    )
)
@settings(max_examples=50)
def test_weights_sum_to_one(weights: list[float]):
    total = sum(weights)
    norm = [w / total for w in weights]
    norm[-1] = 1.0 - sum(norm[:-1])  # exact sum closure
    mapping = {f"SYM{i}": w for i, w in enumerate(norm)}
    result = validated_weights(mapping, require_total=True)
    assert "CASH" in result
    assert math.isclose(sum(result.values()), 1.0, abs_tol=1e-7)
```

## Best Practices
- Always set `allow_nan=False, allow_infinity=False` when testing normal domain inputs, and explicitly test NaN/inf in failure tests.
- Keep `max_examples` between 30 and 50 for quick unit test execution under CI.

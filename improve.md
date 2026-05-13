# Future Improvements

## 1. Adaptive Base Buy Weight

The base buy weight is currently hardcoded at 6% (`base_weight = 0.06` in
`backend/src/signals/decision_rules.py` line 392). Every new buy starts at
this fixed allocation regardless of how many positions the portfolio already
holds or how much cash is available.

A smarter approach would scale the base weight based on:
- Available cash percentage (more cash = larger initial positions)
- Current position count vs target count (fewer positions = larger each)
- Portfolio conviction level (high-conviction runs could use 8%, low: 4%)

## 2. Less Conservative Rotation Logic

Rotation trims weak holdings to free up cash for stronger buy candidates.
Currently it only targets stocks that are both low-decile (<=4) AND failed
the quality filter (`is_good == False`), and requires the replacement to
score at least 0.1 higher on composite score. This is intentionally
conservative to avoid excessive turnover, but in practice it rarely fires.

Potential relaxations:
- Allow rotating good stocks that have stagnated (decile 4-5 for 60+ days)
- Lower the score advantage threshold from 0.1 to 0.05
- Consider partial rotation (trim 25% instead of 50%)

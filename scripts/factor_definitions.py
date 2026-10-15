"""Original 16 formula families, using explicit no-fill calendar returns under v2 preprocessing."""
import numpy as np
import pandas as pd

def factors(g: pd.DataFrame) -> dict[str, pd.Series]:
    close, op, hi, lo = g.close, g.open, g.high, g.low
    ret = close.pct_change(fill_method=None)
    rng = (hi - lo).replace(0, np.nan)
    loc = ((close - lo) / rng).clip(0, 1)
    # Image seed: -rank(ts_sum((close-low)/(high-close), 3)). We retain the
    # high-close denominator and also provide a bounded high-low variant.
    upper_room = (hi - close).replace(0, np.nan)
    panic_ratio = ((close - lo) / upper_room).replace([np.inf, -np.inf], np.nan)
    turn = g.turn.clip(lower=0)
    t20 = turn.rolling(20, min_periods=10).mean()
    vol20 = ret.rolling(20, min_periods=10).std()
    down = ret.where(ret < 0, 0.0)
    low3 = loc.rolling(3, min_periods=3).mean()
    low5 = loc.rolling(5, min_periods=5).mean()
    low20 = loc.rolling(20, min_periods=10).mean()
    low_count3 = (loc < 0.2).rolling(3, min_periods=3).sum()
    low_count5 = (loc < 0.2).rolling(5, min_periods=5).sum()
    turn_shock = (turn / t20.replace(0, np.nan)).clip(0, 20)
    f: dict[str, pd.Series] = {
        "O01_seed_upper_room_3d": -panic_ratio.rolling(3, min_periods=3).sum(),
        "O02_low_location_3d": -low3,
        "O03_low_location_5d": -low5,
        "O04_three_low_closes": low_count3,
        "O05_five_low_closes": low_count5,
        "O06_return_3d": -ret.rolling(3, min_periods=3).sum(),
        "O07_return_5d": -ret.rolling(5, min_periods=5).sum(),
        "O08_downside_sum_5d": -down.rolling(5, min_periods=5).sum(),
        "O09_drawdown_20d": -(close / close.rolling(20, min_periods=10).max() - 1),
        "O10_distance_low_20d": -(close / close.rolling(20, min_periods=10).min() - 1),
        "O11_low_close_turn_shock": -low3 * turn_shock,
        "O12_low_close_turn_dollar": -low3 * np.log1p(turn),
        "O13_low_close_high_vol": -low3 * (vol20 / vol20.rolling(60, min_periods=20).mean()),
        "O14_panic_range_low_close": -low3 * ((rng / close).rolling(5, min_periods=3).mean()),
        "O15_three_day_bear_pressure": -((close - op) / rng).rolling(3, min_periods=3).sum(),
        "O16_low_close_rebound_gap": -low3 * (-(op / close.shift(1) - 1)).clip(lower=0),
    }
    return {k: v.replace([np.inf, -np.inf], np.nan) for k, v in f.items()}

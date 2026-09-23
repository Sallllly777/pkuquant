"""Focused oversold-rebound factor mining.

The seed signal follows the supplied formula: a three-day sum of close
location near the low, with a negative sign so that deeper oversold conditions
rank higher. Candidates are evaluated cross-sectionally with next-day returns,
IC/ICIR, hit rate, realized portfolio turnover and long-short net Sharpe.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", default="projects/factor_backtest/runs/oversold_rebound")
    ap.add_argument("--start", default="2017-01-01")
    ap.add_argument("--end", default="2020-12-31")
    ap.add_argument("--cost-bps", type=float, default=5.0)
    ap.add_argument("--top-bottom", type=float, default=0.2)
    return ap.parse_args()


def load(path: Path, start: str, end: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["datetime"])
    df = df[(df.datetime >= start) & (df.datetime <= end)].copy()
    for c in ["open", "high", "low", "close", "volume", "turnover", "turn"]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["turn"] = df.get("turn", np.nan)
    df["turnover"] = df["turnover"].fillna(df["close"] * df["volume"])
    return df.dropna(subset=["datetime", "symbol", "open", "high", "low", "close", "volume", "turn"])


def factors(g: pd.DataFrame) -> dict[str, pd.Series]:
    close, op, hi, lo = g.close, g.open, g.high, g.low
    ret = close.pct_change()
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


def evaluate(data: pd.DataFrame, name: str, cost_bps: float, top_bottom: float) -> tuple[dict, pd.DataFrame]:
    d = data[["datetime", "symbol", "close", name]].dropna().copy()
    d["signal"] = d.groupby("datetime")[name].transform(lambda x: x.clip(x.quantile(.01), x.quantile(.99)).rank(pct=True))
    for h in [1, 3, 5]:
        d[f"fwd_{h}"] = d.groupby("symbol").close.transform(lambda x, h=h: x.shift(-h) / x - 1)
    ic: dict[int, pd.Series] = {}
    for h in [1, 3, 5]:
        ic[h] = d.groupby("datetime").apply(lambda x, h=h: x.signal.corr(x[f"fwd_{h}"], method="spearman") if x[["signal", f"fwd_{h}"]].dropna().shape[0] >= 10 else np.nan, include_groups=False).dropna()

    previous: dict[str, float] = {}

    def portfolio(x: pd.DataFrame) -> pd.Series:
        x = x.dropna(subset=["signal", "fwd_1"]).sort_values("signal")
        n = max(1, int(len(x) * top_bottom))
        if len(x) < max(10, n * 2):
            return pd.Series({"gross": np.nan, "turnover": np.nan})
        long_symbols, short_symbols = set(x.tail(n).symbol), set(x.head(n).symbol)
        current = {s: 0.5 / n for s in long_symbols} | {s: -0.5 / n for s in short_symbols}
        all_symbols = set(previous) | set(current)
        turnover = sum(abs(current.get(s, 0.0) - previous.get(s, 0.0)) for s in all_symbols) / 2
        previous.clear(); previous.update(current)
        return pd.Series({"gross": (x.tail(n).fwd_1.mean() - x.head(n).fwd_1.mean()) / 2, "turnover": turnover})

    daily = d.groupby("datetime").apply(portfolio, include_groups=False).dropna()
    if daily.empty:
        daily = pd.DataFrame(columns=["gross", "turnover"])
    daily["cost"] = daily.turnover * cost_bps / 10000
    daily["net"] = daily.gross - daily.cost
    equity = (1 + daily.net).cumprod()
    std = daily.net.std(ddof=1)
    metrics: dict[str, float] = {"factor": name, "observations": len(daily), "avg_turnover": daily.turnover.mean() if len(daily) else np.nan,
        "turnover_p95": daily.turnover.quantile(.95) if len(daily) else np.nan, "total_return": equity.iloc[-1] - 1 if len(equity) else np.nan,
        "annualized_return": equity.iloc[-1] ** (252 / len(equity)) - 1 if len(equity) else np.nan,
        "annualized_vol": std * np.sqrt(252) if np.isfinite(std) else np.nan, "sharpe": daily.net.mean() / std * np.sqrt(252) if std and np.isfinite(std) else np.nan,
        "max_drawdown": (equity / equity.cummax() - 1).min() if len(equity) else np.nan}
    for h in [1, 3, 5]:
        vals = ic[h]; metrics[f"ic_{h}_mean"] = vals.mean() if len(vals) else np.nan; metrics[f"ic_{h}_ir"] = vals.mean() / vals.std(ddof=1) if len(vals) > 1 and vals.std(ddof=1) else np.nan; metrics[f"ic_{h}_hit"] = (vals > 0).mean() if len(vals) else np.nan
    metrics["selection_score"] = np.nan
    out = daily.reset_index().rename(columns={"index": "datetime"}); out["factor"] = name
    return metrics, out


def main() -> None:
    a = args(); frame = load(Path(a.input), a.start, a.end)
    chunks = []
    for symbol, group in frame.groupby("symbol", sort=False):
        g = group.sort_values("datetime").reset_index(drop=True); chunks.append(g[["datetime", "symbol", "close"]].assign(**factors(g)))
    data = pd.concat(chunks, ignore_index=True).sort_values(["datetime", "symbol"])
    names = [c for c in data.columns if c.startswith("O")]
    metrics, daily = [], []
    for name in names:
        m, d = evaluate(data, name, a.cost_bps, a.top_bottom); metrics.append(m); daily.append(d)
    metrics_df = pd.DataFrame(metrics)
    # Rank only after all metrics are computed; this is a screening score, not
    # a claim of out-of-sample performance.
    for c in ["sharpe", "ic_1_ir", "ic_1_mean", "ic_1_hit"]:
        metrics_df[c + "_rank"] = metrics_df[c].rank(pct=True)
    metrics_df["avg_turnover_rank"] = metrics_df["avg_turnover"].rank(pct=True, ascending=False)
    metrics_df["selection_score"] = metrics_df[["sharpe_rank", "ic_1_ir_rank", "ic_1_mean_rank", "ic_1_hit_rank"]].mean(axis=1) + metrics_df["avg_turnover_rank"] * 0.25
    metrics_df = metrics_df.sort_values(["selection_score", "sharpe"], ascending=False)
    out = Path(a.output); out.mkdir(parents=True, exist_ok=True); metrics_df.to_csv(out / "oversold_factor_metrics.csv", index=False); pd.concat(daily, ignore_index=True).to_csv(out / "oversold_daily_returns.csv", index=False)
    top = metrics_df.head(5); fig, ax = plt.subplots(figsize=(12, 7)); all_daily = pd.concat(daily, ignore_index=True)
    for name in top.factor:
        d = all_daily[all_daily.factor == name].sort_values("datetime"); ax.plot(d.datetime, (1 + d.net).cumprod(), label=name)
    ax.set_title("Oversold rebound: selected factors"); ax.grid(alpha=.3); ax.legend(); fig.tight_layout(); fig.savefig(out / "selected_factor_equity.png", dpi=140); plt.close(fig)
    table = metrics_df.to_html(index=False, float_format=lambda x: f"{x:.4f}")
    manifest = {"start": a.start, "end": a.end, "symbols": int(frame.symbol.nunique()), "rows": int(len(frame)), "factor_count": len(names), "cost_bps": a.cost_bps, "top_bottom": a.top_bottom, "signal": "three-day close-near-low oversold rebound family", "universe_note": "HS300 constituents as of 2020-12-31; survivorship bias present"}
    (out / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "report.html").write_text("<html><meta charset='utf-8'><title>Oversold rebound factors</title><h1>Oversold rebound factor mining</h1><p>Signals use close t to predict t+1; results are research output.</p><img src='selected_factor_equity.png' style='max-width:100%'><h2>All candidates ranked by predictive power, net Sharpe and turnover</h2>" + table + "</html>", encoding="utf-8")
    print(f"complete: {len(names)} candidates, {frame.symbol.nunique()} symbols -> {out}")


if __name__ == "__main__": main()



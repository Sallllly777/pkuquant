# Research notes

## Signal construction

The seed expression is `-rank(ts_sum((close-low)/(high-close), 3))`. The implementation also includes a bounded close-location variant using `(close-low)/(high-low)` to avoid instability when the close is equal to the high.

Signals are calculated after the close of day `t`; the label is close-to-close return from `t` to `t+1`. Every date is ranked cross-sectionally. The long leg holds the top 20% of the signal and the short leg holds the bottom 20%. Transaction cost is 5 bps times realized one-way weight turnover.

## Screening

Candidates are ranked jointly by 1-day IC mean, ICIR, positive-IC hit rate, net long-short Sharpe and low realized turnover. The top three are retained in `config/selected_factors.json`.

## Limits

The experiment is in-sample over 2017–2020 and uses a frozen constituent list. It does not model suspension constraints, price limits, borrow availability, slippage beyond the fixed cost, or point-in-time membership changes.

"""Calendar-aligned factors, purged labels and self-financing research NAV.

Daily open-price simulation is an explicit diagnostic proxy, not a fill model.
No future return is used to choose positions or drop a portfolio observation.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
from factor_definitions import factors as original_factors

def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_panel(path):
    df = pd.read_csv(path, parse_dates=['datetime'])
    required = {'datetime','symbol','open','high','low','close','volume','turn'}
    if not required.issubset(df): raise ValueError(f'Missing columns: {sorted(required-set(df))}')
    if df[['datetime','symbol']].isna().any().any(): raise ValueError('Missing row identity')
    if df.duplicated(['datetime','symbol']).any(): raise ValueError('Duplicate date/symbol rows')
    original_rows = len(df)
    for col in ['open','high','low','close','volume','turn']:
        df[col] = pd.to_numeric(df[col], errors='coerce').replace([np.inf,-np.inf],np.nan)
    invalid_price = (df[['open','high','low','close']] <= 0).any(axis=1) | (df.high<df.low) | (df.close>df.high+1e-8) | (df.close<df.low-1e-8)
    df.loc[invalid_price,['open','high','low','close']] = np.nan
    df.loc[df.volume<0,'volume'] = np.nan
    df.loc[df.turn<0,'turn'] = np.nan
    df['source_present'] = True
    calendar = pd.DatetimeIndex(sorted(df.datetime.unique()))
    symbols = sorted(df.symbol.unique())
    index = pd.MultiIndex.from_product([calendar,symbols],names=['datetime','symbol'])
    df = df.set_index(['datetime','symbol']).reindex(index)
    quality = {'input_rows':original_rows,'calendar_dates':len(calendar),'symbols':len(symbols),
               'panel_rows':len(df),'absent_symbol_dates':int(df.source_present.isna().sum()),
               'missing_turn_source_rows':int((df.turn.isna() & df.source_present.eq(True)).sum()),
               'invalid_ohlc_rows':int(invalid_price.sum()),'zero_range_source_rows':int((df.high==df.low).sum()),
               'nonpositive_volume_rows':int((df.volume<=0).sum()),
               'start':str(calendar.min().date()),'end':str(calendar.max().date()),
               'calendar_source':'union of input dates; calendar gaps shared by all symbols are not independently detectable',
               'input_sha256':file_hash(path)}
    return df, quality

def factor_values(group):
    # Preserve all 16 historical formulas as named baselines; fixes get new IDs.
    values = original_factors(group)
    loc = ((group.close-group.low)/(group.high-group.low).replace(0,np.nan)).clip(0,1)
    low3 = loc.rolling(3,min_periods=3).mean()
    strength = 1-low3
    turnover = group.turn.clip(lower=0)
    ret = group.close.pct_change(fill_method=None)
    vol20 = ret.rolling(20,min_periods=10).std()
    relative_vol = vol20/vol20.rolling(60,min_periods=20).mean().replace(0,np.nan)
    values.update({
        'O11v2_low_strength_turn_shock_3d': strength*(turnover/turnover.rolling(20,min_periods=10).mean().replace(0,np.nan)).clip(0,20),
        'O12v2_low_strength_turn_3d': strength*np.log1p(turnover),
        'O13v2_low_strength_relative_vol_3d': strength*relative_vol,
        'O14v2_low_strength_range_3d': strength*((group.high-group.low)/group.close).rolling(5,min_periods=3).mean(),
        'O16v2_low_strength_gap_3d': strength*(-(group.open/group.close.shift(1)-1)).clip(lower=0)
    })
    return {k:v.replace([np.inf,-np.inf],np.nan) for k,v in values.items()}

def build_features(panel):
    chunks=[]
    for symbol in sorted(panel.index.get_level_values('symbol').unique()):
        g=panel.xs(symbol,level='symbol').copy()
        dates=pd.Series(g.index,index=g.index)
        # Labels are built on the complete calendar BEFORE factor availability.
        for h in (1,3,5):
            g[f'fwd_{h}']=g.close.shift(-h)/g.close-1
            g[f'label_end_{h}']=dates.shift(-h)
        g=g.assign(**factor_values(g))
        g['symbol']=symbol
        chunks.append(g.reset_index())
    return pd.concat(chunks,ignore_index=True).set_index(['datetime','symbol']).sort_index()

def wide(data,column): return data[column].unstack('symbol').sort_index()

def rank_ic(features,name,start,end,minimum=10):
    score=wide(features,name).loc[start:end]
    result=pd.DataFrame(index=score.index)
    for h in (1,3,5):
        labels=wide(features,f'fwd_{h}').reindex(score.index)
        ends=wide(features,f'label_end_{h}').reindex(score.index)
        valid=score.notna() & labels.notna() & ends.le(pd.Timestamp(end))
        a=score.where(valid).rank(axis=1,method='average')
        b=labels.where(valid).rank(axis=1,method='average')
        a=a.sub(a.mean(axis=1),axis=0); b=b.sub(b.mean(axis=1),axis=0)
        denominator=np.sqrt(a.pow(2).sum(axis=1)*b.pow(2).sum(axis=1))
        result[f'ic_{h}']=(a.mul(b).sum(axis=1)/denominator.replace(0,np.nan)).where(valid.sum(axis=1)>=minimum)
        result[f'n_{h}']=valid.sum(axis=1)
    return result

def weights(score,eligible,fraction=.2,mode='long_short',minimum=10,group=None):
    result=np.zeros(len(score))
    ids=np.flatnonzero(np.isfinite(score)&eligible)
    if len(ids)<minimum: return result
    # Stable tie-break only within nonconstant cross-sections. Constant signal => cash.
    if mode!='equal_weight' and np.unique(score[ids]).size<2: return result
    ids=ids[np.argsort(score[ids],kind='stable')]
    n=max(1,int(len(ids)*fraction))
    if mode=='equal_weight': result[ids]=1/len(ids)
    elif group is not None:
        bucket=np.array_split(ids,5)[group-1]
        result[bucket]=1/len(bucket)
    elif mode=='long_only': result[ids[-n:]]=1/n
    else:
        result[ids[-n:]]=.5/n; result[ids[:n]]=-.5/n
    return result

def fees(delta,prices,cost):
    notional=np.abs(delta)*prices
    traded=float(notional.sum()); sell=float(notional[delta<0].sum())
    return {'commission':traded*cost['commission_bps']/10000,
            'slippage':traded*cost['slippage_bps']/10000,
            'sell_extra':sell*cost['sell_extra_bps']/10000}

def simulate(features,name,start,end,cost,fraction=.2,minimum=10,mode='long_short',group=None):
    prices=wide(features,'open')
    marks=prices.ffill()  # stale valuation is logged; missing quotes never allow trading.
    scores=wide(features,name).shift(1)  # close t -> open t+1
    previous_volume=wide(features,'volume').shift(1)
    dates=prices.loc[start:end].index
    if len(dates)<2: raise ValueError('Need at least two calendar observations')
    shares=np.zeros(prices.shape[1]); cash=1.; previous_nav=1.; rows=[]
    for i,date in enumerate(dates):
        quote=prices.loc[date].to_numpy(dtype=float)
        mark=marks.loc[date].fillna(0).to_numpy(dtype=float)
        can_trade=np.isfinite(quote)&(quote>0)
        previous_active=previous_volume.loc[date].fillna(0).to_numpy()>0
        eligible=can_trade&previous_active
        before=float(cash+np.dot(shares,mark))
        if before<=0: raise ValueError('Nonpositive NAV; do not silently drop date')
        gross=before/previous_nav-1
        borrow=float(np.abs(np.minimum(shares,0)*mark).sum())*cost['short_borrow_annual_bps']/10000/252
        before-=borrow; cash-=borrow
        blocked=bool(np.any((shares!=0)&~can_trade))
        target=np.zeros_like(shares) if i==len(dates)-1 else weights(scores.loc[date].to_numpy(dtype=float),eligible,fraction,mode,minimum,group)
        parts={'commission':0.,'slippage':0.,'sell_extra':0.}; traded=0.
        if not blocked:
            # Fee-inclusive self-financing sizing avoids negative cash on a fully invested long book.
            after=before
            for _ in range(20):
                new=np.divide(target*after,quote,out=np.zeros_like(shares),where=can_trade)
                parts=fees(new-shares,np.where(can_trade,quote,0),cost)
                next_after=before-sum(parts.values())
                if abs(next_after-after)<1e-13:
                    after=next_after; break
                after=next_after
            new=np.divide(target*after,quote,out=np.zeros_like(shares),where=can_trade)
            delta=new-shares
            parts=fees(delta,np.where(can_trade,quote,0),cost)
            traded=float(np.sum(np.abs(delta)*mark))
            cash-=float(np.dot(delta,mark))+sum(parts.values())
            shares=new
        nav=float(cash+np.dot(shares,mark))
        if nav<=0: raise ValueError('Costs exhausted portfolio')
        rows.append({'datetime':date,'gross':gross,'net':nav/previous_nav-1,'nav':nav,'cash':cash,
                     'traded_notional':traded/previous_nav,'turnover':traded/previous_nav,
                     'cost':(sum(parts.values())+borrow)/previous_nav,
                     **{k:v/previous_nav for k,v in parts.items()},'borrow':borrow/previous_nav,
                     'gross_exposure':float(np.abs(shares*mark).sum()/nav),
                     'blocked_rebalance':int(blocked),'stale_held_quotes':int(np.sum((shares!=0)&~can_trade)),
                     'held_count':int(np.count_nonzero(shares)), 'factor':name,'mode':mode,'group':group or 0})
        previous_nav=nav
    return pd.DataFrame(rows)

def nav_metrics(daily,annual=252):
    r=daily.net; nav=daily.nav
    running_max=np.maximum.accumulate(np.r_[1.,nav.to_numpy()])[1:]
    std=r.std(ddof=1)
    return {'observations':len(daily),'total_return':float(nav.iloc[-1]-1),
            'annualized_return':float(nav.iloc[-1]**(annual/len(daily))-1),
            'annualized_vol':float(std*np.sqrt(annual)),
            'sharpe':float(r.mean()/std*np.sqrt(annual)) if std>0 else np.nan,
            'max_drawdown':float(np.min(nav.to_numpy()/running_max-1)),
            'avg_turnover':float(daily.turnover.mean()),'total_cost_in_daily_nav_units':float(daily.cost.sum()),
            'blocked_days':int(daily.blocked_rebalance.sum()),'terminal_held_count':int(daily.held_count.iloc[-1])}

def ic_metrics(ic):
    metrics={}
    for h in (1,3,5):
        v=ic[f'ic_{h}'].dropna(); sd=v.std(ddof=1)
        metrics.update({f'ic_{h}_mean':v.mean(),f'ic_{h}_ir':v.mean()/sd if sd>0 else np.nan,
                        f'ic_{h}_hit':(v>0).mean(),f'ic_{h}_days':len(v)})
    return metrics

def select_candidates(metrics,count):
    m=metrics.copy()
    valid=m[['sharpe','ic_1_mean','ic_1_ir']].notna().all(axis=1)
    m['selection_score']=np.nan
    m.loc[valid,'selection_score']=(m.loc[valid,['sharpe','ic_1_mean','ic_1_ir']].rank(pct=True).mean(axis=1)
                                     +.25*m.loc[valid,'avg_turnover'].rank(pct=True,ascending=False))
    return m.sort_values(['selection_score','factor'],ascending=[False,True]), m.loc[valid].sort_values(['selection_score','factor'],ascending=[False,True]).head(count).factor.tolist()

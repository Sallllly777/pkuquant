import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import unittest
import tempfile
import numpy as np
import pandas as pd
from research_core import load_panel,build_features,rank_ic,simulate,nav_metrics,weights,fees

TEMP_ROOT=Path(__file__).resolve().parents[1]/'.cache/tests'
TEMP_ROOT.mkdir(parents=True,exist_ok=True)

ZERO={'commission_bps':0.,'slippage_bps':0.,'sell_extra_bps':0.,'short_borrow_annual_bps':0.}

def panel(days=12,symbols=12):
    dates=pd.date_range('2020-01-01',periods=days,freq='B')
    rows=[]
    for d,dt in enumerate(dates):
        for s in range(symbols):
            price=100+d+s
            rows.append(dict(datetime=dt,symbol=f'S{s:02}',open=price,high=price+2,low=price-2,close=price+(s%3-1)*.5,volume=1000,turn=2,source_present=True))
    return pd.DataFrame(rows).set_index(['datetime','symbol'])

class ResearchTests(unittest.TestCase):
    def test_missing_turn_does_not_delete_price(self):
        df=panel().reset_index(); df.loc[2,'turn']=np.nan
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            self.assertTrue(Path(td).resolve().is_relative_to(TEMP_ROOT.resolve()))
            path=Path(td)/'input.csv'; df.to_csv(path,index=False)
            loaded,q=load_panel(path)
        self.assertEqual(len(loaded),len(df)); self.assertEqual(q['missing_turn_source_rows'],1)
    def test_missing_calendar_day_not_spliced(self):
        p=panel(); date=p.index.levels[0][4]; p=p.drop((date,'S00'))
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            self.assertTrue(Path(td).resolve().is_relative_to(TEMP_ROOT.resolve()))
            path=Path(td)/'input.csv'; p.reset_index().to_csv(path,index=False)
            p,_=load_panel(path)
        f=build_features(p); previous=p.index.levels[0][3]
        self.assertTrue(np.isnan(f.loc[(previous,'S00'),'fwd_1']))
    def test_factor_missing_does_not_change_label(self):
        p=panel(); f=build_features(p)
        p.loc[(p.index.levels[0][4],'S00'),'turn']=np.nan
        other=build_features(p)
        pd.testing.assert_series_equal(f.fwd_1,other.fwd_1)
    def test_future_data_does_not_change_past_factor(self):
        p=panel(90); a=build_features(p); cutoff=p.index.levels[0][60]
        p.loc[p.index.get_level_values('datetime')>cutoff,'close']*=2
        b=build_features(p)
        cols=[c for c in a if c.startswith('O')]
        pd.testing.assert_frame_equal(a.loc[:cutoff,cols],b.loc[:cutoff,cols])
    def test_horizon_three_uses_exact_calendar_end(self):
        f=build_features(panel()); g=f.xs('S00',level='symbol')
        self.assertAlmostEqual(g.fwd_3.iloc[0],g.close.iloc[3]/g.close.iloc[0]-1)
        self.assertEqual(g.label_end_3.iloc[0],g.index[3])
    def test_ic_purges_cross_boundary_labels(self):
        f=build_features(panel()); dates=f.index.levels[0]
        ic=rank_ic(f,'O02_low_location_3d',str(dates[0].date()),str(dates[7].date()))
        self.assertEqual(ic.n_5.iloc[-1],0); self.assertEqual(ic.n_3.iloc[-2],0)
    def test_first_loss_in_drawdown(self):
        d=pd.DataFrame(dict(net=[-.1,0],nav=[.9,.9],turnover=[0,0],cost=[0,0],blocked_rebalance=[0,0],held_count=[0,0]))
        self.assertAlmostEqual(nav_metrics(d)['max_drawdown'],-.1)
    def test_full_traded_notional_cost(self):
        f=fees(np.array([.5,-.5]),np.array([1.,1.]),dict(commission_bps=10,slippage_bps=0,sell_extra_bps=0))
        self.assertAlmostEqual(f['commission'],.001)
    def test_constant_signal_does_not_create_arbitrary_portfolio(self):
        self.assertFalse(weights(np.ones(12),np.ones(12,dtype=bool)).any())
    def test_weight_gross_one(self):
        w=weights(np.arange(12),np.ones(12,dtype=bool))
        self.assertAlmostEqual(abs(w).sum(),1); self.assertAlmostEqual(w.sum(),0)
    def test_next_open_lag_and_liquidation(self):
        p=panel(8); f=build_features(p); f['score']=np.tile(np.arange(12),8)
        dates=f.index.levels[0]
        d=simulate(f,'score',str(dates[0].date()),str(dates[-1].date()),ZERO,mode='long_only')
        self.assertEqual(d.held_count.iloc[0],0)
        self.assertGreater(d.held_count.iloc[1],0)
        self.assertEqual(d.held_count.iloc[-1],0)
        self.assertGreater(d.traded_notional.iloc[-1],0)
    def test_cost_book_self_financing(self):
        f=build_features(panel()); f['score']=np.tile(np.arange(12),12)
        dates=f.index.levels[0]; cost={**ZERO,'commission_bps':20}
        d=simulate(f,'score',str(dates[0].date()),str(dates[-1].date()),cost,mode='long_only')
        self.assertGreater(d.cost.iloc[1],0); self.assertGreater(d.cost.iloc[-1],0)
        self.assertGreaterEqual(d.cash.min(),-1e-10)
        np.testing.assert_allclose((1+d.net).cumprod(),d.nav)
    def test_unknown_future_return_does_not_filter_selection(self):
        f=build_features(panel()); f['score']=np.tile(np.arange(12),12)
        dates=f.index.levels[0]
        a=simulate(f,'score',str(dates[0].date()),str(dates[-1].date()),ZERO)
        f['fwd_1']=np.nan
        b=simulate(f,'score',str(dates[0].date()),str(dates[-1].date()),ZERO)
        pd.testing.assert_frame_equal(a,b)
    def test_missing_quote_keeps_calendar_and_blocks_held_rebalance(self):
        f=build_features(panel()); f['score']=np.tile(np.arange(12),12); dates=f.index.levels[0]
        f.loc[(dates[4],'S11'),'open']=np.nan
        d=simulate(f,'score',str(dates[0].date()),str(dates[-1].date()),ZERO,mode='long_only')
        self.assertEqual(len(d),len(dates)); self.assertEqual(d.blocked_rebalance.iloc[4],1)
    def test_zero_range_no_infinity(self):
        p=panel(); p['high']=p['low']; f=build_features(p)
        self.assertFalse(np.isinf(f.filter(regex='^O').to_numpy()).any())
    def test_new_interaction_versions_have_declared_direction(self):
        from research_core import factor_values
        g=panel(90).xs('S00',level='symbol')
        g['close']=100.+np.sin(np.arange(90))
        g['low']=g.close-1.; g['high']=g.close+3.
        f=factor_values(g)
        # L3=.25, S=.75. The old O13=-L3*RV; the new O13=S*RV.
        self.assertLess(f['O13_low_close_high_vol'].iloc[-1],0)
        self.assertAlmostEqual(f['O13v2_low_strength_relative_vol_3d'].iloc[-1],-3*f['O13_low_close_high_vol'].iloc[-1])
    def test_selected_ids_do_not_depend_on_input_row_order(self):
        from research_core import select_candidates
        m=pd.DataFrame({'factor':['B','A','C'],'sharpe':[1,1,0],'ic_1_mean':[.1,.1,.0],
                        'ic_1_ir':[1,1,0],'avg_turnover':[.1,.1,.2]})
        self.assertEqual(select_candidates(m,2)[1],['A','B'])
        self.assertEqual(select_candidates(m.iloc[::-1],2)[1],['A','B'])

if __name__=='__main__': unittest.main()

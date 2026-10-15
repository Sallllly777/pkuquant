import sys
from pathlib import Path
import unittest
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from evaluate_forward import recorded_features,evaluate_modes

class ForwardTests(unittest.TestCase):
    def panel(self):
        index=pd.MultiIndex.from_product([pd.date_range('2026-10-12',periods=3,freq='B'),['A','B']],names=['datetime','symbol'])
        return pd.DataFrame({'open':100.,'volume':1.},index=index)
    def record(self):
        return {'signal_date':'2026-10-12','recorded_at_utc':'2026-10-12T08:00:00+00:00','freeze_sha256':'frozen',
                'signals':{'factor':[{'symbol':'A','score':1.},{'symbol':'B','score':2.}]}}
    def test_only_recorded_scores_used(self):
        f=recorded_features(self.panel(),[self.record()],['factor'],'frozen')
        self.assertEqual(f.loc[('2026-10-12','B'),'factor'],2.)
        self.assertTrue(f.loc['2026-10-13','factor'].isna().all())
    def test_post_open_backfill_rejected(self):
        r=self.record(); r['recorded_at_utc']='2026-10-13T02:00:00+00:00'
        with self.assertRaisesRegex(ValueError,'before next open'): recorded_features(self.panel(),[r],['factor'],'frozen')
    def test_different_experiment_rejected(self):
        with self.assertRaisesRegex(ValueError,'different freeze'): recorded_features(self.panel(),[self.record()],['factor'],'changed')
    def test_long_short_gain_does_not_disguise_long_only_loss(self):
        panel=self.panel(); panel.loc[('2026-10-14','A'),'open']=80.; panel.loc[('2026-10-14','B'),'open']=95.
        features=recorded_features(panel,[self.record()],['factor'],'frozen')
        frozen={'selection':['factor'],'config':{'quantile_fraction':.5,'minimum_cross_section':2,
                'cost':{'commission_bps':0.,'slippage_bps':0.,'sell_extra_bps':0.,'short_borrow_annual_bps':0.}}}
        daily,metrics=evaluate_modes(features,frozen,'2026-10-12','2026-10-14')
        values=metrics.set_index('mode').total_return
        self.assertAlmostEqual(values['long_short'],.075)
        self.assertAlmostEqual(values['long_only'],-.05)
        self.assertAlmostEqual(values['equal_weight'],-.125)
        self.assertTrue(metrics.terminal_held_count.eq(0).all())

    def test_baseline_does_not_trade_before_first_signal(self):
        panel=self.panel()
        panel.loc['2026-10-12','open']=50.
        features=recorded_features(panel,[self.record()],['factor'],'frozen')
        frozen={'selection':['factor'],'config':{'quantile_fraction':.5,'minimum_cross_section':2,
                'cost':{'commission_bps':3.,'slippage_bps':2.,'sell_extra_bps':10.,'short_borrow_annual_bps':200.}}}
        daily,metrics=evaluate_modes(features,frozen,'2026-10-12','2026-10-14')
        baseline=daily[daily['mode'].eq('equal_weight')].reset_index(drop=True)
        self.assertEqual(baseline.loc[0,'nav'],1.)
        self.assertEqual(baseline.loc[0,'held_count'],0)
        self.assertEqual(baseline.loc[0,'cost'],0.)
        self.assertEqual(baseline.loc[1,'held_count'],2)
        self.assertEqual(baseline.loc[2,'held_count'],0)
        self.assertTrue(baseline.gross.eq(0.).all())
        self.assertGreater(baseline.cost.sum(),0.)
        self.assertLess(metrics.set_index('mode').loc['equal_weight','total_return'],0.)

if __name__=='__main__': unittest.main()

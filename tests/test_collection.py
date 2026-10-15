import sys
from pathlib import Path
from datetime import datetime
import unittest
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from collect_forward import FIELDS,TZ,completed_day,validate_chunk


class CollectionTests(unittest.TestCase):
    def calendar(self):
        return pd.DataFrame({'calendar_date':['2026-10-11','2026-10-12','2026-10-13'], 'is_trading_day':['0','1','1']})
    def test_midday_cannot_record(self):
        with self.assertRaisesRegex(ValueError,'18:00'):
            completed_day(self.calendar(),datetime(2026,10,13,12,tzinfo=TZ),False)
    def test_midday_observation_uses_prior_day(self):
        self.assertEqual(completed_day(self.calendar(),datetime(2026,10,13,12,tzinfo=TZ),True),'2026-10-12')
    def test_after_close_uses_today(self):
        self.assertEqual(completed_day(self.calendar(),datetime(2026,10,13,21,tzinfo=TZ),False),'2026-10-13')
    def test_holiday_never_backfills(self):
        with self.assertRaisesRegex(ValueError,'not a provider trading day'):
            completed_day(self.calendar(),datetime(2026,10,11,21,tzinfo=TZ),False)
    def empty(self):
        return pd.DataFrame(columns=FIELDS.split(','))
    def test_unknown_missing_stock_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unexplained missing'):
            validate_chunk(self.empty(),'sh.600000',['2026-10-12'],{'outDate':''})
    def test_retired_stock_keeps_blank_prices(self):
        data,count=validate_chunk(self.empty(),'sh.600068',['2026-10-12'],{'outDate':'2021-09-13'})
        self.assertEqual(count,1); self.assertEqual(data.iloc[0]['close'],'')
        self.assertEqual(data.iloc[0]['volume'],'0'); self.assertEqual(data.iloc[0]['code'],'sh.600068')
    def test_retirement_does_not_explain_prior_gap(self):
        with self.assertRaisesRegex(ValueError,'Unexplained missing'):
            validate_chunk(self.empty(),'sh.600068',['2026-10-12'],{'outDate':'2026-10-14'})
    def test_duplicate_provider_rows_rejected(self):
        row={k:'' for k in FIELDS.split(',')}; row.update(code='sh.600000',date='2026-10-12')
        with self.assertRaisesRegex(ValueError,'duplicate'):
            validate_chunk(pd.DataFrame([row,row]),'sh.600000',['2026-10-12'],{})


if __name__=='__main__': unittest.main()

import json
import sys
import tempfile
from datetime import datetime,timezone
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from research_control import claim_holdout,validate_forward_date,verify_freeze
from report_v2 import selected_names
from research_core import file_hash
TEMP_ROOT=Path(__file__).resolve().parents[1]/'.cache/tests'
TEMP_ROOT.mkdir(parents=True,exist_ok=True)

class ControlTests(unittest.TestCase):
    def test_holdout_second_access_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            p=Path(td)/'access.json'; claim_holdout(p,'freeze','data')
            with self.assertRaises(FileExistsError): claim_holdout(p,'freeze','changed_data')
            self.assertEqual(json.loads(p.read_text())['input_sha256'],'data')
    def test_forward_cannot_backdate(self):
        now=datetime(2026,10,10,9,tzinfo=timezone.utc)
        with self.assertRaises(ValueError): validate_forward_date('2026-10-09','2026-10-09T13:00:00+00:00',now)
    def test_forward_cannot_record_before_close(self):
        with self.assertRaises(ValueError): validate_forward_date('2026-10-10','2026-10-09T13:00:00+00:00',datetime(2026,10,10,3,tzinfo=timezone.utc))
    def test_forward_same_day_after_close(self):
        validate_forward_date('2026-10-12','2026-10-09T13:00:00+00:00',datetime(2026,10,12,9,tzinfo=timezone.utc))
    def test_report_uses_designated_order_without_reselection(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            p=Path(td)/'selection.json'; p.write_text(json.dumps({'selection':['weak','strong']}))
            self.assertEqual(selected_names(p),['weak','strong'])
    def test_frozen_source_change_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            root=Path(td); code=root/'core.py'; code.write_text('old')
            f=root/'freeze.json'; f.write_text(json.dumps({'source_sha256':{'core.py':file_hash(code)}}))
            code.write_text('new')
            with self.assertRaisesRegex(ValueError,'Frozen source changed'): verify_freeze(f,root)

if __name__=='__main__': unittest.main()

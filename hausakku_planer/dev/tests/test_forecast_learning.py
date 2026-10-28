"""Tests use explicit candidate fixtures, not claimed real-world improvements."""
import copy,unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from forecast_learning import apply_learning,public_model_summary,snapshot_observations
TZ=ZoneInfo('Europe/Berlin')

def example():
    snapshot={'collected_at':'2026-10-18T20:15:10+02:00'}
    data={'intervals':[{'start':datetime(2026,10,18,21,tzinfo=TZ),'end':datetime(2026,10,18,21,15,tzinfo=TZ),'load_kwh':.25,'pv_kwh':.5}],
          'pv_totals_corrected_kwh':{'2026-10-18':2.,'2026-10-19':4.},'pv_calibration':{'factor':2.,'pairs':7}}
    artifact={'as_of':snapshot['collected_at'],'trained_before':'2026-10-18T00:00:00+02:00',
        'selected_model':{'load':'median7','pv':'ratio7'},
        'load':{'is_baseline':False,'available':True,'models':{'median7':{'values':[[2.]*24 for _ in range(7)]}}},
        'pv':{'is_baseline':False,'models':{'ratio7':{'factor':3.}}},
        'backtest':{k:{'promoted':True,'reason':'test fixture passed','validation':{'days':14,'improvement_fraction':.2},'test':{'days':14,'improvement_fraction':.1}} for k in ('load','pv')},
        'coverage':{'complete_load_days':40,'pv_pairs':40}}
    return data,snapshot,artifact

class LearningApplicationTests(unittest.TestCase):
    def test_promoted_models_apply_actual_interval_energy(self):
        d,s,a=example();out,meta=apply_learning(d,s,a)
        self.assertEqual(out['intervals'][0]['load_kwh'],.5)
        self.assertEqual(out['intervals'][0]['pv_kwh'],.75)
        self.assertEqual(out['pv_totals_corrected_kwh']['2026-10-19'],6)
        self.assertEqual(meta['load'],'median7');self.assertTrue(meta['applied']['pv'])
        self.assertEqual(d['intervals'][0]['load_kwh'],.25)
    def test_insufficient_evidence_preserves_exact_operational_baseline(self):
        d,s,a=example()
        for channel in ('load','pv'):
            a[channel]['is_baseline']=True;a['backtest'][channel]['promoted']=False
        out,meta=apply_learning(d,s,a)
        self.assertEqual(out['intervals'],d['intervals']);self.assertEqual(out['pv_totals_corrected_kwh'],d['pv_totals_corrected_kwh'])
        self.assertFalse(any(meta['applied'].values()))
    def test_missing_artifact_keeps_planning_available(self):
        d,s,a=example();out,meta=apply_learning(d,s,None)
        self.assertEqual(out['intervals'],d['intervals']);self.assertIn('no_artifact',meta['warnings'])
    def test_future_artifact_cannot_leak_into_old_snapshot(self):
        d,s,a=example();a['as_of']='2026-10-19T20:15:10+02:00'
        out,meta=apply_learning(d,s,a)
        self.assertEqual(out['intervals'],d['intervals']);self.assertIn('future_artifact',meta['warnings'])
    def test_stale_training_cannot_promote_new_candidate(self):
        d,s,a=example();a['trained_before']='2026-10-17T00:00:00+02:00'
        out,meta=apply_learning(d,s,a)
        self.assertEqual(out['intervals'],d['intervals']);self.assertIn('stale_training_cutoff',meta['warnings'])
    def test_candidate_application_failure_is_channel_atomic(self):
        d,s,a=example();a['load']['models']['median7']['values'][6][21]=None
        out,meta=apply_learning(d,s,a)
        self.assertEqual(out['intervals'][0]['load_kwh'],.25)
        self.assertTrue(meta['applied']['pv']);self.assertIn('load_candidate_rejected',meta['warnings'])
    def test_extreme_pv_factor_not_allowed_into_plan(self):
        d,s,a=example();a['pv']['models']['ratio7']['factor']=50.
        out,meta=apply_learning(d,s,a)
        self.assertEqual(out['intervals'][0]['pv_kwh'],.5);self.assertIn('pv_candidate_rejected',meta['warnings'])
    def test_public_summary_exposes_reasons_without_full_models(self):
        d,s,a=example();out,meta=apply_learning(d,s,a);text=public_model_summary(meta)
        self.assertIn('median7',text);self.assertNotIn('values',text)
    def test_sparse_pv_baseline_reports_actual_applied_factor_one(self):
        d,s,a=example();d['pv_calibration']={'factor':7,'pairs':2}
        out,meta=apply_learning(d,s,None)
        self.assertEqual(out['pv_calibration']['applied_factor'],1.)
    def test_snapshot_fallback_observations_keep_missing_pv_missing(self):
        snap={'planning_start':'2026-10-19T20:15:00+02:00','balances':[{'start':1792317600.,'grid':1,'wr':.5,'charger':.1,'export':0,'ev':.2}], 'raw':{'energy':{'data':{'entities':[]}}}}
        data=snapshot_observations(snap)
        self.assertAlmostEqual(data['hours'][0]['load_kwh'],1.2)
        self.assertIsNone(data['hours'][0]['pv_kwh'])
class RefreshTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import asyncio
        asyncio.get_running_loop().slow_callback_duration=10
    async def test_refresh_saves_versioned_model_and_latest_backtest(self):
        import tempfile,json
        from pathlib import Path
        from unittest.mock import AsyncMock,patch
        from forecast_learning import refresh_learning
        snapshot={'collected_at':'2026-10-18T20:15:10+02:00'}
        dataset={'cutoff':'2026-10-18T00:00:00+02:00','hours':[],'pv_forecasts':[],'coverage':{}}
        with tempfile.TemporaryDirectory() as temp,patch('annual_data.collect',new_callable=AsyncMock,return_value=dataset) as collect:
            data,artifact=await refresh_learning(snapshot,Path(temp))
            self.assertEqual(data,dataset)
            self.assertFalse(collect.call_args.kwargs['require_disabled'])
            latest=json.loads((Path(temp)/'model.json').read_text())
            self.assertEqual(latest,artifact)
            self.assertEqual(json.loads((Path(temp)/'models'/f"{artifact['artifact_id']}.json").read_text()),artifact)
            self.assertEqual(json.loads((Path(temp)/'backtest.json').read_text()),artifact['backtest'])

if __name__=='__main__':unittest.main()

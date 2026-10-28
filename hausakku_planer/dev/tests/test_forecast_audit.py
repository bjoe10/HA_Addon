import json,sqlite3,tempfile,unittest
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from forecast_audit import archive_forecast,score_forecasts,audit_summary
TZ=ZoneInfo('Europe/Berlin')

def sample(day='2026-10-18',issue=None):
    start=datetime.fromisoformat(day).replace(hour=12,tzinfo=TZ)
    issue=issue or (start-timedelta(days=1)).isoformat()
    rows=[{'start':(start+timedelta(minutes=i*15)).isoformat(),'end':(start+timedelta(minutes=(i+1)*15)).isoformat(),'load_kwh':.25,'pv_kwh':.5} for i in range(4)]
    plan={'created_at':issue,'plan':{'intervals':rows},'inputs':{'pv_totals_corrected_kwh':{day:4.}},'forecast_model':{'load':'baseline','pv':'baseline'},
          'forecast_baseline':{'intervals':[dict(r,load_kwh=.5,pv_kwh=.25) for r in rows],'pv_totals_corrected_kwh':{day:3.}}}
    snapshot={'collected_at':issue}
    return plan,snapshot,start

def actual_day(day,pv_per_hour=.1,load_per_hour=.8):
    d=datetime.fromisoformat(day).replace(tzinfo=TZ);t=d.timestamp();end=(d+timedelta(days=1)).timestamp();out=[]
    while t<end:out.append({'start':t,'pv_kwh':pv_per_hour,'load_kwh':load_per_hour});t+=3600
    return out

class ArchiveTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'audit.sqlite'
    def tearDown(self):self.tmp.cleanup()
    def test_archive_and_score_real_future_targets(self):
        p,s,t=sample();event=archive_forecast(self.path,p,s)
        data={'hours':actual_day('2026-10-18'),'cutoff':'2026-10-19T00:00:00+02:00'}
        result=score_forecasts(self.path,data,datetime(2026,10,19,tzinfo=TZ))
        self.assertEqual(result['new_scores'],3)
        summ=audit_summary(self.path);self.assertEqual(summ['issued_forecasts'],1)
        self.assertAlmostEqual(summ['metrics']['load_hour']['mae_kwh'],.2)
        self.assertAlmostEqual(summ['metrics']['load_hour']['baseline_mae_kwh'],1.2)
        self.assertAlmostEqual(summ['metrics']['pv_day']['bias_kwh'],1.6)
    def test_same_issue_is_idempotent(self):
        p,s,t=sample();a=archive_forecast(self.path,p,s);b=archive_forecast(self.path,p,s)
        self.assertEqual(a,b);self.assertEqual(audit_summary(self.path)['issued_forecasts'],1)
    def test_incomplete_hour_is_not_called_full_hour_forecast(self):
        p,s,t=sample();p['plan']['intervals'].pop(0);archive_forecast(self.path,p,s)
        score_forecasts(self.path,{'hours':actual_day('2026-10-18'),'cutoff':'2026-10-19T00:00:00+02:00'},datetime(2026,10,19,tzinfo=TZ))
        self.assertNotIn('load_hour',audit_summary(self.path)['metrics'])
    def test_past_predictions_not_backdated_into_archive(self):
        p,s,t=sample(issue='2026-10-18T12:30:00+02:00');archive_forecast(self.path,p,s)
        self.assertEqual(audit_summary(self.path)['targets'],0)
    def test_missing_observations_are_pending_not_zero(self):
        p,s,t=sample();archive_forecast(self.path,p,s)
        score_forecasts(self.path,{'hours':[],'cutoff':'2026-10-19T00:00:00+02:00'},datetime(2026,10,19,tzinfo=TZ))
        summ=audit_summary(self.path);self.assertEqual(summ['scored_targets'],0);self.assertEqual(summ['pending_targets'],3)
    def test_scoring_never_uses_unfinished_today(self):
        p,s,t=sample();archive_forecast(self.path,p,s)
        score_forecasts(self.path,{'hours':actual_day('2026-10-18'),'cutoff':'2026-10-19T00:00:00+02:00'},datetime(2026,10,18,20,tzinfo=TZ))
        self.assertEqual(audit_summary(self.path)['scored_targets'],0)
    def test_scoring_idempotent(self):
        p,s,t=sample();archive_forecast(self.path,p,s)
        data={'hours':actual_day('2026-10-18'),'cutoff':'2026-10-19T00:00:00+02:00'}
        score_forecasts(self.path,data,datetime(2026,10,19,tzinfo=TZ))
        self.assertEqual(score_forecasts(self.path,data,datetime(2026,10,20,tzinfo=TZ))['new_scores'],0)
    def test_dst_short_day_accepts_exact_23_hours(self):
        p,s,t=sample('2026-03-29');archive_forecast(self.path,p,s)
        result=score_forecasts(self.path,{'hours':actual_day('2026-03-29'),'cutoff':'2026-03-30T00:00:00+02:00'},datetime(2026,3,30,tzinfo=TZ))
        self.assertEqual(result['new_scores'],3)
    def test_missing_day_hour_blocks_daily_pv_score(self):
        p,s,t=sample();archive_forecast(self.path,p,s);rows=actual_day('2026-10-18');rows.pop(0)
        score_forecasts(self.path,{'hours':rows,'cutoff':'2026-10-19T00:00:00+02:00'},datetime(2026,10,19,tzinfo=TZ))
        self.assertNotIn('pv_day',audit_summary(self.path)['metrics'])
    def test_nan_prediction_rejected(self):
        p,s,t=sample();p['plan']['intervals'][0]['load_kwh']=float('nan')
        with self.assertRaises(ValueError):archive_forecast(self.path,p,s)
    def test_conflicting_actual_duplicates_rejected(self):
        p,s,t=sample();archive_forecast(self.path,p,s);rows=actual_day('2026-10-18');rows.append(dict(rows[0],pv_kwh=99))
        with self.assertRaises(ValueError):score_forecasts(self.path,{'hours':rows},datetime(2026,10,19,tzinfo=TZ))
    def test_archive_keeps_confirmed_ac_meter_provenance(self):
        p,s,t=sample();s['ev_source']='sensor.cee_energy';archive_forecast(self.path,p,s)
        with sqlite3.connect(self.path) as con:meta=json.loads(con.execute('SELECT metadata FROM issues').fetchone()[0])
        self.assertEqual(meta['ev_source'],'sensor.cee_energy')
    def test_database_contains_no_raw_ha_states(self):
        p,s,t=sample();s['private_source_url']='DO_NOT_STORE';archive_forecast(self.path,p,s)
        self.assertNotIn('DO_NOT_STORE',self.path.read_bytes().decode(errors='ignore'))
if __name__=='__main__':unittest.main()

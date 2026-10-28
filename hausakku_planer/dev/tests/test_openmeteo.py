import json,tempfile,unittest
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo
import openmeteo
from openmeteo import parse,fit_day,training_days,hourly_pv,apply_radiation,refresh_history,archive_radiation
TZ=ZoneInfo('Europe/Berlin');UTC=timezone.utc

def payload(start,hours,direct=lambda t:0.,diffuse=lambda t:0.):
    times=[];sw=[];di=[];df=[];cc=[]
    for i in range(hours):
        end=start+timedelta(hours=i+1)
        t=(end-timedelta(hours=1)).timestamp()
        times.append(end.strftime('%Y-%m-%dT%H:%M'));d=direct(t);f=diffuse(t)
        di.append(d);df.append(f);sw.append(d+f);cc.append(50.)
    return {'hourly':{'time':times,'shortwave_radiation':sw,'direct_radiation':di,'diffuse_radiation':df,'cloud_cover':cc}}

def sun(t):
    h=datetime.fromtimestamp(t,UTC).hour
    return 400. if 9<=h<=13 else 0.

class OpenMeteoTests(unittest.TestCase):
    def setUp(self):
        start=datetime(2026,1,1,tzinfo=UTC)
        self.history=parse(payload(start,24*300,direct=lambda t:sun(t)*(1+(int(t//86400)%3)),diffuse=lambda t:sun(t)/4))
        hours=[]
        for t,(ghi,direct,diffuse,cloud) in self.history.items():
            hours.append({'start':t,'load_kwh':.2,'pv_kwh':.002*direct+.004*diffuse})
        self.dataset={'hours':hours}
        self.issue=datetime(2026,10,24,20,15,tzinfo=TZ)
    def test_value_is_stored_under_pv_hour_start(self):
        rows=parse(payload(datetime(2026,10,24,10,tzinfo=UTC),1,direct=lambda t:100.))
        self.assertEqual(list(rows),[datetime(2026,10,24,10,tzinfo=UTC).timestamp()])
        self.assertEqual(parse({'hourly':{'time':['2026-10-24T10:00'],'shortwave_radiation':[None],
            'direct_radiation':[1],'diffuse_radiation':[1],'cloud_cover':[1]}}),{})
    def test_fit_recovers_shaded_coefficients_from_past_days_only(self):
        training=training_days(self.dataset,self.history,self.issue)
        self.assertTrue(all(d<self.issue.date() for d in training))
        fit=fit_day(training,date(2026,10,26))
        a,b=fit['coefficients'][11]
        self.assertAlmostEqual(a,.002,places=6);self.assertAlmostEqual(b,.004,places=6)
        self.assertEqual(fit['coefficients'][2],(0.,0.))
        self.assertIsNone(fit_day(dict(list(training.items())[:5]),date(2026,10,26)))
    def test_forecast_hours_are_predicted_and_negative_fit_is_avoided(self):
        forecast={'issued_at':self.issue.isoformat(),'hours':{str(int(k)):v for k,v in
            parse(payload(datetime(2026,10,24,tzinfo=UTC),72,direct=sun,diffuse=lambda t:sun(t)/4)).items()}}
        model=hourly_pv(self.dataset,self.history,forecast,self.issue)
        noon=datetime(2026,10,26,11,tzinfo=UTC).timestamp()
        self.assertAlmostEqual(model['hours'][noon],.002*400+.004*100,places=6)
        self.assertTrue(all(v>=0 for v in model['hours'].values()))
    def test_apply_radiation_replaces_horizon_or_falls_back(self):
        start=datetime(2026,10,25,9,tzinfo=TZ)
        def data():
            return {'intervals':[{'start':start+timedelta(minutes=15*i),'end':start+timedelta(minutes=15*i+15),
                                  'price_eur_kwh':.2,'load_kwh':.1,'pv_kwh':9.} for i in range(8)],
                    'pv_totals_corrected_kwh':{'2026-10-25':9.}}
        forecast={'issued_at':self.issue.isoformat(),'hours':{str(int(k)):v for k,v in
            parse(payload(datetime(2026,10,24,tzinfo=UTC),72,direct=sun,diffuse=lambda t:sun(t)/4)).items()}}
        snapshot={'collected_at':self.issue.isoformat(),'radiation_forecast':forecast}
        d=data();meta=apply_radiation(d,snapshot,self.dataset,self.history)
        self.assertEqual(meta['source'],'openmeteo_radiation')
        hour=datetime(2026,10,25,9,tzinfo=TZ).astimezone(UTC).timestamp()
        self.assertAlmostEqual(d['intervals'][0]['pv_kwh'],meta['hours'][str(int(hour))]/4)
        self.assertAlmostEqual(d['pv_totals_corrected_kwh']['2026-10-25'],sum(r['pv_kwh'] for r in d['intervals']))
        for broken in ({**snapshot,'radiation_forecast':None},{**snapshot,'radiation_forecast':{**forecast,'hours':{}}}):
            d=data();self.assertEqual(apply_radiation(d,broken,self.dataset,self.history)['source'],'ha_solarforecast_ratio')
            self.assertEqual(d['intervals'][0]['pv_kwh'],9.)
        d=data();self.assertIn('warning',apply_radiation(d,snapshot,self.dataset,None))
    def test_history_cache_is_incremental(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'h.json';calls=[]
            def fake(url,params,timeout=30):
                calls.append(params);s=datetime.fromisoformat(params['start_date']).replace(tzinfo=UTC)
                days=(date.fromisoformat(params['end_date'])-date.fromisoformat(params['start_date'])).days+1
                return payload(s,24*days,direct=sun)
            with mock.patch.object(openmeteo,'_get',fake):
                first=refresh_history(path,52.52,13.40,date(2026,1,10))
                second=refresh_history(path,52.52,13.40,date(2026,1,12))
                refresh_history(path,52.52,13.40,date(2026,1,12))
            self.assertEqual(calls[0]['start_date'],'2026-01-01')
            self.assertEqual(calls[1]['start_date'],'2026-01-07')
            self.assertEqual(calls[0]['latitude'],'52.52')
            self.assertGreater(len(second),len(first))
    def test_forecast_vintages_archived_once(self):
        forecast={'issued_at':self.issue.isoformat(),'hours':{'1792800000':[1,1,1,1]}}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'a.sqlite';snap={'collected_at':self.issue.isoformat(),'radiation_forecast':forecast}
            archive_radiation(path,snap);archive_radiation(path,snap)
            from multiday import _db
            with _db(path) as db:self.assertEqual(db.execute('SELECT count(*) FROM radiation').fetchone()[0],1)
            self.assertEqual(archive_radiation(path,{'collected_at':self.issue.isoformat()}),0)
    def test_tail_uses_radiation_hours(self):
        from multiday import build_tail
        from planner_data import prepare
        s=json.loads((Path(__file__).parent/'fixtures/test_fixture_snapshot.json').read_text())
        c=json.loads((Path(__file__).parent.parent/'tests/fixtures/config_legacy.json').read_text())
        d=prepare(s,c);end=d['intervals'][-1]['end']
        hours={end.timestamp()+3600*i:.5 for i in range(72)}
        tail=build_tail(s,d,end,{'hours':[]},[],radiation_pv=hours)
        self.assertEqual(tail['pv_model'],'openmeteo_radiation_calibrated')
        self.assertTrue(all(abs(r['pv_kwh']-.5)<1e-12 for r in tail['rows']))

class MidnightSolarForecastTests(OpenMeteoTests):
    def test_unavailable_ha_pv_is_fine_with_radiation_and_fails_closed_without(self):
        from planner import compute_plan
        s=json.loads((Path(__file__).parent/'fixtures/test_fixture_snapshot.json').read_text())
        c=json.loads((Path(__file__).parent.parent/'tests/fixtures/config_legacy.json').read_text())
        for key in ('sensor.energy_production_today_remaining','sensor.energy_production_tomorrow'):
            s['states'][key]={**s['states'][key],'state':'unavailable'}
        issue=datetime.fromisoformat(s['collected_at'])
        s['radiation_forecast']={'issued_at':s['collected_at'],'hours':{str(int(k)):v for k,v in
            parse(payload(datetime(2026,10,24,tzinfo=UTC),24*6,direct=sun,diffuse=lambda t:sun(t)/4)).items()}}
        plan=compute_plan(s,c,dataset=self.dataset,radiation_history=self.history)
        self.assertEqual(plan['pv_source']['source'],'openmeteo_radiation')
        self.assertGreater(sum(f['pv_kwh'] for f in plan['plan']['intervals']),0)
        with self.assertRaises(ValueError):compute_plan({**s,'radiation_forecast':None},c,dataset=self.dataset,radiation_history=self.history)

if __name__=='__main__':unittest.main()

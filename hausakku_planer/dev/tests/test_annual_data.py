"""Annual read-only training collector acceptance tests."""
import asyncio
from contextlib import redirect_stdout
from io import StringIO
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import annual_data as a
TZ = ZoneInfo('Europe/Berlin')

class AnnualDataTests(unittest.TestCase):
    def test_year_boundary_keeps_90_day_warmup_for_continued_learning(self):
        cutoff=datetime(2027,1,2,tzinfo=TZ)
        self.assertEqual((cutoff-a.training_start(cutoff)).days,90)
        self.assertLess(a.training_start(cutoff).year,cutoff.year)
        self.assertEqual(a.training_start(datetime(2026,10,18,tzinfo=TZ)),datetime(2026,1,1,tzinfo=TZ))

    def test_month_chunks_are_local_calendar_and_cutoff(self):
        chunks = a.month_chunks(datetime(2026,1,1,tzinfo=TZ),datetime(2026,4,2,tzinfo=TZ))
        self.assertEqual(len(chunks),4)
        self.assertEqual(chunks[2][1].isoformat(),'2026-04-01T00:00:00+02:00')

    def test_milliseconds_units_missing_and_pv_only_union(self):
        t = datetime(2026,1,2,tzinfo=TZ).timestamp()
        def response(key,value,unit='kWh',field='change',stamp=t):
            return {'data':{'entities':[{'entity_id':a.ENERGY.get(key,a.EV),'unit_of_measurement':unit,'statistics':[{'start':stamp*1000,field:value}]}]}}
        batches = [response('grid',3),response('wr',2),response('charger',500,'Wh'),response('export',.2),response('ev',1000,'Wh','change'),response('pv',1500,'Wh'),response('pv',2000,'Wh',stamp=t+3600)]
        d=a.build_dataset(batches,[],datetime(2026,1,1,tzinfo=TZ),datetime(2026,1,3,tzinfo=TZ),'kWh')
        self.assertEqual(d['hours'],[{'start':t,'load_kwh':3.3,'pv_kwh':1.5},{'start':t+3600,'load_kwh':None,'pv_kwh':2.0}])

    def test_ev_source_is_confirmed_cee_ac_energy(self):
        self.assertEqual(a.EV,'sensor.cee_energy')
        t=datetime(2026,1,1,tzinfo=TZ).timestamp()
        rows=[]
        for entity,value in [(a.ENERGY['grid'],3.),(a.ENERGY['wr'],1.),(a.ENERGY['charger'],.5),(a.ENERGY['export'],0.),('sensor.cee_energy',1.)]:
            rows.append({'entity_id':entity,'unit_of_measurement':'kWh','statistics':[{'start':t*1000,'change':value}]})
        rows.append({'entity_id':'sensor.car_charger_power','unit_of_measurement':'kW','statistics':[{'start':t*1000,'mean':99.}]})
        dataset=a.build_dataset([{'entities':rows}],[],datetime(2026,1,1,tzinfo=TZ),datetime(2026,1,2,tzinfo=TZ),'kWh')
        self.assertEqual(dataset['hours'][0]['load_kwh'],2.5)

    def test_city_el_is_subtracted_like_tesla_and_missing_hours_stay_missing(self):
        t=datetime(2026,10,1,tzinfo=TZ).timestamp()
        rows=[]
        for entity,values in [(a.ENERGY['grid'],[3.,3.,3.]),(a.ENERGY['wr'],[1.,1.,1.]),(a.ENERGY['charger'],[0.,0.,0.]),
                              (a.ENERGY['export'],[0.,0.,0.]),('sensor.cee_energy',[1.,1.,1.])]:
            rows.append({'entity_id':entity,'unit_of_measurement':'kWh','statistics':[{'start':(t+3600*i)*1000,'change':v} for i,v in enumerate(values)]})
        # City El starts recording in hour 1 and misses hour 2.
        rows.append({'entity_id':'sensor.second_ev_energy','unit_of_measurement':'Wh','statistics':[{'start':(t+3600)*1000,'change':500}]})
        d=a.build_dataset([{'entities':rows}],[],datetime(2026,10,1,tzinfo=TZ),datetime(2026,10,2,tzinfo=TZ),'kWh')
        loads=[h['load_kwh'] for h in d['hours'][:3]]
        self.assertEqual(loads,[3.,2.5,None])
        self.assertIn('sensor.second_ev_energy',a.EXTRA_VEHICLES)

    def test_forecast_latest_preceding_evening_no_leakage(self):
        times=['2026-01-01T15:59:00+01:00','2026-01-01T16:00:00+01:00','2026-01-01T20:15:00+01:00','2026-01-01T20:15:01+01:00','2026-01-02T10:00:00+01:00']
        raw={'data':{'entities':[{'entity_id':a.FORECAST,'states':[{'state':str(i),'last_updated':t} for i,t in enumerate(times)]}]}}
        d=a.build_dataset([], [raw], datetime(2026,1,1,tzinfo=TZ),datetime(2026,1,3,tzinfo=TZ),'kWh')
        self.assertEqual(d['pv_forecasts'],[{'issued_at':times[2],'target_date':'2026-01-02','predicted_kwh':2.0}])

    def test_duplicate_detection_conflicts_rejected_exact_counted(self):
        t=datetime(2026,1,1,tzinfo=TZ).timestamp()
        raw={'data':{'entities':[{'entity_id':a.ENERGY['pv'],'unit_of_measurement':'kWh','statistics':[{'start':t*1000,'change':1}]*2}]}}
        d=a.build_dataset([raw],[],datetime(2026,1,1,tzinfo=TZ),datetime(2026,1,2,tzinfo=TZ),'kWh')
        self.assertEqual(d['coverage']['exact_duplicate_statistics'],1)
        raw['data']['entities'][0]['statistics'].append({'start':t*1000,'change':2})
        with self.assertRaises(ValueError): a.build_dataset([raw],[],datetime(2026,1,1,tzinfo=TZ),datetime(2026,1,2,tzinfo=TZ),'kWh')

    def test_dst_full_days_and_missing_not_zero(self):
        for day,following,count in [(29,30,23)]:
            start=datetime(2026,3,day,tzinfo=TZ);end=datetime(2026,3,following,tzinfo=TZ)
            stats=[{'start':t*1000,'change':0} for t in range(int(start.timestamp()),int(end.timestamp()),3600)]
            raw={'entities':[{'entity_id':a.ENERGY['pv'],'unit_of_measurement':'kWh','statistics':stats}]}
            d=a.build_dataset([raw],[],start,end,'kWh')
            self.assertEqual(len(d['hours']),count)
            self.assertEqual(d['coverage']['pv_complete_days'],1)
            self.assertEqual(d['coverage']['load_hours'],0)
        self.assertEqual(a.expected_hours(datetime(2026,10,25,tzinfo=TZ),datetime(2026,10,26,tzinfo=TZ)),25)

    def test_truncation_subdivides_and_cache_reuses_same_bounds(self):
        class Fake:
            def __init__(self): self.calls=0
            async def call(self,name,**args):
                self.calls+=1
                lo=datetime.fromisoformat(args['start_time']);hi=datetime.fromisoformat(args['end_time'])
                return {'entities':[{'entity_id':'x','has_more':hi.timestamp()-lo.timestamp()>3600,'statistics':[]}]}
        async def run():
            fake=Fake()
            with tempfile.TemporaryDirectory() as tmp:
                start=datetime(2026,1,1,tzinfo=TZ);end=datetime(2026,1,1,2,tzinfo=TZ)
                batches=await a.fetch_cached(fake,Path(tmp),'test',{'source':'statistics','entity_ids':['x']},start,end)
                self.assertEqual(len(batches),2)
                self.assertEqual(fake.calls,3)
                await a.fetch_cached(fake,Path(tmp),'test',{'source':'statistics','entity_ids':['x']},start,end)
                self.assertEqual(fake.calls,3)
        with redirect_stdout(StringIO()):asyncio.run(run())

    def test_nonfinite_negative_missing_incomplete_rejected(self):
        start=datetime(2026,1,1,tzinfo=TZ);end=datetime(2026,1,2,tzinfo=TZ);t=start.timestamp()
        raw={'entities':[{'entity_id':a.ENERGY['pv'],'unit_of_measurement':'kWh','statistics':[{'start':t*1000,'change':None},{'start':(t+3600)*1000,'change':-1},{'start':(t+7200)*1000,'change':float('nan')},{'start':end.timestamp()*1000,'change':1}]}]}
        d=a.build_dataset([raw],[],start,end,'kWh')
        self.assertEqual(d['hours'],[])
        self.assertEqual(d['coverage']['expected_hours'],24)

    def test_rejection_quality_is_attributed_to_component(self):
        start=datetime(2026,1,1,tzinfo=TZ);end=datetime(2026,1,2,tzinfo=TZ)
        raw={'entities':[{'entity_id':a.ENERGY['pv'],'unit_of_measurement':'Wh','statistics':[{'start':start.timestamp()*1000,'change':-100}]}]}
        d=a.build_dataset([raw],[],start,end,'kWh')
        self.assertEqual(d['coverage']['rejected_statistics_by_entity'],{a.ENERGY['pv']:1})

    def test_small_observed_negative_noise_matches_operational_20wh_tolerance(self):
        start=datetime(2026,1,1,tzinfo=TZ);end=datetime(2026,1,2,tzinfo=TZ)
        raw={'entities':[{'entity_id':a.ENERGY['pv'],'unit_of_measurement':'Wh','statistics':[{'start':start.timestamp()*1000,'change':-7},{'start':(start.timestamp()+3600)*1000,'change':-21}]}]}
        d=a.build_dataset([raw],[],start,end,'kWh')
        self.assertEqual(d['hours'][0]['pv_kwh'],0)
        self.assertEqual(len(d['hours']),1)
        self.assertEqual(d['coverage']['clamped_negative_statistics'],1)
        self.assertAlmostEqual(d['coverage']['clamped_negative_kwh_by_entity'][a.ENERGY['pv']],.007)

    def test_issued_forecasts_survive_raw_history_retention(self):
        previous={'pv_forecasts':[{'issued_at':'2026-01-01T20:00:00+01:00','target_date':'2026-01-02','predicted_kwh':3.}]}
        current={'requested_start':'2026-01-01T00:00:00+01:00','cutoff':'2026-01-20T00:00:00+01:00','pv_forecasts':[], 'coverage':{'complete_days':{'pv':['2026-01-02']}}}
        merged=a.retain_issued_forecasts(current,previous)
        self.assertEqual(merged['pv_forecasts'],previous['pv_forecasts'])
        self.assertEqual(merged['coverage']['pv_forecast_complete_pairs'],1)
        self.assertEqual(merged['coverage']['retained_forecast_days'],1)
    def test_conflicting_immutable_forecast_vintage_is_not_silently_replaced(self):
        row={'issued_at':'2026-01-01T20:00:00+01:00','target_date':'2026-01-02','predicted_kwh':3.}
        current={'requested_start':'2026-01-01T00:00:00+01:00','cutoff':'2026-01-20T00:00:00+01:00','pv_forecasts':[dict(row,predicted_kwh=9.)],'coverage':{'complete_days':{'pv':[]}}}
        with self.assertRaises(ValueError):a.retain_issued_forecasts(current,{'pv_forecasts':[row]})

    def test_collect_entrypoint_is_read_only(self):
        from contextlib import asynccontextmanager
        from unittest.mock import patch
        class Fake:
            def __init__(self): self.calls=[]
            async def call(self,name,**args):
                self.calls.append(name)
                if name=='ha_get_state':
                    return {'states':{e:{'state':'1','attributes':{'unit_of_measurement':'kWh'}} for e in [a.FORECAST]}}
                return {'entities':[]}
        async def run():
            fake=Fake()
            @asynccontextmanager
            async def connect(): yield fake
            with tempfile.TemporaryDirectory() as tmp, patch.object(a,'connection',connect):
                d=await a.collect(Path(tmp),datetime(2026,1,2,tzinfo=TZ))
                self.assertEqual(d['hours'],[])
                self.assertTrue((Path(tmp)/'annual_dataset.json').exists())
            self.assertTrue(set(fake.calls)<={'ha_get_history','ha_get_state'})
        with redirect_stdout(StringIO()):asyncio.run(run())

    def test_collect_names_missing_setup_instead_of_crashing(self):
        import settings
        settings.use({})
        try:
            with self.assertRaises(settings.NotConfigured):asyncio.run(a.collect(Path(tempfile.mkdtemp()),datetime(2026,1,2,tzinfo=TZ)))
        finally:
            settings.use(None);a.bind()

if __name__=='__main__': unittest.main()

import asyncio, json, os, tempfile, unittest
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo
from aiohttp.test_utils import AioHTTPTestCase
os.environ['HAUSAKKU_NO_SCHEDULER']='1'
import prices, service, settings, spot_prices, views
TZ=ZoneInfo('Europe/Berlin')
DAY=datetime(2026,10,28,tzinfo=TZ)

def hourly(day,values,key='start',vkey='value'):
    return [{key:(day+timedelta(hours=i)).isoformat(),'end':(day+timedelta(hours=i+1)).isoformat(),vkey:v} for i,v in enumerate(values)]

class FakeHA:
    def __init__(self,state=None,service=None,missing=False):self.state=state;self.service=service;self.missing=missing
    async def call(self,name,**a):
        if name=='ha_get_state':
            if self.missing:raise RuntimeError('gone')
            return self.state
        if name=='ha_call_service':return self.service
        raise AssertionError(name)

def run(coro):return asyncio.run(coro)

class ParsingTests(unittest.TestCase):
    def test_nordpool_style_attributes_today_and_tomorrow(self):
        attrs={'raw_today':hourly(DAY,[.1]*24),'raw_tomorrow':hourly(DAY+timedelta(days=1),[.2]*24),'today':[.1]*24,'unit':'x'}
        pts=prices.parse_attributes(attrs);self.assertEqual(len(pts),48)
        rows=prices.to_quarter_hours(pts);self.assertEqual(len(rows),192);self.assertEqual(rows[0]['price'],.1);self.assertEqual(rows[-1]['price'],.2)

    def test_epex_style_keys_and_explicit_attribute(self):
        attrs={'data':[{'start_time':(DAY+timedelta(minutes=15*i)).isoformat(),'price_per_kwh':.3} for i in range(8)],'other':[{'start':DAY.isoformat(),'value':9}]}
        self.assertEqual(len(prices.parse_attributes(attrs,'data')),8)
        self.assertEqual(prices.parse_attributes(attrs,'other')[DAY.timestamp()][1],9)

    def test_quarter_hours_are_kept_hourly_expanded_mixed_ok(self):
        pts={}
        for i in range(2):d=DAY+timedelta(hours=i);pts[d.timestamp()]=(d,.1)
        for i in range(4):d=DAY+timedelta(hours=2,minutes=15*i);pts[d.timestamp()]=(d,.2)
        rows=prices.to_quarter_hours(pts)
        self.assertEqual([r['price'] for r in rows],[.1]*8+[.2]*4)
        starts=[datetime.fromisoformat(r['start_time']) for r in rows]
        self.assertTrue(all((b-a)==timedelta(minutes=15) for a,b in zip(starts,starts[1:])))

    def test_half_hour_grid_rejected_with_clear_message(self):
        pts={(DAY+timedelta(minutes=30*i)).timestamp():(DAY+timedelta(minutes=30*i),.1) for i in range(4)}
        with self.assertRaises(prices.PriceError) as ctx:prices.to_quarter_hours(pts)
        self.assertIn('30 Minuten',str(ctx.exception))

    def test_bad_rows_are_skipped_not_fatal(self):
        attrs={'raw':[{'start':DAY.isoformat(),'value':'x'},{'start':'kaputt','value':1},{'value':2},{'start':DAY.isoformat(),'value':.5}]}
        self.assertEqual(list(prices.parse_attributes(attrs).values())[0][1],.5)

    def test_units_markup_vat(self):
        self.assertEqual(prices.unit_factor('EUR/kWh'),(1.,True));self.assertEqual(prices.unit_factor('€/kWh'),(1.,True))
        self.assertEqual(prices.unit_factor('ct/kWh'),(.01,True));self.assertEqual(prices.unit_factor('EUR/MWh'),(.001,True))
        self.assertEqual(prices.unit_factor(None),(1.,False))
        self.assertAlmostEqual(prices.finish(.10,{'markup_ct':10,'vat_percent':19}),(.10+.10)*1.19)
        self.assertEqual(prices.finish(.10,{}),.10)

class ProviderTests(unittest.TestCase):
    def test_entity_provider_converts_unit_and_markup(self):
        ha=FakeHA(state={'attributes':{'unit_of_measurement':'ct/kWh','raw_today':hourly(DAY,[10.]*24),'raw_tomorrow':hourly(DAY+timedelta(days=1),[20.]*24)}})
        rows,info=run(prices.fetch(ha,DAY,{'provider':'entity','entity':'sensor.np','markup_ct':5,'vat_percent':0}))
        self.assertEqual(len(rows),192);self.assertAlmostEqual(rows[0]['price'],.15);self.assertAlmostEqual(rows[-1]['price'],.25);self.assertTrue(info['unit_known'])

    def test_entity_provider_errors_are_readable(self):
        with self.assertRaises(prices.PriceError):run(prices.fetch(FakeHA(missing=True),DAY,{'provider':'entity','entity':'sensor.np'}))
        with self.assertRaises(prices.PriceError) as ctx:run(prices.fetch(FakeHA(state={'attributes':{}}),DAY,{'provider':'entity','entity':'sensor.np'}))
        self.assertIn('keine Preisliste',str(ctx.exception))
        with self.assertRaises(prices.PriceError):run(prices.fetch(FakeHA(),DAY,{'provider':'entity'}))
        with self.assertRaises(prices.PriceError):run(prices.fetch(FakeHA(),DAY,{'provider':'gas'}))

    def tibber(self,homes):
        return FakeHA(service={'service_response':{'prices':homes}})
    def rows15(self,p):return [{'start_time':(DAY+timedelta(minutes=15*i)).isoformat(),'price':p} for i in range(192)]

    def test_tibber_single_multiple_and_named_home(self):
        one=self.tibber({'Haus':self.rows15(.3)})
        rows,_=run(prices.fetch(one,DAY,{'provider':'tibber'}));self.assertEqual(len(rows),192)
        two=self.tibber({'A':self.rows15(.3),'B':self.rows15(.4)})
        with self.assertRaises(prices.PriceError) as ctx:run(prices.fetch(two,DAY,{'provider':'tibber'}))
        self.assertIn('A, B',str(ctx.exception))
        rows,_=run(prices.fetch(two,DAY,{'provider':'tibber','tibber_home':'B'}));self.assertEqual(rows[0]['price'],.4)
        with self.assertRaises(prices.PriceError):run(prices.fetch(two,DAY,{'provider':'tibber','tibber_home':'C'}))

    def test_window_is_limited_to_two_days(self):
        long=[{'start_time':(DAY-timedelta(days=1)+timedelta(minutes=15*i)).isoformat(),'price':.3} for i in range(96*4)]
        rows,_=run(prices.fetch(self.tibber({'H':long}),DAY,{'provider':'tibber'}))
        self.assertEqual(len(rows),192);self.assertEqual(rows[0]['start_time'],DAY.isoformat())

    def test_spot_provider_uses_zone_markup_and_vat(self):
        seen={}
        def fake_get(params,timeout=60):
            seen.update(params)
            stamps=[int((DAY+timedelta(hours=i)).timestamp()) for i in range(48)]
            return {'unit':'EUR / MWh','unix_seconds':stamps,'price':[100.]*48}
        original=spot_prices._get;spot_prices._get=fake_get
        try:rows,info=run(prices.fetch(FakeHA(),DAY,{'provider':'spot','bidding_zone':'AT','markup_ct':10,'vat_percent':20}))
        finally:spot_prices._get=original
        self.assertEqual(seen['bzn'],'AT');self.assertEqual(len(rows),192);self.assertAlmostEqual(rows[0]['price'],(.1+.1)*1.2)

    def test_spot_failure_is_a_price_error(self):
        def boom(params,timeout=60):raise OSError('net')
        original=spot_prices._get;spot_prices._get=boom
        try:
            with self.assertRaises(prices.PriceError):run(prices.fetch(FakeHA(),DAY,{'provider':'spot'}))
        finally:spot_prices._get=original

    def test_summary_reports_gaps_and_current_price(self):
        rows=[{'start_time':(DAY+timedelta(minutes=15*i)).isoformat(),'price':.1+i/1000} for i in range(8)]
        del rows[3]
        s=prices.summarize(rows,{'provider':'entity','unit':'EUR/kWh'},DAY+timedelta(minutes=20))
        self.assertEqual((s['intervals'],s['gaps']),(7,1));self.assertAlmostEqual(s['now'],.101)

class SpotCacheTests(unittest.TestCase):
    def test_cache_from_other_zone_is_not_reused(self):
        calls=[]
        def fake_get(params,timeout=60):
            calls.append(params);return {'unit':'EUR / MWh','unix_seconds':[1790000000],'price':[50.]}
        original=spot_prices._get;spot_prices._get=fake_get
        path=Path(tempfile.mkdtemp())/'spot.json'
        try:
            spot_prices.refresh(path,date(2026,10,28),zone='DE-LU')
            spot_prices.refresh(path,date(2026,10,28),zone='AT')
        finally:spot_prices._get=original
        self.assertEqual(json.loads(path.read_text())['bzn'],'AT')
        self.assertEqual(calls[1]['start'],'2026-01-01')    # started from scratch, not incrementally

class PriceSettingsTests(unittest.TestCase):
    def test_entity_provider_without_sensor_counts_as_missing(self):
        s=settings.Settings({'prices':{'provider':'entity'}})
        self.assertIn('price_entity',s.missing('plan'));self.assertEqual(settings.label('price_entity'),'Preis-Sensor (Strompreis)')
        self.assertNotIn('price_entity',settings.Settings({'prices':{'provider':'tibber'}}).missing('plan'))

    def test_validation(self):
        err={}
        out=views.validate_prices({'provider':'spot','bidding_zone':'at','markup_ct':'12,5','vat_percent':'19'},err)
        self.assertEqual(err,{});self.assertEqual((out['bidding_zone'],out['markup_ct'],out['vat_percent']),('AT',12.5,19.))
        for raw,key in (({'provider':'x'},'prices.provider'),({'provider':'entity'},'prices.entity'),({'provider':'tibber','bidding_zone':'??'},'prices.bidding_zone'),
                        ({'provider':'spot','markup_ct':'500'},'prices.markup_ct'),({'provider':'spot','vat_percent':'99'},'prices.vat_percent'),
                        ({'provider':'entity','entity':'sensor.a','attribute':'Bad Attr'},'prices.attribute')):
            e={};views.validate_prices(raw,e);self.assertIn(key,e,raw)

    def test_price_sensor_suggestion_needs_a_price_list(self):
        states=[{'entity_id':'sensor.nordpool','state':'0.1','attributes':{'raw_today':[{'start':'x','value':1}]}},
                {'entity_id':'sensor.temp','state':'20','attributes':{'unit_of_measurement':'°C'}}]
        self.assertEqual([e['entity_id'] for e in views.suggest('price_entity',states)],['sensor.nordpool'])

class PriceApiTests(AioHTTPTestCase):
    async def get_application(self):
        settings.use({});return service.make_app()
    async def tearDownAsync(self):settings.use(None)

    async def test_price_check_ok_and_error(self):
        from contextlib import asynccontextmanager
        now=datetime.now(TZ).replace(minute=0,second=0,microsecond=0)
        day=now.replace(hour=0)
        rows=[{'start_time':(day+timedelta(minutes=15*i)).isoformat(),'price':.3} for i in range(192)]
        @asynccontextmanager
        async def conn():yield object()
        orig_conn,orig_fetch=service.connection,prices.fetch
        service.connection=conn
        async def good(ha,daystart,cfg=None):return rows,{'provider':'tibber','unit':'EUR/kWh'}
        async def bad(ha,daystart,cfg=None):raise prices.PriceError('Mehrere Tibber-Zuhause gefunden (A, B).')
        try:
            prices.fetch=good
            r=await (await self.client.get('/api/prices/check')).json()
            self.assertTrue(r['ok']);self.assertEqual(r['summary']['intervals'],192)
            prices.fetch=bad
            r=await (await self.client.get('/api/prices/check')).json()
            self.assertFalse(r['ok']);self.assertIn('Mehrere',r['message'])
        finally:service.connection,prices.fetch=orig_conn,orig_fetch

if __name__=='__main__':unittest.main()

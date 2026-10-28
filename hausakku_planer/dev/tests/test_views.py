import asyncio, json, os, tempfile, unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from aiohttp.test_utils import AioHTTPTestCase
os.environ['HAUSAKKU_NO_SCHEDULER']='1'
import paths, service, settings, views
TZ=ZoneInfo('Europe/Berlin')

def iv(start,end,mode,price=.2,charge=0.,serve=0.,soc=5.):
    return {'start':start,'end':end,'mode':mode,'price_eur_kwh':price,'load_kwh':.1,'pv_kwh':0.,'terminal_kwh':soc,'charger_ac_kwh':charge,'served_ac_kwh':serve}

def sample_plan():
    ivs=[iv('2026-10-28T10:00:00+01:00','2026-10-28T10:15:00+01:00','charge',.10,charge=.28),
         iv('2026-10-28T10:15:00+01:00','2026-10-28T10:30:00+01:00','charge',.12,charge=.28),
         iv('2026-10-28T10:30:00+01:00','2026-10-28T11:00:00+01:00','serve',.30,serve=.5,soc=4.)]
    return {'created_at':'2026-10-28T09:55:00+01:00','valid_until':'2026-10-29T00:00:00+01:00','target_soc':60,
            'plan':{'intervals':ivs,'comparison':{'total_savings_eur':.42,'estimated_carryover_benefit_eur':.1}},
            'inputs':{'nominal_capacity_kwh':10.,'reserve_kwh':1.,'grid_charge_limit_kwh':9.,'initial_kwh':3.,'soc':30.},
            'operating_policy':{'reason':'Netzladen lohnt sich','reason_code':'grid_charge'},
            'multiday_forecast':{'rows':[{'start':'2026-10-28T11:00:00+01:00','end':'2026-10-28T12:00:00+01:00','price_eur_kwh':.2,'load_kwh':.3,'pv_kwh':.1}]},
            'pv_source':{'warning':'no Open-Meteo forecast'},'forecast_model':{'warnings':['no_artifact']},'efficiency':{'source':'configured'}}

class PlanViewTests(unittest.TestCase):
    def test_adjacent_same_mode_intervals_merge_with_weighted_price(self):
        v=views.plan_view(sample_plan(),datetime(2026,10,28,10,20,tzinfo=TZ))
        self.assertEqual([w['mode'] for w in v['windows']],['charge','serve'])
        charge=v['windows'][0]
        self.assertAlmostEqual(charge['avg_price'],.11);self.assertAlmostEqual(charge['kwh'],.56)
        self.assertEqual(charge['label'],'Laden');self.assertIn('Netzladen: 0,6 kWh',charge['text'])

    def test_now_and_next_window(self):
        v=views.plan_view(sample_plan(),datetime(2026,10,28,10,20,tzinfo=TZ))
        self.assertEqual(v['now']['mode'],'charge');self.assertEqual(v['next']['mode'],'serve')
        self.assertFalse(v['expired'])
        late=views.plan_view(sample_plan(),datetime(2026,10,30,tzinfo=TZ))
        self.assertIsNone(late['now']);self.assertTrue(late['expired'])

    def test_tail_hints_and_savings(self):
        v=views.plan_view(sample_plan(),datetime(2026,10,28,10,20,tzinfo=TZ))
        self.assertEqual(len(v['tail']),1);self.assertEqual(v['savings']['cash_eur'],.42)
        texts=' '.join(h['text'] for h in v['hints'])
        self.assertIn('Open-Meteo',texts);self.assertIn('Startwert',texts);self.assertNotIn('no_artifact',texts)

class SuggestTests(unittest.TestCase):
    STATES=[{'entity_id':'sensor.netz_bezug','state':'10','attributes':{'unit_of_measurement':'kWh','friendly_name':'Netz Bezug'}},
            {'entity_id':'sensor.temp','state':'20','attributes':{'unit_of_measurement':'°C'}},
            {'entity_id':'sensor.akku_soc','state':'55','attributes':{'unit_of_measurement':'%','friendly_name':'Akku SOC'}},
            {'entity_id':'sensor.wr_energy','state':'3','attributes':{'unit_of_measurement':'Wh','friendly_name':'Wechselrichter'}},
            {'entity_id':'switch.lader','state':'off','attributes':{'friendly_name':'Ladegerät'}},
            {'entity_id':'weather.home','state':'sunny','attributes':{}}]

    def ids(self,role,q=''):return [e['entity_id'] for e in views.suggest(role,self.STATES,q)]

    def test_roles_filter_by_kind(self):
        self.assertEqual(self.ids('battery_soc'),['sensor.akku_soc'])
        self.assertEqual(self.ids('charger_switch'),['switch.lader'])
        self.assertEqual(self.ids('weather'),['weather.home'])
        self.assertNotIn('sensor.temp',self.ids('grid_import'))

    def test_keyword_ranking_and_query(self):
        self.assertEqual(self.ids('inverter_energy')[0],'sensor.wr_energy')
        self.assertEqual(self.ids('grid_import','netz'),['sensor.netz_bezug'])

class ValidationTests(unittest.TestCase):
    def test_valid_input_is_cleaned(self):
        clean,err=views.validate_settings({'entities':{'battery_soc':' sensor.soc ','ev_energy':['sensor.a','',' sensor.b'],'bogus':'x'},
            'location':{'latitude':'52.5212','longitude':'13.4011'},'battery':{'capacity_kwh':'10'}})
        self.assertEqual(err,{});self.assertEqual(clean['entities']['battery_soc'],'sensor.soc')
        self.assertEqual(clean['entities']['ev_energy'],['sensor.a','sensor.b']);self.assertNotIn('bogus',clean['entities'])
        self.assertEqual((clean['location']['latitude'],clean['location']['longitude']),(52.52,13.40))
        self.assertEqual(clean['battery']['capacity_kwh'],10.)

    def test_errors_are_reported_per_field(self):
        _,err=views.validate_settings({'entities':{'battery_soc':'not an entity','ev_energy':['bad id'],'ev_window_helper':'sensor.x'},
            'location':{'latitude':'95','longitude':''},'battery':{'capacity_kwh':'500'}})
        for key in ('entities.battery_soc','entities.ev_energy','entities.ev_window_helper','location.latitude','battery.capacity_kwh'):self.assertIn(key,err)

    def test_empty_values_clear_roles(self):
        clean,err=views.validate_settings({'entities':{'battery_soc':''},'location':{},'battery':{}})
        self.assertEqual(err,{});self.assertIsNone(clean['entities']['battery_soc'])

class FakeHA:
    def __init__(self,unit='kWh',state='5',days=28,exists=True):self.unit=unit;self.state=state;self.days=days;self.exists=exists
    async def call(self,name,**a):
        if name=='ha_get_state':
            if not self.exists:raise RuntimeError('gone')
            return {'state':self.state,'attributes':{'unit_of_measurement':self.unit}}
        return {'entities':[{'entity_id':a['entity_ids'],'statistics':[{'change':1.}]*self.days}]}

class CheckTests(unittest.TestCase):
    def check(self,role,**kw):return asyncio.run(service.check_entity(FakeHA(**kw),role,'sensor.x',datetime(2026,10,28,tzinfo=TZ)))

    def test_good_counter(self):
        r=self.check('grid_import');self.assertTrue(r['ok']);self.assertEqual(r['history_days'],28)
    def test_missing_entity_wrong_unit_no_history(self):
        self.assertFalse(self.check('grid_import',exists=False)['ok'])
        self.assertIn('Einheit',' '.join(self.check('grid_import',unit='W')['messages']))
        self.assertIn('Langzeitstatistik',' '.join(self.check('grid_import',days=0)['messages']))
    def test_short_history_warns_but_passes(self):
        r=self.check('grid_import',days=10);self.assertTrue(r['ok']);self.assertIn('10 von 28',' '.join(r['messages']))
    def test_unavailable_fails(self):self.assertFalse(self.check('battery_soc',state='unavailable',unit='%')['ok'])

class ApiTests(AioHTTPTestCase):
    async def get_application(self):
        self.tmp=tempfile.mkdtemp();self.old=(paths.DATA,paths.STATE)
        paths.DATA=Path(self.tmp);paths.STATE=paths.DATA/'state';paths.STATE.mkdir()
        self.env=os.environ.pop('HAUSAKKU_SETTINGS',None)   # settings are read back from <data>/settings.json here
        settings.use({});return service.make_app()
    async def tearDownAsync(self):
        paths.DATA,paths.STATE=self.old
        if self.env:os.environ['HAUSAKKU_SETTINGS']=self.env
        settings.use(None)

    async def test_plan_none_then_present(self):
        self.assertIsNone((await (await self.client.get('/api/plan')).json())['plan'])
        (paths.STATE/'plan.json').write_text(json.dumps(sample_plan()))
        self.assertEqual((await (await self.client.get('/api/plan')).json())['plan']['target_soc'],60)

    async def test_settings_roundtrip_keeps_planner_overrides(self):
        settings.use({'planner':{'max_charge_kw':3.3}})
        r=await self.client.put('/api/settings',json={'entities':{'battery_soc':'sensor.soc'},'location':{'latitude':'50','longitude':'8'},'battery':{'capacity_kwh':'10'}})
        self.assertEqual(r.status,200)
        saved=json.loads((paths.DATA/'settings.json').read_text())
        self.assertEqual(saved['entities']['battery_soc'],'sensor.soc');self.assertEqual(saved['planner']['max_charge_kw'],3.3)
        got=await (await self.client.get('/api/settings')).json()
        self.assertEqual(got['settings']['battery']['capacity_kwh'],10.);self.assertIn('grid_import',got['missing'])

    async def test_invalid_settings_rejected_and_not_saved(self):
        r=await self.client.put('/api/settings',json={'entities':{'battery_soc':'bad id'}})
        self.assertEqual(r.status,400);self.assertIn('entities.battery_soc',(await r.json())['errors'])
        self.assertFalse((paths.DATA/'settings.json').exists())

    async def test_unknown_role_and_bad_entity_rejected(self):
        self.assertEqual((await self.client.get('/api/entities?role=nope')).status,400)
        self.assertEqual((await self.client.get('/api/check?role=grid_import&entity=../x')).status,400)

    async def test_index_is_served(self):
        r=await self.client.get('/');t=await r.text();self.assertEqual(r.status,200);self.assertIn('Einstellungen',t)

class IngressTests(AioHTTPTestCase):
    async def get_application(self):return service.make_app()
    async def test_only_ingress_gateway_inside_addon(self):
        os.environ['SUPERVISOR_TOKEN']='x'
        try:self.assertEqual((await self.client.get('/api/status')).status,200)   # test client connects from 127.0.0.1
        finally:os.environ.pop('SUPERVISOR_TOKEN')

if __name__=='__main__':unittest.main()

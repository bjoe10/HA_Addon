import asyncio, json, os, sys, tempfile, unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from aiohttp.test_utils import AioHTTPTestCase
os.environ['HAUSAKKU_NO_SCHEDULER']='1'
import paths, service, settings
TZ=ZoneInfo('Europe/Berlin')

class SchedulingTests(unittest.TestCase):
    def test_due_runs_main_and_hourly(self):
        t=lambda h,m:datetime(2026,10,27,h,m,tzinfo=TZ)
        self.assertEqual(service.due_runs(t(14,16),t(14,10)),['main'])
        self.assertEqual(service.due_runs(t(11,46),t(11,40)),['replan'])
        self.assertEqual(service.due_runs(t(20,16),t(20,14)),['main'])
        self.assertEqual(service.due_runs(t(11,50),t(11,46)),[])

    def test_missed_minutes_are_not_lost(self):
        t=lambda h,m:datetime(2026,10,27,h,m,tzinfo=TZ)
        self.assertEqual(service.due_runs(t(15,50),t(13,50)),['main'])
        self.assertEqual(service.due_runs(t(18,50),t(16,50)),['replan'])

    def test_observe_never_publishes(self):
        self.assertEqual(service.planner_args('main','observe'),[]);self.assertEqual(service.planner_args('replan','observe'),[])
        self.assertEqual(service.planner_args('main','publish'),['--publish']);self.assertEqual(service.planner_args('replan','control'),['--replan'])

class RunTests(unittest.TestCase):
    def setUp(self):
        self.old=paths.STATE;paths.STATE=__import__('pathlib').Path(tempfile.mkdtemp());settings.use(settings.load())
    def tearDown(self):paths.STATE=self.old;settings.use(None)

    def test_unconfigured_run_is_skipped_with_reason(self):
        settings.use({})
        r=asyncio.run(service.run_planner('main','observe'))
        self.assertTrue(r['skipped']);self.assertIn('Einrichtung unvollständig',r['message'])
        self.assertEqual(service.read_runs()[0]['skipped'],True)

    def test_run_is_logged_with_output(self):
        r=asyncio.run(service.run_planner('main','observe',command=[sys.executable,'-c','print("plan ok")']))
        self.assertTrue(r['ok']);self.assertIn('plan ok',r['stdout'])
        bad=asyncio.run(service.run_planner('replan','observe',command=[sys.executable,'-c','import sys;print("boom",file=sys.stderr);sys.exit(1)']))
        self.assertFalse(bad['ok']);self.assertEqual([x['ok'] for x in service.read_runs()],[False,True])

    def test_hung_run_is_stopped_and_keeps_what_it_printed(self):
        hang=[sys.executable,'-u','-c','import sys,time;print("schritt 1");print("warte",file=sys.stderr);time.sleep(60)']
        t0=__import__('time').monotonic()
        r=asyncio.run(service.run_planner('main','observe',command=hang,timeout=1))
        self.assertLess(__import__('time').monotonic()-t0,10)
        self.assertFalse(r['ok']);self.assertIn('Zeitlimit',r['message'])
        self.assertIn('schritt 1',r['stdout']);self.assertIn('warte',r['stderr']);self.assertIn('Zeitlimit',r['stderr'])
        self.assertIn('Zeitlimit',service.read_runs()[0]['message'])

    def test_hung_run_writes_where_it_waits_before_it_is_stopped(self):
        code=('import asyncio,diagnostics\n'
              'diagnostics.arm()\n'
              'async def stuck():await asyncio.sleep(60)\n'
              'async def main():\n'
              '    w=diagnostics.start_watch(["Datenabruf aus HA"]);await stuck()\n'
              'asyncio.run(main())\n')
        r=asyncio.run(service.run_planner('main','observe',command=[sys.executable,'-c',code],timeout=3))
        self.assertFalse(r['ok']);self.assertIn('Zeitlimit',r['message'])
        self.assertIn('Lauf hängt seit',r['stderr']);self.assertIn('Schritt: Datenabruf aus HA',r['stderr'])
        self.assertIn('stuck',r['stderr'])                    # the awaiting coroutine is named

    def test_every_run_kind_has_a_time_limit(self):
        for kind in ('main','replan','weekly'):self.assertGreater(service.RUN_TIMEOUT[kind],300)

class FakeHA:
    """Answers the three reads of update_savings: 5-minute meter changes, battery means, release-switch history."""
    def __init__(self,switch='on',grid=.05,battery=8.):self.switch=switch;self.grid=grid;self.battery=battery;self.calls=[]
    async def call(self,name,**kw):
        self.calls.append((name,kw))
        start=datetime.fromisoformat(kw['start_time']).timestamp();end=datetime.fromisoformat(kw['end_time']).timestamp()
        buckets=range(int(start),int(end),300)
        ids=kw['entity_ids'] if isinstance(kw['entity_ids'],list) else [kw['entity_ids']]
        if kw.get('source')=='statistics' and kw['statistic_types']==['mean']:
            return {'entities':[{'entity_id':e,'unit_of_measurement':'kWh','statistics':[{'start':t*1000,'mean':self.battery} for t in buckets]} for e in ids]}
        if kw.get('source')=='statistics':
            grid=settings.current().entity('grid_import')
            return {'entities':[{'entity_id':e,'unit_of_measurement':'kWh','has_more':False,
                                 'statistics':[{'start':t*1000,'change':self.grid if e==grid else 0.} for t in buckets]} for e in ids]}
        return {'entities':[{'entity_id':ids[0],'states':[{'state':self.switch,'last_changed':datetime.fromtimestamp(start-3600,TZ).isoformat()}]}]}

class SavingsTests(unittest.TestCase):
    def setUp(self):
        from pathlib import Path
        self.old=(paths.DATA,paths.STATE);paths.DATA=Path(tempfile.mkdtemp());paths.STATE=paths.DATA/'state';paths.ensure()
        settings.use(settings.load())
        (paths.DATA/'config.json').write_text(json.dumps({'capacity_kwh':16,'reserve_fraction':.1,'max_charge_kw':1,'max_discharge_kw':2,
            'discharge_efficiency':.9,'roundtrip_efficiency':.8,'grid_charge_max_soc_fraction':.9}))
        import multiday
        t0=int(datetime(2026,11,9,10,0,tzinfo=TZ).timestamp())
        multiday.archive_prices(paths.STATE/'multiday_audit.sqlite',{'collected_at':datetime.fromtimestamp(t0-86400,TZ).isoformat(),
            'prices':[{'start_time':datetime.fromtimestamp(t0-86400+900*i,TZ).isoformat(),'price':.3} for i in range(4*72)]})
        self.t0=t0
    def tearDown(self):paths.DATA,paths.STATE=self.old;settings.use(None)

    def at(self,minutes):return datetime.fromtimestamp(self.t0+60*minutes,TZ)

    def test_counting_starts_now_without_going_back(self):
        ha=FakeHA()
        s=asyncio.run(service.update_savings(ha,self.at(10)))
        self.assertEqual(ha.calls,[]);self.assertEqual(s['total_eur'],0.);self.assertEqual(s['active_hours'],0.)
        self.assertTrue(s['since'].startswith('2026-11-09T10:00'))

    def test_held_hour_counts_while_the_control_is_on(self):
        ha=FakeHA(grid=.05)
        asyncio.run(service.update_savings(ha,self.at(0)))
        s=asyncio.run(service.update_savings(ha,self.at(67)))           # one complete hour later
        self.assertEqual(s['active_hours'],1.)
        # The house drew 0.6 kWh from the grid at 0.30 while the shadow served it from its battery.
        self.assertAlmostEqual(s['cash_eur'],-.18,places=2);self.assertAlmostEqual(s['actual_cost_eur'],.18,places=2)
        # The kept energy (0.6 kWh AC = 0.67 kWh in the battery) is valued at the lowest recent price x efficiency.
        self.assertAlmostEqual(s['inventory_eur'],(.6/.9)*.3*.9,places=2)
        self.assertEqual(s['week_eur'],s['total_eur']);self.assertTrue(s['control_on'])
        state,attrs=service.savings_state(s)
        self.assertEqual(state,s['total_eur']);self.assertEqual(attrs['week_eur'],s['week_eur']);self.assertEqual(attrs['device_class'],'monetary')
        self.assertEqual(service.savings_summary(),s)

    def test_nothing_is_added_while_the_control_is_off(self):
        ha=FakeHA(switch='off')
        asyncio.run(service.update_savings(ha,self.at(0)))
        s=asyncio.run(service.update_savings(ha,self.at(67)))
        self.assertEqual(s['total_eur'],0.);self.assertEqual(s['active_hours'],0.);self.assertEqual(s['inactive_hours'],1.)
        self.assertFalse(s['control_on'])

    def test_unknown_before_the_first_update(self):
        self.assertIsNone(service.savings_summary())
        state,attrs=service.savings_state(None)
        self.assertEqual(state,'unknown');self.assertEqual(attrs['unit_of_measurement'],'EUR')

    def test_savings_sensor_is_writable_like_the_report_and_only_when_publishing(self):
        from ha_client import check_call,savings_sensor,WritesDisabled
        settings.use({'helper_prefix':'hap'})
        try:
            self.assertEqual(savings_sensor(),'sensor.hap_ersparnis')
            check_call('ha_set_state',{'entity_id':'sensor.hap_ersparnis'},mode='publish')
            with self.assertRaises(WritesDisabled):check_call('ha_set_state',{'entity_id':'sensor.hap_ersparnis'},mode='observe')
            with self.assertRaises(ValueError):check_call('ha_set_state',{'entity_id':'sensor.hap_anderes'},mode='publish')
        finally:settings.use(None)

class ServiceTests(AioHTTPTestCase):
    async def get_application(self):
        settings.use({});return service.make_app()
    async def tearDownAsync(self):settings.use(None)

    async def test_index_status_and_runs(self):
        r=await self.client.get('/');self.assertEqual(r.status,200);self.assertIn('Hausakku',await r.text())
        s=await (await self.client.get('/api/status')).json()
        self.assertIn(s['mode'],('observe','publish','control'));self.assertTrue(s['missing']);self.assertIsNone(s['plan'])
        self.assertEqual(await (await self.client.get('/api/runs')).json(),[] if not (paths.STATE/'runs.jsonl').exists() else await (await self.client.get('/api/runs')).json())

class AdoptedHelpersTests(AioHTTPTestCase):
    async def get_application(self):
        self.old=paths.DATA;paths.DATA=__import__('pathlib').Path(tempfile.mkdtemp())
        settings.use({'helper_prefix':'hausakku','adopt_legacy_helpers':True});return service.make_app()
    async def tearDownAsync(self):paths.DATA=self.old;settings.use(None)

    async def test_saving_from_the_ui_keeps_an_adopted_prefix(self):
        body={'helper_prefix':'hausakku','entities':{},'location':{},'battery':{},'prices':{'provider':'tibber'}}   # the UI does not send the flag
        r=await self.client.put('/api/settings',json=body)
        self.assertEqual(r.status,200)
        saved=settings.Settings(json.loads((paths.DATA/'settings.json').read_text()))   # what the add-on loads next
        self.assertEqual(saved.helpers()['charge'],'hausakku_netzladen');self.assertTrue(saved.data['adopt_legacy_helpers'])

    async def test_without_adoption_the_reserved_prefix_is_refused(self):
        settings.use({})
        r=await self.client.put('/api/settings',json={'helper_prefix':'hausakku','entities':{},'location':{},'battery':{},'prices':{'provider':'tibber'}})
        self.assertEqual(r.status,400)

class OperatingModeTests(unittest.TestCase):
    def tearDown(self):
        settings.use(None);os.environ.pop('HAUSAKKU_MODE',None)
    def test_ui_switch_decides_and_the_option_is_only_the_fallback(self):
        settings.use({});os.environ['HAUSAKKU_MODE']='publish'
        self.assertEqual(settings.operating_mode(),'publish')            # older install: the option still counts
        settings.use({'publish':False});self.assertEqual(settings.operating_mode(),'observe')
        os.environ['HAUSAKKU_MODE']='observe'
        settings.use({'publish':True});self.assertEqual(settings.operating_mode(),'publish')
        settings.use({});self.assertEqual(settings.operating_mode(),'observe')

class MigratePublishTests(unittest.TestCase):
    def setUp(self):
        self.old=paths.DATA;paths.DATA=__import__('pathlib').Path(tempfile.mkdtemp());self.env=os.environ.get('HAUSAKKU_SETTINGS')
        os.environ['HAUSAKKU_SETTINGS']=str(paths.DATA/'settings.json')
    def tearDown(self):
        paths.DATA=self.old;settings.use(None);os.environ.pop('HAUSAKKU_MODE',None)
        if self.env is None:os.environ.pop('HAUSAKKU_SETTINGS',None)
        else:os.environ['HAUSAKKU_SETTINGS']=self.env
    def test_option_becomes_the_saved_setting_once(self):
        os.environ['HAUSAKKU_MODE']='publish';settings.use(None)
        self.assertTrue(settings.migrate_publish())
        self.assertIs(json.loads((paths.DATA/'settings.json').read_text())['publish'],True)
        os.environ.pop('HAUSAKKU_MODE');settings.use(None)
        self.assertEqual(settings.operating_mode(),'publish')            # no option needed any more
        self.assertFalse(settings.migrate_publish())
    def test_observe_option_or_explicit_choice_is_left_alone(self):
        os.environ['HAUSAKKU_MODE']='observe';settings.use(None);self.assertFalse(settings.migrate_publish())
        os.environ['HAUSAKKU_MODE']='publish';settings.use({'publish':False});self.assertFalse(settings.migrate_publish())

class ControlSetupGuardTests(AioHTTPTestCase):
    async def get_application(self):
        settings.use({});return service.make_app()
    async def tearDownAsync(self):settings.use(None)

    async def test_refused_while_publishing_is_off(self):
        settings.use({'publish':False})
        r=await self.client.post('/api/control/setup')
        self.assertEqual(r.status,409);self.assertIn('veröffentlichen',(await r.json())['message'])
    async def test_nothing_is_created_when_the_existing_control_cannot_be_checked(self):
        settings.use({'publish':True,'entities':{'charger_switch':'switch.c','inverter_switch':'switch.i','battery_soc':'sensor.s'}})
        calls=[]
        class Broken:
            async def __aenter__(s):return s
            async def __aexit__(s,*a):return False
            async def call(s,name,**kw):
                calls.append(name)
                if name=='ha_related':raise RuntimeError('boom')
            async def install_control(s,*a):calls.append('install')
            async def ensure_own_helpers(s):calls.append('helpers')
        original=service.connection;service.connection=lambda:Broken()
        try:r=await self.client.post('/api/control/setup')
        finally:service.connection=original
        self.assertEqual(r.status,500);self.assertNotIn('install',calls);self.assertNotIn('helpers',calls)
    async def test_refused_without_the_switches_and_soc(self):
        settings.use({'publish':True})
        r=await self.client.post('/api/control/setup')
        self.assertEqual(r.status,400);self.assertIn('Schalter Netzladegerät',(await r.json())['message'])

class AsyncRunTests(AioHTTPTestCase):
    async def get_application(self):
        settings.use({});return service.make_app()
    async def tearDownAsync(self):settings.use(None)

    async def test_run_returns_at_once_and_status_shows_running(self):
        gate=asyncio.Event()
        async def slow(kind,mode,trigger='zeit',command=None):
            await gate.wait();return {'ok':True}
        original=service.run_planner;service.run_planner=slow
        try:
            r=await self.client.post('/api/run')
            self.assertEqual(r.status,202);self.assertTrue((await r.json())['started'])
            self.assertEqual((await (await self.client.get('/api/status')).json())['running']['kind'],'main')
            again=await self.client.post('/api/run')
            self.assertEqual(again.status,409)
            gate.set()
            for _ in range(50):
                if (await (await self.client.get('/api/status')).json())['running'] is None:break
                await asyncio.sleep(.02)
            self.assertIsNone((await (await self.client.get('/api/status')).json())['running'])
            self.assertEqual((await self.client.post('/api/run')).status,202)
        finally:service.run_planner=original

class ReportTextTests(unittest.TestCase):
    """The report must not carry one household's assumptions and must not claim writes that did not happen."""
    def plan(self,helper,published):
        import copy
        from pathlib import Path
        from planner import compute_plan
        fixture=json.loads((Path(__file__).parent/'fixtures/test_fixture_snapshot.json').read_text())
        data=copy.deepcopy(settings.load().data);data['entities']['ev_window_helper']=helper
        settings.use(data)
        plan=compute_plan(fixture,settings.current().planner_config()|{'capacity_kwh':15.85})
        plan['ev']={'status':'ok','soc':50,'target_soc':80,'need_kwh':20.,'kwh_per_percent':.7,'per_percent_source':'gemessen','power_kw':3.5,
                    'power_source':'gemessen','duration_h':5.,'plugged':True,'start':plan['plan']['intervals'][0]['start'],'end':plan['plan']['intervals'][4]['end'],
                    'mean_price_eur_kwh':.2,'cost_eur':4.,'flex_start':plan['plan']['intervals'][0]['start'],'flex_end':plan['plan']['intervals'][4]['end']}
        if published:plan['ev_publication']={'verified':True}
        return plan

    def tearDown(self):settings.use(None)

    def report(self,helper,published):
        from planner import report,llm_facts
        plan=self.plan(helper,published)
        return report(plan)+'\n'+llm_facts(plan)

    def test_no_helper_says_so(self):
        text=self.report(None,False)
        self.assertIn('Kein Zeitplan-Helfer eingerichtet',text);self.assertNotIn('als schedule.',text)

    def test_helper_but_nothing_written_does_not_claim_entry(self):
        text=self.report('car_charge_window',False)
        self.assertIn('Nicht in HA eingetragen',text);self.assertNotIn('als schedule.car_charge_window eingetragen',text)

    def test_published_window_is_reported_as_written(self):
        self.assertIn('In HA als schedule.car_charge_window eingetragen',self.report('car_charge_window',True))

    def test_no_household_specific_wording(self):
        text=self.report(None,False)
        for word in ('laut Nutzer','Tesla','CEE','City El','15 kWh / 2 kW'):self.assertNotIn(word,text)
        self.assertIn('schaltet selbst keine Geräte',text)

class BridgeTests(unittest.TestCase):
    def test_report_attributes_keep_latest_per_kind(self):
        a=service.bridge_attributes({'kind':'main','time':'t1','ok':True,'stdout':' bericht \n','stderr':''},{})
        b=service.bridge_attributes({'kind':'replan','time':'t2','ok':True,'stdout':'','stderr':''},a)
        self.assertEqual(b['main']['report'],'bericht');self.assertEqual(b['replan']['report'],'')
        c=service.bridge_attributes({'kind':'main','time':'t3','ok':False,'stdout':'','stderr':'boom'},b)
        self.assertEqual(c['main']['error'],'boom');self.assertIn('replan',c)
    def test_soc_plan_only_from_verified_publication(self):
        iv=lambda a,b,start,end:{'start':a,'end':b,'initial_kwh':start,'terminal_kwh':end}
        plan={'created_at':'2026-11-02T14:15:00+01:00','valid_until':'2026-11-04T00:00:00+01:00','publication':{'verified':True},
              'inputs':{'nominal_capacity_kwh':16.0},
              'plan':{'intervals':[iv('2026-11-02T14:15:00+01:00','2026-11-02T14:30:00+01:00',4.123,4.0),
                                   iv('2026-11-02T14:30:00+01:00','2026-11-02T15:30:00+01:00',4.0,3.456)]}}
        soc=service.soc_plan_attribute(plan)
        self.assertEqual(soc['minutes'],[15,75]);self.assertEqual(soc['kwh'],[4.0,3.46])
        self.assertEqual(soc['initial_kwh'],4.12);self.assertEqual(soc['capacity_kwh'],16.0)
        self.assertEqual(soc['start'],'2026-11-02T14:15:00+01:00')
        self.assertIsNone(service.soc_plan_attribute({**plan,'publication':{'verified':False}}))
        self.assertIsNone(service.soc_plan_attribute(None))
        entry={'kind':'main','time':'t1','ok':True,'stdout':'','stderr':''}
        a=service.bridge_attributes(entry,{},plan)
        b=service.bridge_attributes({**entry,'kind':'replan'},a,{**plan,'publication':{}})
        self.assertEqual(b['soc_plan'],soc)   # an unpublished plan leaves the last published one
    def test_weekly_run_is_due_monday_8(self):
        from datetime import datetime
        tz=service.TZ
        self.assertEqual(service.due_runs(datetime(2026,11,2,8,0,30,tzinfo=tz),datetime(2026,11,2,7,59,40,tzinfo=tz)),['weekly'])
        self.assertEqual(service.due_runs(datetime(2026,11,3,8,0,30,tzinfo=tz),datetime(2026,11,3,7,59,40,tzinfo=tz)),[])

if __name__=='__main__':unittest.main()

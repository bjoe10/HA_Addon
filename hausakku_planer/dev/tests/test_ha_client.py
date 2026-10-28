import unittest
from ha_client import check_call, HA, WritesDisabled, ControlExists
import asyncio, settings

class ClientTests(unittest.TestCase):
    def test_normalizes_dwd_hourly_forecast_service_response(self):
        from collector import normalize_hourly_weather
        response={'service_response':{'weather.home_forecast':{'forecast':[
            {'datetime':'2026-10-26T10:00:00+00:00','cloud_coverage':87.0,'condition':'cloudy'},
            {'datetime':'bad','cloud_coverage':50.0}, {'datetime':'2026-10-26T12:00:00+00:00','cloud_coverage':101.0}]}}}
        self.assertEqual(normalize_hourly_weather(response),[{'datetime':'2026-10-26T10:00:00+00:00','cloud_coverage':87.0,'condition':'cloudy'}])

    def test_allows_read_only_hourly_weather_forecasts_only_for_dwd_entity(self):
        check_call('ha_call_service',{'domain':'weather','service':'get_forecasts','entity_id':'weather.home_forecast','data':{'type':'hourly'}})
        with self.assertRaises(ValueError): check_call('ha_call_service',{'domain':'weather','service':'get_forecasts','entity_id':'weather.other','data':{'type':'hourly'}})
        with self.assertRaises(ValueError): check_call('ha_call_service',{'domain':'weather','service':'get_forecasts','entity_id':'weather.home_forecast','data':{'type':'daily'}})
        with self.assertRaises(ValueError): check_call('ha_call_service',{'domain':'weather','service':'turn_on'})

    def test_energy_prefs_read_only(self):
        from ha_client import check_call
        check_call('ha_manage_energy_prefs',{'mode':'get'})
        for args in ({'mode':'set','config':{}},{'mode':'add_device','stat_consumption':'sensor.x'},{'mode':'get','include_schema':True}):
            with self.assertRaises(ValueError):check_call('ha_manage_energy_prefs',args)
    def test_device_consumption_splits_days_and_units(self):
        from collector import device_consumption
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz=ZoneInfo('Europe/Berlin');now=datetime(2026,10,25,9,tzinfo=tz)
        y=datetime(2026,10,24,12,tzinfo=tz).timestamp()*1000;t=datetime(2026,10,25,7,tzinfo=tz).timestamp()*1000
        prefs={'config':{'device_consumption':[{'stat_consumption':'sensor.wm','name':'Waschmaschine'},{'stat_consumption':'sensor.cee'}]}}
        stats={'entities':[{'entity_id':'sensor.wm','unit_of_measurement':'kWh','statistics':[{'start':y,'change':2.5},{'start':t,'change':1.}]},
                           {'entity_id':'sensor.cee','unit_of_measurement':'Wh','statistics':[{'start':y,'change':1500}]}]}
        r=device_consumption(prefs,stats,now)
        self.assertEqual(r['yesterday'],{'Waschmaschine':2.5,'Cee':1.5});self.assertEqual(r['today'],{'Waschmaschine':1.})
    def test_no_hardware_services(self):
        with self.assertRaises(ValueError): check_call('ha_call_service',{'domain':'switch','service':'turn_on'})
    def test_only_own_helpers_written(self):
        with self.assertRaises(ValueError): check_call('ha_config_set_helper',{'helper_type':'schedule','helper_id':'car_charge_window'})
        check_call('ha_config_set_helper',{'helper_type':'schedule','helper_id':'hap_netzladen','action':'update'})
    def test_original_planner_helpers_are_never_written(self):
        for helper in ('hausakku_netzladen','hausakku_entladen'):
            with self.assertRaises(ValueError):
                check_call('ha_config_set_helper',{'helper_type':'schedule','helper_id':helper,'action':'update'})
        for entity in ('input_datetime.hausakku_plan_gueltig_bis','input_number.hausakku_ziel_soc','input_text.hausakku_plan_status'):
            with self.assertRaises(ValueError):
                check_call('ha_call_service',{'domain':entity.split('.')[0],'service':'set_value','entity_id':entity})
    def test_prefix_decides_the_own_helpers(self):
        old=settings.current()
        try:
            settings.use({'helper_prefix':'solar'})
            check_call('ha_config_set_helper',{'helper_type':'schedule','helper_id':'solar_netzladen','action':'update'})
            with self.assertRaises(ValueError):
                check_call('ha_config_set_helper',{'helper_type':'schedule','helper_id':'hap_netzladen','action':'update'})
            self.assertEqual(settings.current().helpers()['target'],'solar_ziel_soc')
        finally:settings.use(old)
    def test_reserved_or_malformed_prefix_rejected(self):
        for bad in ('hausakku','hausakku2','x','Ab','a-b','1abc','',None,'a'*17):
            self.assertIsNotNone(settings.check_prefix(bad),bad)
        self.assertIsNone(settings.check_prefix('hap'))
        with self.assertRaises(ValueError):settings.Settings({'helper_prefix':'hausakku'}).helpers()
    def test_adopting_legacy_helpers_is_opt_in(self):
        self.assertIsNotNone(settings.check_prefix('hausakku'))
        self.assertIsNone(settings.check_prefix('hausakku',adopt_legacy=True))
        self.assertIsNotNone(settings.check_prefix('hausakku2',adopt_legacy=True))
        names=settings.Settings({'helper_prefix':'hausakku','adopt_legacy_helpers':True}).helpers()
        self.assertEqual(names['charge'],'hausakku_netzladen');self.assertEqual(names['target'],'hausakku_ziel_soc')
        self.assertEqual(names['permission'],'hausakku_planer_freigabe')
    def test_report_sensor_is_the_only_state_write(self):
        old=settings.current()
        try:
            settings.use({'helper_prefix':'hap'})
            check_call('ha_set_state',{'entity_id':'sensor.hap_bericht'},mode='publish')
            with self.assertRaises(WritesDisabled):check_call('ha_set_state',{'entity_id':'sensor.hap_bericht'},mode='observe')
            for entity in ('sensor.other','sensor.hausakku_regelmodus','switch.zigbee_blau'):
                with self.assertRaises(ValueError):check_call('ha_set_state',{'entity_id':entity},mode='publish')
            with self.assertRaises(ValueError):   # the report name is not an input helper
                check_call('ha_call_service',{'domain':'input_text','service':'set_value','entity_id':'input_text.hap_bericht'},mode='publish')
        finally:settings.use(old)
    def test_only_own_helper_values_written(self):
        with self.assertRaises(ValueError): check_call('ha_call_service',{'domain':'input_datetime','service':'set_datetime','entity_id':'input_datetime.other'})
        check_call('ha_call_service',{'domain':'input_datetime','service':'set_datetime','entity_id':'input_datetime.hap_plan_gueltig_bis'})


class FakeTransport:
    """Records calls and answers like the HA REST/WebSocket API."""
    def __init__(self):
        self.rest_calls=[];self.commands=[];self.states={'sensor.a':{'entity_id':'sensor.a','state':'5','attributes':{}}}
        self.schedules=[];self.helpers={'input_datetime':[],'input_text':[],'input_number':[],'input_boolean':[],'timer':[]}
    async def rest(self,method,path,json_body=None,params=None):
        self.rest_calls.append((method,path,json_body,params))
        if path.startswith('/config/automation/config/') and method=='GET':return {'id':'x'} if getattr(self,'automation_exists',False) else None
        if path.startswith('/states/'):return self.states.get(path.split('/states/')[1])
        if path.startswith('/history/period/'):
            return [[{'entity_id':'sensor.a','state':'5','last_changed':'2026-10-26T10:00:00+00:00'},{'state':'6','last_changed':'2026-10-26T11:00:00+00:00'}]]
        if path.startswith('/services/'):
            return {'changed_states':[],'service_response':{'prices':{'home':[]}}} if params else []
    async def command(self,**p):
        self.commands.append(p);t=p['type']
        if t=='recorder/statistics_during_period':return {'sensor.a':[{'start':3600000.,'end':7200000.,'change':1.5}]}
        if t=='recorder/get_statistics_metadata':return [{'statistic_id':'sensor.a','statistics_unit_of_measurement':'Wh'}]
        if t=='schedule/list':return list(self.schedules)
        if t=='schedule/create':self.schedules.append({'id':p['name'].lower().replace(' ','_'),**p});return {}   # HA derives the id from the name
        if t=='schedule/update':
            if 'name' not in p:raise RuntimeError('invalid_format')   # as Home Assistant answers
            return {}
        if t=='energy/get_prefs':return {'device_consumption':[]}
        if t.endswith('/list'):return list(self.helpers[t.split('/')[0]])
        if t.endswith('/create'):self.helpers[t.split('/')[0]].append({'id':p['name'].lower().replace(' ','_')});return {}

def run(coro):return asyncio.run(coro)

class NativeClientTests(unittest.TestCase):
    def setUp(self):self.t=FakeTransport();self.ha=HA(self.t,mode='publish')

    def test_state_single_and_list_with_missing(self):
        self.assertEqual(run(self.ha.call('ha_get_state',entity_id='sensor.a'))['state'],'5')
        r=run(self.ha.call('ha_get_state',entity_id=['sensor.a','sensor.gone']))
        self.assertEqual(list(r['states']),['sensor.a']);self.assertEqual(r['error_count'],1)

    def test_statistics_keep_mcp_shape_with_unit_and_no_truncation(self):
        r=run(self.ha.call('ha_get_history',source='statistics',entity_ids=['sensor.a'],start_time='2026-10-26T00:00:00+01:00',
                           end_time='2026-10-27T00:00:00+01:00',period='hour',statistic_types=['change'],limit=1000))
        e=r['entities'][0]
        self.assertEqual((e['entity_id'],e['unit_of_measurement'],e['has_more']),('sensor.a','Wh',False))
        from collector import normalize_statistics
        self.assertEqual(normalize_statistics(r)['sensor.a'],{3600.:1.5/1000})

    def test_history_groups_states_per_entity(self):
        r=run(self.ha.call('ha_get_history',entity_ids='sensor.a',start_time='2026-10-26T00:00:00+00:00',end_time='2026-10-27T00:00:00+00:00'))
        self.assertEqual(len(r['entities'][0]['states']),2)
        self.assertEqual(self.t.rest_calls[0][3]['filter_entity_id'],'sensor.a')

    def test_service_response_is_returned_for_prices(self):
        r=run(self.ha.call('ha_call_service',domain='tibber',service='get_prices',data={'start':'x','end':'y'},return_response=True))
        self.assertIn('prices',r['service_response'])
        self.assertEqual(self.t.rest_calls[0][3],{'return_response':'1'})

    def test_schedule_is_created_then_updated(self):
        week={d:[] for d in ('monday','tuesday','wednesday','thursday','friday','saturday','sunday')}
        run(self.ha.call('ha_config_set_helper',helper_type='schedule',helper_id='hap_netzladen',action='update',config=week))
        self.assertEqual([c['type'] for c in self.t.commands],['schedule/list','schedule/create'])
        self.t.commands.clear()
        run(self.ha.call('ha_config_set_helper',helper_type='schedule',helper_id='hap_netzladen',action='update',config=week))
        self.assertEqual([c['type'] for c in self.t.commands],['schedule/list','schedule/update'])
        self.assertEqual(self.t.commands[1]['schedule_id'],'hap_netzladen');self.assertIn('name',self.t.commands[1])

    def test_install_control_saves_the_blueprint_then_creates_the_automation(self):
        inputs={'charger_switch':'switch.c'}
        r=run(self.ha.install_control('blueprint: yaml','https://example/bp.yaml',inputs))
        self.assertEqual(r,{'automation':'automation.hausakku_planer_steuerung'})
        save=[c for c in self.t.commands if c['type']=='blueprint/save'][0]
        self.assertEqual((save['domain'],save['path'],save['yaml']),('automation','hausakku_planer/steuerung.yaml','blueprint: yaml'))
        post=[c for c in self.t.rest_calls if c[0]=='POST'][0]
        self.assertEqual(post[1],'/config/automation/config/hausakku_planer_steuerung')
        self.assertEqual(post[2]['use_blueprint'],{'path':'hausakku_planer/steuerung.yaml','input':inputs})
        self.assertNotIn('input_boolean.turn_on',str(self.t.rest_calls))      # the release switch is never touched
    def test_install_control_never_overwrites_and_respects_observe(self):
        self.t.automation_exists=True
        with self.assertRaises(ControlExists):run(self.ha.install_control('y','u',{}))
        self.assertFalse([c for c in self.t.commands if c['type']=='blueprint/save']);self.assertFalse([c for c in self.t.rest_calls if c[0]=='POST'])
        with self.assertRaises(WritesDisabled):run(HA(self.t,mode='observe').install_control('y','u',{}))
    def test_ensure_own_helpers_creates_once(self):
        created=run(self.ha.ensure_own_helpers());self.assertEqual(len(created),6)
        self.assertIn('input_boolean.hap_planer_freigabe',created);self.assertIn('timer.hap_schaltsperre',created)
        self.assertEqual(run(self.ha.ensure_own_helpers()),[])

    def test_observe_mode_refuses_every_write_but_allows_reads(self):
        observe=HA(self.t,mode='observe')
        run(observe.call('ha_get_state',entity_id='sensor.a'))
        run(observe.call('ha_call_service',domain='tibber',service='get_prices',data={},return_response=True))
        with self.assertRaises(WritesDisabled):
            run(observe.call('ha_call_service',domain='input_text',service='set_value',entity_id='input_text.hap_plan_status',data={'value':'x'}))
        with self.assertRaises(WritesDisabled):run(observe.ensure_own_helpers())
        self.assertFalse([c for c in self.t.rest_calls if c[0]=='POST' and 'input_text' in c[1]])

    def test_hardware_switching_is_never_possible(self):
        for mode in ('observe','publish','control'):
            with self.assertRaises(ValueError):check_call('ha_call_service',{'domain':'switch','service':'turn_on','entity_id':'switch.charger_plug'},mode)

class SettingsTests(unittest.TestCase):
    def test_unconfigured_role_is_named(self):
        s=settings.Settings({})
        with self.assertRaises(settings.NotConfigured) as ctx:s.entity('battery_soc')
        self.assertIn('Akku-Ladestand',str(ctx.exception))

    def test_missing_roles_by_stage(self):
        s=settings.Settings({'entities':{'battery_soc':'sensor.soc'}})
        self.assertIn('grid_import',s.missing('plan'));self.assertNotIn('battery_soc',s.missing('plan'))
        self.assertIn('charger_switch',s.missing('control'));self.assertNotIn('charger_switch',s.missing('plan'))

    def test_planner_config_is_neutral_and_takes_location_and_capacity(self):
        c=settings.Settings({'location':{'latitude':50.1,'longitude':8.6},'battery':{'capacity_kwh':10}}).planner_config()
        self.assertEqual((c['openmeteo_latitude'],c['capacity_kwh']),(50.1,10.))
        self.assertIsNone(settings.Settings({}).planner_config()['capacity_kwh'])
        self.assertEqual(settings.Settings({}).planner_config()['pv_forecast_source'],'ha_solarforecast')

    def test_save_roundtrip(self):
        import tempfile,pathlib
        p=pathlib.Path(tempfile.mkdtemp())/'settings.json'
        settings.save({'entities':{'battery_soc':'sensor.soc'}},p)
        self.assertEqual(settings.load(p).entity('battery_soc'),'sensor.soc')
        settings.use(None)

class NeutralDefaultsTests(unittest.TestCase):
    def test_planner_runs_with_neutral_defaults_and_settings_only(self):
        import json
        from pathlib import Path
        from planner import compute_plan
        fixture=json.loads((Path(__file__).parent/'fixtures/test_fixture_snapshot.json').read_text())
        cfg=settings.load().planner_config()
        cfg['capacity_kwh']=10.
        plan=compute_plan(fixture,cfg)
        self.assertEqual(plan['plan']['initial_kwh'],float(fixture['states']['sensor.hausbatterie_kwh']['state']))
        self.assertIn(plan['mode'],('shadow','live'))

    def test_battery_kwh_sensor_is_optional_but_capacity_then_required(self):
        import json,copy
        from pathlib import Path
        from planner import compute_plan
        fixture=json.loads((Path(__file__).parent/'fixtures/test_fixture_snapshot.json').read_text())
        data=copy.deepcopy(settings.load().data);data['entities']['battery_kwh']=None
        settings.use(data)
        try:
            cfg=settings.current().planner_config()
            with self.assertRaises(ValueError):compute_plan(fixture,cfg)
            cfg['capacity_kwh']=12.
            self.assertAlmostEqual(compute_plan(fixture,cfg)['plan']['initial_kwh'],12*float(fixture['states']['sensor.ant_bms_16_soc']['state'])/100)
        finally:settings.use(None)

if __name__=='__main__': unittest.main()

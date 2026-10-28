"""Offline execution of the control blueprint: its templates run in Jinja with Home Assistant's functions,
its action tree runs in a small interpreter. No Home Assistant needed."""
import copy, math, unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import yaml
from jinja2 import Environment, StrictUndefined

BLUEPRINT=Path(__file__).resolve().parents[3]/'blueprints/automation/hausakku_planer/steuerung.yaml'
TZ=ZoneInfo('Europe/Berlin')
NOW=datetime(2026,10,28,12,0,tzinfo=TZ)

class Input:
    def __init__(self,name):self.name=name

class Loader(yaml.SafeLoader):pass
Loader.add_constructor('!input',lambda l,n:Input(l.construct_scalar(n)))

def load():return yaml.load(BLUEPRINT.read_text(),Loader)

def input_defaults(blueprint):
    out={}
    def walk(inputs):
        for name,spec in inputs.items():
            if isinstance(spec,dict) and 'input' in spec and 'selector' not in spec:walk(spec['input'])
            else:out[name]=spec.get('default')
    walk(blueprint['blueprint']['input']);return out

def substitute(node,values):
    if isinstance(node,Input):return copy.deepcopy(values[node.name])
    if isinstance(node,dict):return {k:substitute(v,values) for k,v in node.items()}
    if isinstance(node,list):return [substitute(v,values) for v in node]
    return node

REQUIRED=dict(charger_switch='switch.charger',inverter_switch='switch.inverter',soc_sensor='sensor.soc',
              charge_schedule='schedule.charge',serve_schedule='schedule.serve',plan_valid_until='input_datetime.until',
              target_soc='input_number.target',release_switch='input_boolean.release',owner_marker='input_boolean.owner',
              cooldown_timer='timer.cooldown')
PROTECTION=dict(battery_voltage='sensor.voltage',temperature_sensors=['sensor.t1','sensor.t2','sensor.t3','sensor.t4'],
                bms_online='binary_sensor.online',bms_heartbeat='sensor.heartbeat',uptime_sensor='sensor.uptime',
                charge_mos='sensor.cmos',discharge_mos='sensor.dmos',discharge_block='input_boolean.empty')

def finite(x):
    try:return not isinstance(x,bool) and math.isfinite(float(x))
    except (TypeError,ValueError):return False

class StopRun(Exception):pass

class Sim:
    """One automation run against fake states."""
    def __init__(self,inputs=None,states=None,attrs=None):
        self.bp=load()
        values={**input_defaults(self.bp),**REQUIRED,**(inputs or {})}
        self.bp=substitute({k:v for k,v in self.bp.items() if k!='blueprint'},values)
        expiry=(NOW+timedelta(days=1)).timestamp()
        self.states={'switch.charger':'off','switch.inverter':'on','sensor.soc':'38','schedule.charge':'off','schedule.serve':'on',
                     'input_datetime.until':'2026-10-29 12:00:00','input_number.target':'60','input_boolean.release':'on',
                     'input_boolean.owner':'off','timer.cooldown':'idle',
                     'sensor.voltage':'52.4','sensor.t1':'21','sensor.t2':'22','sensor.t3':'19','sensor.t4':'19',
                     'binary_sensor.online':'on','sensor.heartbeat':'1234','sensor.uptime':(NOW-timedelta(hours=5)).isoformat(),
                     'sensor.cmos':'on','sensor.dmos':'on','input_boolean.empty':'off'}
        self.attrs={'input_datetime.until':{'timestamp':expiry},
                    'schedule.charge':{'plan_date':NOW.date().isoformat()},'schedule.serve':{'plan_date':NOW.date().isoformat()}}
        self.updated={'sensor.heartbeat':NOW-timedelta(seconds=10)}
        self.states.update(states or {});self.attrs.update(attrs or {})
        self.calls=[];self.vars={};self.fail_off=False;self.on_delay=None
        self.env=Environment(undefined=StrictUndefined)
        g=self.env.globals
        g['states']=lambda e:self.states.get(e,'unknown')
        g['is_state']=lambda e,s:self.states.get(e,'unknown')==s
        g['state_attr']=lambda e,a:self.attrs.get(e,{}).get(a)
        g['has_value']=lambda e:self.states.get(e,'unknown') not in ('unknown','unavailable')
        g['is_number']=finite
        g['now']=lambda:NOW
        g['as_timestamp']=self.as_timestamp
        g['expand']=lambda e:[SimpleNamespace(last_updated=self.updated.get(e,NOW-timedelta(seconds=5)))]
    @staticmethod
    def as_timestamp(value,default=None):
        try:
            if isinstance(value,datetime):return value.timestamp()
            return datetime.fromisoformat(str(value)).timestamp()
        except (TypeError,ValueError):return default
    def render(self,template):
        text=self.env.from_string(template).render(**self.vars).strip()
        low=text.lower()
        if low in ('true','false'):return low=='true'
        try:return int(text)
        except ValueError:return text
    def compute_variables(self):
        for name,value in self.bp['variables'].items():
            self.vars[name]=self.render(value) if isinstance(value,str) and '{' in value else value
    def cond(self,c):
        if isinstance(c,str):return bool(self.render(c))
        t=c['condition']
        if t=='and':return all(self.cond(x) for x in c['conditions'])
        if t=='or':return any(self.cond(x) for x in c['conditions'])
        if t=='not':return not all(self.cond(x) for x in c['conditions'])
        if t=='template':return bool(self.render(c['value_template']))
        if t=='state':
            v=self.states.get(c['entity_id'],'unknown');want=c['state'];return v in want if isinstance(want,list) else v==want
        raise AssertionError(c)
    def seq(self,items):
        for x in items:
            if 'variables' in x:
                for k,v in x['variables'].items():self.vars[k]=self.render(v)
            elif 'condition' in x:
                if not self.cond(x):raise StopRun()
            elif 'if' in x:self.seq(x.get('then',[]) if all(self.cond(c) for c in x['if']) else x.get('else',[]))
            elif 'stop' in x:raise StopRun()
            elif 'choose' in x:
                chosen=next((b['sequence'] for b in x['choose'] if all(self.cond(c) for c in b['conditions'])),x.get('default',[]));self.seq(chosen)
            elif 'delay' in x:
                if self.on_delay:self.on_delay(self)
            elif 'wait_template' in x:
                if not self.render(x['wait_template']) and x.get('continue_on_timeout') is False:raise StopRun()
            elif 'action' in x:self.act(x)
            else:raise AssertionError(x)
    def act(self,x):
        service=x['action'];entity=x['target']['entity_id'];self.calls.append((service,entity))
        if service=='timer.start':self.states[entity]='active'
        elif service.endswith('.turn_off'):
            if not (self.fail_off and entity.startswith('switch.')):self.states[entity]='off'
        elif service.endswith('.turn_on'):
            if entity.startswith('switch.'):
                other='switch.inverter' if entity=='switch.charger' else 'switch.charger'
                if self.states.get(other)!='off':raise AssertionError('would energize simultaneously')
            self.states[entity]='on'
        else:raise AssertionError(service)
    def mode(self):
        self.compute_variables();self.seq(self.bp['actions'][:1]);return self.vars['mode']
    def run(self):
        self.compute_variables()
        try:self.seq(self.bp['actions'])
        except StopRun:pass
        return self

def mode(protected=False,**kw):
    inputs=dict(PROTECTION) if protected else {}
    states=kw.pop('states',{});attrs=kw.pop('attrs',{});inputs.update(kw.pop('inputs',{}))
    return Sim(inputs,states,attrs).mode()

def charge_plan(**states):
    return dict(states,**{'schedule.charge':'on','schedule.serve':'off'})

class ModeBasicTests(unittest.TestCase):
    def test_no_release_is_manual_even_with_bad_data(self):
        self.assertEqual(mode(states={'input_boolean.release':'off','sensor.soc':'unknown'}),'manuell')
    def test_serving_by_plan(self):self.assertEqual(mode(),'versorgen')
    def test_hold_when_no_schedule_is_active(self):
        self.assertEqual(mode(states={'schedule.serve':'off'}),'aufheben')
    def test_unknown_soc_stops(self):
        for value in ('unknown','unavailable','nan','inf','101','-1'):
            with self.subTest(value=value):self.assertEqual(mode(states={'sensor.soc':value}),'sicher_aus')
    def test_unknown_switch_stops(self):self.assertEqual(mode(states={'switch.charger':'unavailable'}),'sicher_aus')
    def test_both_on_stops(self):self.assertEqual(mode(states={'switch.charger':'on'}),'sicher_aus')
    def test_overlapping_schedules_stop(self):
        self.assertEqual(mode(states={'schedule.charge':'on'}),'sicher_aus')
    def test_schedule_for_another_day_stops(self):
        self.assertEqual(mode(attrs={'schedule.serve':{'plan_date':'2026-10-27'}}),'sicher_aus')
    def test_expired_plan_falls_back_to_supplying(self):
        self.assertEqual(mode(attrs={'input_datetime.until':{'timestamp':NOW.timestamp()-1}}),'plan_fallback')
    def test_expired_plan_cannot_authorise_charging(self):
        self.assertEqual(mode(states=charge_plan(),attrs={'input_datetime.until':{'timestamp':NOW.timestamp()-1}}),'plan_fallback')
    def test_missing_expiry_means_expired(self):self.assertEqual(mode(attrs={'input_datetime.until':{}}),'plan_fallback')

class ModeReserveTests(unittest.TestCase):
    def test_reserve_stops_discharge(self):self.assertEqual(mode(states={'sensor.soc':'10'}),'reserve')
    def test_just_above_reserve_keeps_supplying(self):self.assertEqual(mode(states={'sensor.soc':'11'}),'versorgen')
    def test_reserve_hysteresis_needs_resume_level_when_inverter_is_off(self):
        off={'switch.inverter':'off'}
        self.assertEqual(mode(states={**off,'sensor.soc':'11','schedule.serve':'on'}),'reserve')
        self.assertEqual(mode(states={**off,'sensor.soc':'12'}),'versorgen')
    def test_charging_allowed_to_recover_an_empty_battery(self):
        self.assertEqual(mode(states=charge_plan(**{'sensor.soc':'5'})),'netzladen')
    def test_custom_reserve_limits(self):
        self.assertEqual(mode(inputs={'reserve_stop_percent':20,'reserve_resume_percent':25},states={'sensor.soc':'20'}),'reserve')

class ModeChargeTests(unittest.TestCase):
    def test_charge_target_hysteresis(self):
        c=lambda soc,**kw:mode(states=charge_plan(**{'input_number.target':'50','sensor.soc':soc},**kw))
        self.assertEqual(c('48'),'netzladen');self.assertEqual(c('49'),'ladepause')
        self.assertEqual(c('49',**{'switch.charger':'on','switch.inverter':'off'}),'netzladen')
        self.assertEqual(c('50',**{'switch.charger':'on','switch.inverter':'off'}),'ladepause')
    def test_grid_ceiling_never_exceeds_the_limit(self):
        self.assertEqual(mode(states=charge_plan(**{'input_number.target':'100','sensor.soc':'90','switch.charger':'on','switch.inverter':'off'})),'ladepause')
        self.assertEqual(mode(inputs={'grid_charge_max_percent':70},states=charge_plan(**{'input_number.target':'100','sensor.soc':'70'})),'ladepause')
    def test_missing_target_cannot_charge(self):
        self.assertEqual(mode(states=charge_plan(**{'input_number.target':'unknown'})),'ladepause')

class ModeProtectionTests(unittest.TestCase):
    def test_healthy_protected_system_behaves_the_same(self):
        self.assertEqual(mode(True),'versorgen')
        self.assertEqual(mode(True,states=charge_plan()),'netzladen')
    def test_stale_heartbeat_stops(self):
        s=Sim(dict(PROTECTION));s.updated['sensor.heartbeat']=NOW-timedelta(seconds=121);self.assertEqual(s.mode(),'sicher_aus')
    def test_heartbeat_restored_at_startup_does_not_count(self):
        s=Sim(dict(PROTECTION));s.states['sensor.uptime']=(NOW-timedelta(seconds=3)).isoformat();self.assertEqual(s.mode(),'sicher_aus')
    def test_unknown_heartbeat_stops(self):self.assertEqual(mode(True,states={'sensor.heartbeat':'unavailable'}),'sicher_aus')
    def test_offline_stops(self):self.assertEqual(mode(True,states={'binary_sensor.online':'off'}),'sicher_aus')
    def test_unplausible_or_unknown_voltage_stops(self):
        for value in ('unknown','39','61','nan'):
            with self.subTest(value=value):self.assertEqual(mode(True,states={'sensor.voltage':value}),'sicher_aus')
    def test_low_voltage_prevents_discharge(self):self.assertEqual(mode(True,states={'sensor.voltage':'48.9'}),'reserve')
    def test_voltage_hysteresis_with_inverter_off(self):
        off={'switch.inverter':'off','sensor.voltage':'49.1'}
        self.assertEqual(mode(True,states=off),'reserve')
        self.assertEqual(mode(True,states={**off,'sensor.voltage':'49.2'}),'versorgen')
    def test_high_voltage_blocks_charging_only(self):
        self.assertEqual(mode(True,states=charge_plan(**{'sensor.voltage':'56'})),'ladepause')
        self.assertEqual(mode(True,states={'sensor.voltage':'56'}),'versorgen')
    def test_temperature_limits(self):
        cold={f'sensor.t{i}':'2' for i in range(1,5)};hot={f'sensor.t{i}':'46' for i in range(1,5)}
        self.assertEqual(mode(True,states=charge_plan(**cold)),'ladepause')
        self.assertEqual(mode(True,states=cold),'versorgen')
        self.assertEqual(mode(True,states=hot),'sicher_aus')
        self.assertEqual(mode(True,states={'sensor.t3':'-1'}),'sicher_aus')
        self.assertEqual(mode(True,states={'sensor.t3':'unknown'}),'sicher_aus')
    def test_mosfets_respected(self):
        self.assertEqual(mode(True,states=charge_plan(**{'sensor.cmos':'off'})),'ladepause')
        self.assertEqual(mode(True,states={'sensor.dmos':'off'}),'reserve')
    def test_full_battery_with_overcharge_protection_may_still_supply(self):
        for status in ('Overcharge protection','battery full'):
            self.assertEqual(mode(True,states={'sensor.cmos':status,'sensor.soc':'100'}),'versorgen')
            self.assertEqual(mode(True,states={'sensor.cmos':status,'sensor.soc':'100','schedule.serve':'off'}),'aufheben')
            self.assertEqual(mode(True,states=charge_plan(**{'sensor.cmos':status,'sensor.soc':'100'})),'ladepause')
    def test_real_charge_mosfet_faults_stop(self):
        for status in ('over current protection','short circuit protection','battery over temperature protection','unknown','unavailable',''):
            self.assertEqual(mode(True,states={'sensor.cmos':status}),'sicher_aus',status)
    def test_external_block_prevents_discharge_but_not_charging(self):
        self.assertEqual(mode(True,states={'input_boolean.empty':'on'}),'reserve')
        self.assertEqual(mode(True,states=charge_plan(**{'input_boolean.empty':'on'})),'netzladen')
        self.assertEqual(mode(True,states={'input_boolean.empty':'unknown'}),'sicher_aus')
    def test_optional_sensors_left_empty_are_not_required(self):
        self.assertEqual(mode(False,states={'sensor.voltage':'unknown','sensor.t1':'unknown'}),'versorgen')

def sim(mode_name,**kw):
    """A run whose schedules produce `mode_name` in a healthy system."""
    plan={'netzladen':charge_plan(),'versorgen':{},'aufheben':{'schedule.serve':'off'},'sicher_aus':{'schedule.charge':'on'},
          'reserve':{'sensor.soc':'8'}}[mode_name]
    return Sim(states={**plan,**kw.pop('states',{})},**kw)

class ActionTests(unittest.TestCase):
    def test_no_release_and_not_owned_does_not_touch_hardware(self):
        s=Sim(states={'input_boolean.release':'off'}).run();self.assertEqual(s.calls,[])
    def test_release_off_releases_owned_devices(self):
        s=Sim(states={'input_boolean.release':'off','input_boolean.owner':'on','switch.charger':'on','switch.inverter':'off'}).run()
        self.assertEqual((s.states['switch.charger'],s.states['switch.inverter'],s.states['input_boolean.owner']),('off','off','off'))
    def test_release_off_keeps_ownership_when_off_not_confirmed(self):
        s=Sim(states={'input_boolean.release':'off','input_boolean.owner':'on','switch.charger':'on','switch.inverter':'off'});s.fail_off=True;s.run()
        self.assertEqual(s.states['input_boolean.owner'],'on')
    def test_charge_turns_off_inverter_then_starts_charger(self):
        s=sim('netzladen').run()
        self.assertEqual((s.states['switch.charger'],s.states['switch.inverter']),('on','off'))
        self.assertLess(s.calls.index(('switch.turn_off','switch.inverter')),s.calls.index(('switch.turn_on','switch.charger')))
        self.assertLess(s.calls.index(('timer.start','timer.cooldown')),s.calls.index(('switch.turn_on','switch.charger')))
    def test_unconfirmed_off_prevents_start(self):
        s=sim('netzladen');s.fail_off=True;s.run();self.assertNotIn(('switch.turn_on','switch.charger'),s.calls)
    def test_release_removed_during_dead_time_prevents_start(self):
        s=sim('netzladen');s.on_delay=lambda x:x.states.update({'input_boolean.release':'off'});s.run()
        self.assertNotIn(('switch.turn_on','switch.charger'),s.calls)
    def test_mode_changed_during_dead_time_prevents_start(self):
        s=sim('netzladen');s.on_delay=lambda x:x.states.update({'sensor.soc':'60'});s.run()   # target reached meanwhile
        self.assertNotIn(('switch.turn_on','switch.charger'),s.calls)
        s=sim('netzladen');s.on_delay=lambda x:x.states.update({'schedule.charge':'off'});s.run()
        self.assertNotIn(('switch.turn_on','switch.charger'),s.calls)
        s=sim('versorgen',states={'switch.inverter':'off'});s.on_delay=lambda x:x.states.update({'sensor.soc':'8'});s.run()
        self.assertNotIn(('switch.turn_on','switch.inverter'),s.calls)
    def test_plan_expiring_during_dead_time_prevents_charging(self):
        s=sim('netzladen');s.on_delay=lambda x:x.attrs.update({'input_datetime.until':{'timestamp':NOW.timestamp()-1}});s.run()
        self.assertNotIn(('switch.turn_on','switch.charger'),s.calls)
    def test_immediate_charge_stop_ignores_cooldown(self):
        s=Sim(states={'schedule.serve':'off','switch.charger':'on','switch.inverter':'off','timer.cooldown':'active','sensor.soc':'60'}).run()
        self.assertEqual(s.states['switch.charger'],'off')
    def test_regular_mode_change_obeys_cooldown(self):
        s=sim('netzladen',states={'timer.cooldown':'active'}).run()
        self.assertEqual((s.states['switch.inverter'],s.states['switch.charger']),('on','off'))
    def test_protective_stop_ignores_cooldown(self):
        s=sim('reserve',states={'timer.cooldown':'active'}).run();self.assertEqual(s.states['switch.inverter'],'off')
    def test_invalid_data_turns_both_off(self):
        s=sim('sicher_aus').run();self.assertEqual((s.states['switch.charger'],s.states['switch.inverter']),('off','off'))
    def test_supply_after_expiry_waits_for_off_then_starts_inverter(self):
        s=Sim(states={'switch.charger':'on','switch.inverter':'off','timer.cooldown':'idle'},attrs={'input_datetime.until':{'timestamp':NOW.timestamp()-1}}).run()
        self.assertEqual(s.states['switch.charger'],'off');s.states['timer.cooldown']='idle';s.run()
        self.assertEqual(s.states['switch.inverter'],'on')
    def test_existing_supply_state_is_not_toggled(self):
        s=sim('versorgen').run();self.assertFalse(any(a.startswith('switch.') for a,e in s.calls))
    def test_hold_turns_both_off(self):
        s=sim('aufheben').run();self.assertEqual((s.states['switch.charger'],s.states['switch.inverter']),('off','off'))
    def test_never_both_on(self):
        for name in ('netzladen','versorgen','aufheben','reserve','sicher_aus'):
            for charger,inverter in (('on','off'),('off','on'),('off','off')):
                with self.subTest(mode=name,start=(charger,inverter)):
                    s=sim(name,states={'switch.charger':charger,'switch.inverter':inverter}).run()
                    self.assertFalse(s.states['switch.charger']=='on' and s.states['switch.inverter']=='on')

class StructureTests(unittest.TestCase):
    def walk(self,x):
        if isinstance(x,dict):
            yield x
            for v in x.values():yield from self.walk(v)
        elif isinstance(x,list):
            for v in x:yield from self.walk(v)
    def test_declared_inputs_match_used_inputs(self):
        bp=load();declared=set(input_defaults(bp))
        used={n.name for n in self.walk_inputs(bp)}
        self.assertEqual(declared-used,set());self.assertEqual(used-declared,set())
    def walk_inputs(self,x):
        if isinstance(x,Input):yield x
        elif isinstance(x,dict):
            for k,v in x.items():
                if k!='blueprint':yield from self.walk_inputs(v)
        elif isinstance(x,list):
            for v in x:yield from self.walk_inputs(v)
    def test_restart_mode_and_start_and_watchdog_triggers(self):
        bp=load();self.assertEqual(bp['mode'],'restart')
        self.assertTrue(any(t.get('trigger')=='homeassistant' for t in bp['triggers']))
        self.assertTrue(any(t.get('trigger')=='time_pattern' for t in bp['triggers']))
    def test_no_device_ids_and_only_two_switches_are_energised(self):
        nodes=list(self.walk(load()['actions']))
        self.assertFalse(any('device_id' in n for n in nodes))
        on=[n for n in nodes if n.get('action')=='switch.turn_on']
        self.assertEqual({n['target']['entity_id'].name for n in on},{'charger_switch','inverter_switch'})
    def test_every_turn_on_is_preceded_by_confirmed_off_dead_time_and_recheck(self):
        count=0
        for branch in self.walk(load()['actions']):
            seq=branch.get('sequence')
            if not isinstance(seq,list):continue
            for i,item in enumerate(seq):
                if item.get('action')=='switch.turn_on':
                    count+=1;earlier=seq[:i]
                    self.assertTrue(any('wait_template' in n and n.get('continue_on_timeout') is False for n in earlier))
                    self.assertTrue(any(n.get('delay',{}).get('seconds')==2 for n in earlier))
                    self.assertTrue(any('variables' in n for n in earlier))
                    self.assertTrue(any(isinstance(n.get('entity_id'),Input) and n['entity_id'].name=='cooldown_timer' for n in earlier))
        self.assertEqual(count,2)
    def test_on_confirmation_allows_slow_devices(self):
        waits=[n for n in self.walk(load()['actions']) if 'wait_template' in n and "'on'" in n['wait_template']]
        self.assertEqual(len(waits),2)
        self.assertTrue(all(n['timeout']['seconds']==30 and n['continue_on_timeout'] is False for n in waits))
    def test_mode_is_recomputed_from_the_same_definition(self):
        acts=load()['actions'];first=acts[0]['variables']
        again=[n for n in self.walk(acts) if n.get('variables') is first]
        self.assertGreaterEqual(len(again),3)

if __name__=='__main__':unittest.main()

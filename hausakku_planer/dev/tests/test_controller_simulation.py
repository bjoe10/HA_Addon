"""Offline execution of the actual generated HA action tree. No HA connection."""
import unittest
from controller_config import automation_config,PERMISSION,OWNER,GUARD,TIMER,CHARGER,INVERTER

class StopRun(Exception):pass
class Sim:
    def __init__(self,mode='versorgen',**kw):
        self.states={PERMISSION:'on',OWNER:'off',GUARD:mode,TIMER:'idle',CHARGER:'off',INVERTER:'off',
                     'sensor.ant_bms_16_soc':'38','input_number.hausakku_ziel_soc':'60','sensor.hausakku_betriebsstrategie':'netzladen'}
        self.states.update(kw);self.calls=[];self.fail_off=False;self.on_delay=None
    def cond(self,c):
        t=c.get('condition')
        if t=='and':return all(self.cond(x) for x in c['conditions'])
        if t=='or':return any(self.cond(x) for x in c['conditions'])
        if t=='not':return not all(self.cond(x) for x in c['conditions'])
        if t=='state':
            v=self.states.get(c['entity_id'],'unknown');want=c['state'];return v in want if isinstance(want,list) else v==want
        if t=='numeric_state':
            try:
                value=float(self.states[c['entity_id']]);bound=c['below'];bound=float(self.states[bound] if isinstance(bound,str) else bound)
                return value<bound
            except (KeyError,ValueError):return False
        raise AssertionError(c)
    def seq(self,items):
        for x in items:
            if 'condition' in x:
                if not self.cond(x):raise StopRun()
            elif 'if' in x:self.seq(x.get('then',[]) if all(self.cond(c) for c in x['if']) else x.get('else',[]))
            elif 'stop' in x:raise StopRun()
            elif 'choose' in x:
                chosen=next((b['sequence'] for b in x['choose'] if all(self.cond(c) for c in b['conditions'])),x.get('default',[]));self.seq(chosen)
            elif 'delay' in x:
                if self.on_delay:self.on_delay(self)
            elif 'wait_template' in x:
                # Builder emits only a direct is_state wait, tested separately in HA.
                tokens=x['wait_template'].split("'");entity,want=tokens[1],tokens[3]
                if self.states.get(entity)!=want and x.get('continue_on_timeout') is False:raise StopRun()
            elif 'action' in x:
                service=x['action'];entity=x['target']['entity_id'];self.calls.append((service,entity))
                if service=='timer.start':self.states[entity]='active'
                elif service.endswith('.turn_off'):
                    if not (self.fail_off and entity in (CHARGER,INVERTER)):self.states[entity]='off'
                elif service.endswith('.turn_on'):
                    if entity in (CHARGER,INVERTER):
                        other=INVERTER if entity==CHARGER else CHARGER
                        if self.states.get(other)!='off':raise AssertionError('would energize simultaneously')
                    self.states[entity]='on'
                else:raise AssertionError(service)
            else:raise AssertionError(x)
    def run(self):
        try:self.seq(automation_config()['actions'])
        except StopRun:pass
        return self

class ActionSimulationTests(unittest.TestCase):
    def test_disabled_and_unowned_does_not_touch_hardware(self):
        s=Sim(**{PERMISSION:'off',INVERTER:'on'}).run();self.assertEqual(s.calls,[])
    def test_disabling_owned_controller_turns_both_off_and_releases_ownership(self):
        s=Sim(**{PERMISSION:'off',OWNER:'on',CHARGER:'on'}).run()
        self.assertEqual((s.states[CHARGER],s.states[INVERTER],s.states[OWNER]),('off','off','off'))
    def test_charge_turns_off_wr_then_starts_charger(self):
        s=Sim('netzladen',**{INVERTER:'on'}).run()
        self.assertEqual((s.states[CHARGER],s.states[INVERTER]),('on','off'))
        self.assertLess(s.calls.index(('switch.turn_off',INVERTER)),s.calls.index(('switch.turn_on',CHARGER)))
    def test_opposing_device_not_confirmed_off_prevents_start(self):
        s=Sim('netzladen',**{INVERTER:'on'});s.fail_off=True;s.run()
        self.assertNotIn(('switch.turn_on',CHARGER),s.calls)
    def test_permission_removed_during_deadtime_prevents_start(self):
        s=Sim('netzladen');s.on_delay=lambda x:x.states.update({PERMISSION:'off'});s.run()
        self.assertNotIn(('switch.turn_on',CHARGER),s.calls)
    def test_mode_changed_during_deadtime_prevents_start(self):
        s=Sim('netzladen');s.on_delay=lambda x:x.states.update({GUARD:'reserve'});s.run()
        self.assertNotIn(('switch.turn_on',CHARGER),s.calls)
    def test_immediate_charge_stop_ignores_active_cooldown(self):
        s=Sim('ladepause',**{CHARGER:'on',TIMER:'active'}).run();self.assertEqual(s.states[CHARGER],'off')
    def test_regular_mode_change_obeys_cooldown(self):
        s=Sim('netzladen',**{TIMER:'active',INVERTER:'on'}).run()
        self.assertEqual(s.states[INVERTER],'on');self.assertEqual(s.states[CHARGER],'off')
    def test_safety_stop_ignores_cooldown(self):
        s=Sim('reserve',**{TIMER:'active',INVERTER:'on'}).run();self.assertEqual(s.states[INVERTER],'off')
    def test_expired_plan_stops_charging_before_fallback(self):
        s=Sim('plan_fallback',**{CHARGER:'on'}).run()
        self.assertEqual(s.states[CHARGER],'off');self.assertEqual(s.states[INVERTER],'off')
        s.states[TIMER]='idle';s.run();self.assertEqual(s.states[INVERTER],'on')
    def test_existing_serve_state_is_not_toggled(self):
        s=Sim('versorgen',**{INVERTER:'on'}).run();self.assertFalse(any(a.startswith('switch.') for a,e in s.calls))
    def test_missing_target_prevents_start_even_if_guard_lagged(self):
        s=Sim('netzladen',**{'input_number.hausakku_ziel_soc':'0'}).run()
        self.assertNotIn(('switch.turn_on',CHARGER),s.calls)
if __name__=='__main__':unittest.main()

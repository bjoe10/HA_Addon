"""Same guard template as HA, evaluated against explicit test fixtures."""
import math
import unittest
from jinja2 import Environment,StrictUndefined
from controller_config import GUARD_LOGIC,automation_config

def fixture(**kw):
    return dict(enabled=True,online=True,hb_age=1,hb_after_start=True,soc='38',voltage='52.4',temps=['21','22','19','19'],
        charge_mos='on',discharge_mos='on',low_batt='off',reserve='off',low_voltage='off',
        legacy_block='off',charger='off',inverter='on',plan='versorgen',plan_valid=True,
        target='60',**{})|kw

def render(**kw):
    env=Environment(undefined=StrictUndefined)
    env.globals['is_number']=lambda x: not isinstance(x,bool) and _finite(x)
    return env.from_string(GUARD_LOGIC).render(v=fixture(**kw)).strip()
def _finite(x):
    try:return math.isfinite(float(x))
    except (ValueError,TypeError):return False

class GuardTests(unittest.TestCase):
    def test_no_permission_is_manual_even_with_bad_data(self):self.assertEqual(render(enabled=False,soc='unknown'),'manuell')
    def test_normal_serving(self):self.assertEqual(render(),'versorgen')
    def test_hold(self):self.assertEqual(render(plan='aufheben'),'aufheben')
    def test_stale_heartbeat_stops(self):self.assertEqual(render(hb_age=121),'sicher_aus')
    def test_offline_stops(self):self.assertEqual(render(online=False),'sicher_aus')
    def test_unknown_and_nonfinite_values_stop(self):
        for value in ['unknown','unavailable','nan','inf']:
            with self.subTest(value=value):self.assertEqual(render(soc=value),'sicher_aus')
    def test_unknown_switch_stops(self):self.assertEqual(render(charger='unavailable'),'sicher_aus')
    def test_both_on_stops(self):self.assertEqual(render(charger='on',inverter='on'),'sicher_aus')
    def test_reserve_prevents_discharge(self):self.assertEqual(render(reserve='on'),'reserve')
    def test_low_voltage_prevents_discharge(self):self.assertEqual(render(low_voltage='on'),'reserve')
    def test_charge_allowed_to_recover_empty_battery(self):
        self.assertEqual(render(plan='netzladen',soc='5',reserve='on',low_batt='on',low_voltage='on'),'netzladen')
    def test_charge_target_hysteresis(self):
        self.assertEqual(render(plan='netzladen',target='50',soc='48'),'netzladen')
        self.assertEqual(render(plan='netzladen',target='50',soc='49'),'ladepause')
        self.assertEqual(render(plan='netzladen',target='50',soc='49',charger='on',inverter='off'),'netzladen')
        self.assertEqual(render(plan='netzladen',target='50',soc='50',charger='on',inverter='off'),'ladepause')
    def test_grid_ceiling_never_exceeds_90(self):
        self.assertEqual(render(plan='netzladen',target='100',soc='90',charger='on',inverter='off'),'ladepause')
    def test_missing_target_cannot_charge(self):
        self.assertEqual(render(plan='netzladen',target='unknown'),'ladepause')
    def test_temperature_charge_and_discharge_limits(self):
        self.assertEqual(render(plan='netzladen',temps=['2']*4),'ladepause')
        self.assertEqual(render(temps=['2']*4),'versorgen')
        self.assertEqual(render(temps=['46']*4),'sicher_aus')
    def test_mosfets_respected(self):
        self.assertEqual(render(plan='netzladen',charge_mos='off'),'ladepause')
        self.assertEqual(render(discharge_mos='off'),'reserve')
    def test_full_battery_with_overcharge_protection_may_still_supply(self):
        # 26.10.2026: a full battery makes the BMS report 'Overcharge protection' on the charge
        # MOSFET. That is normal; it must not force both devices off (the BMS protects upwards).
        for status in ('overcharge protection','battery full'):
            self.assertEqual(render(charge_mos=status,soc='100'),'versorgen')
            self.assertEqual(render(charge_mos=status,soc='100',plan='aufheben'),'aufheben')
            # the grid charger is never allowed while the charge MOSFET is not 'on'
            self.assertEqual(render(plan='netzladen',charge_mos=status,soc='100'),'ladepause')
    def test_real_charge_mosfet_faults_still_stop(self):
        for status in ('over current protection','short circuit protection','battery over temperature protection','unknown','unavailable',''):
            self.assertEqual(render(charge_mos=status),'sicher_aus',status)
    def test_expired_plan_cannot_authorize_charging(self):
        self.assertEqual(render(plan='netzladen',plan_valid=False),'plan_fallback')
    def test_overlap_or_bad_plan_stops(self):self.assertEqual(render(plan='fehler'),'sicher_aus')
    def test_unknown_plan_falls_back_without_grid_charge(self):self.assertEqual(render(plan='unknown'),'plan_fallback')
    def test_missing_orphan_legacy_helper_does_not_block(self):self.assertEqual(render(legacy_block='absent'),'versorgen')
    def test_existing_but_unknown_legacy_helper_fails_closed(self):self.assertEqual(render(legacy_block='unknown'),'sicher_aus')
    def test_legacy_external_block_respected(self):self.assertEqual(render(legacy_block='on'),'sicher_aus')

class StructureTests(unittest.TestCase):
    def walk(self,x):
        if isinstance(x,dict):
            yield x
            for v in x.values():yield from self.walk(v)
        elif isinstance(x,list):
            for v in x:yield from self.walk(v)
    def test_automation_has_native_permission_condition_and_no_device_ids(self):
        c=automation_config();nodes=list(self.walk(c))
        self.assertEqual(c['mode'],'restart')
        self.assertFalse(any('device_id' in n for n in nodes))
        self.assertTrue(any(n.get('entity_id')=='input_boolean.hausakku_planer_freigabe' and n.get('state')=='on' for n in nodes))
        self.assertTrue(any(n.get('trigger')=='homeassistant' for n in nodes))
        self.assertTrue(any(n.get('trigger')=='time_pattern' for n in nodes))
    def test_on_confirmation_allows_slow_device_acknowledgement(self):
        waits=[n for n in self.walk(automation_config()) if 'wait_template' in n and "'on'" in n['wait_template']]
        self.assertEqual(len(waits),2)
        self.assertTrue(all(n['timeout']['seconds']==30 and n['continue_on_timeout'] is False for n in waits))
    def test_only_intended_switches_can_be_energized(self):
        on=[n for n in self.walk(automation_config()) if n.get('action')=='switch.turn_on']
        self.assertEqual({n['target']['entity_id'] for n in on},{'switch.charger_plug','switch.inverter_plug'})
    def test_every_on_is_preceded_by_confirmed_off_deadtime_and_recheck(self):
        seqs=[n for n in self.walk(automation_config()) if isinstance(n.get('sequence'),list)]
        count=0
        for branch in seqs:
            seq=branch['sequence']
            for i,item in enumerate(seq):
                if item.get('action')=='switch.turn_on':
                    count+=1
                    earlier=seq[:i]
                    self.assertTrue(any('wait_template' in n and n.get('continue_on_timeout') is False for n in earlier))
                    self.assertTrue(any(n.get('delay',{}).get('seconds')==2 for n in earlier))
                    self.assertTrue(any(n.get('condition')=='state' and n.get('entity_id')=='sensor.hausakku_regelmodus' for n in earlier))
                    self.assertTrue(any(n.get('condition')=='state' and n.get('entity_id')=='timer.hausakku_schaltsperre' for n in earlier))
        self.assertEqual(count,2)
if __name__=='__main__':unittest.main()

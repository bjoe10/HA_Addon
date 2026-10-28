import unittest
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from planner import schedule_payloads, compute_plan

class PlannerTests(unittest.TestCase):

    def test_payload_mapping_preserves_metadata_and_excludes_hold(self):
        w={d:[] for d in ('mon','tue','wed','thu','fri','sat','sun')}
        w['sun']=[{'start':'01:00','end':'02:00','mode':'charge','data':{'plan_date':'2026-10-18'}}, {'start':'02:00','end':'03:00','mode':'hold','data':{'plan_date':'2026-10-18'}}, {'start':'03:00','end':'04:00','mode':'serve','data':{'plan_date':'2026-10-18'}}]
        charge,serve=schedule_payloads(w)
        self.assertEqual(charge['sunday'][0]['from'],'01:00')
        self.assertEqual(len(charge['sunday']),1)
        self.assertEqual(len(serve['sunday']),1)
        self.assertEqual(charge['sunday'][0]['data']['plan_date'],'2026-10-18')
    def test_real_snapshot_end_to_end(self):
        import json
        from pathlib import Path
        base=Path(__file__).parent
        if not (base/'fixtures/test_fixture_snapshot.json').exists(): self.skipTest('Local integration snapshot not available')
        config=json.loads((base.parent/'tests/fixtures/config_legacy.json').read_text())
        r=compute_plan(json.loads((base/'fixtures/test_fixture_snapshot.json').read_text()),config)
        expected_enabled=json.loads((base/'fixtures/test_fixture_snapshot.json').read_text())['states'].get('input_boolean.hausakku_planer_freigabe',{}).get('state')=='on'
        self.assertEqual(r['mode'],'live' if expected_enabled else 'shadow')
        self.assertTrue(r['control_installed']);self.assertEqual(r['control_enabled'],expected_enabled)
        tv=float(r['plan']['params'].get('terminal_value_eur_kwh',0.0))
        # With a configured carry-over value the within-horizon cash cost may be
        # negative (energy is bought now, consumed after the known price window).
        # The binding invariant is then the objective including carried-over energy.
        self.assertTrue(r['plan']['comparison']['total_savings_eur']>=-1e-9 or tv>0 or r['plan']['params'].get('terminal_value_curve'))
        self.assertLessEqual(r['plan']['objective_eur'],r['plan']['comparison']['optimized_no_charge']['objective_eur']+1e-6)
        self.assertFalse(any(x['charger_ac_kwh']>0 and x['served_ac_kwh']>0 for x in r['plan']['intervals']))
        self.assertEqual(r['plan']['params']['capacity_kwh'],config['capacity_kwh'])
        self.assertAlmostEqual(r['plan']['params']['grid_charge_limit_kwh'],config['capacity_kwh']*config['grid_charge_max_soc_fraction'])
        self.assertEqual(r['plan']['params']['decision_block_minutes'],30)
        self.assertIn('reason_code',r['operating_policy'])
        self.assertLessEqual(r['target_soc'],90)
    def test_installed_controller_is_reported_without_claiming_activation(self):
        import json
        from pathlib import Path
        from planner import report
        base=Path(__file__).parent
        snapshot=json.loads((base/'fixtures/test_fixture_snapshot.json').read_text())
        config=json.loads((base.parent/'tests/fixtures/config_legacy.json').read_text());config['controller_installed']=True
        snapshot['states']['input_boolean.hausakku_planer_freigabe']={'state':'off'}
        result=compute_plan(snapshot,config)
        self.assertTrue(result['control_installed']);self.assertFalse(result['control_enabled'])
        self.assertIn('Steuerung installiert',report(result))
    def test_forecast_baseline_is_retained_for_future_error_comparison(self):
        import json
        from pathlib import Path
        base=Path(__file__).parent
        snapshot=json.loads((base/'fixtures/test_fixture_snapshot.json').read_text());config=json.loads((base.parent/'tests/fixtures/config_legacy.json').read_text())
        result=compute_plan(snapshot,config,learning_artifact=None)
        self.assertIn('forecast_baseline',result)
        self.assertEqual(result['forecast_baseline']['intervals'][0]['load_kwh'],result['plan']['intervals'][0]['load_kwh'])
        self.assertEqual(result['forecast_model']['load'],'median28')
    def test_normal_operation_reports_why_not_hypothetical_savings(self):
        import json
        from pathlib import Path
        from planner import report
        base=Path(__file__).parent
        if not (base/'fixtures/test_fixture_snapshot.json').exists():self.skipTest('Local snapshot absent')
        config=json.loads((base.parent/'tests/fixtures/config_legacy.json').read_text());config['minimum_savings_eur']=100
        # Reporting test only: the shaped tail rightly keeps a full battery for an
        # expensive Monday, so pin the legacy flat tail where serving is sufficient.
        config.update(tail_price_model='flat_median',forecast_tail_days=7,tail_price_floor_eur_kwh=None,tail_pv_weather_weight=0.)
        snapshot=json.loads((base/'fixtures/test_fixture_snapshot.json').read_text())
        # The saved integration snapshot spans the autumn fold. This policy
        # reporting test is independent of the separately tested DST rejection;
        # begin after the repeated wall-clock hour.
        from datetime import datetime
        from zoneinfo import ZoneInfo
        fold_end=datetime(2026,10,25,3,0,tzinfo=ZoneInfo('Europe/Berlin'))
        snapshot['prices']=[r for r in snapshot['prices'] if datetime.fromisoformat(r['start_time']).timestamp()>=fold_end.timestamp()]
        snapshot['collected_at']=fold_end.isoformat();snapshot['planning_start']=fold_end.isoformat()
        # A high GRID-charge threshold no longer discards a useful holding plan.
        # Use genuinely sufficient initial energy to exercise normal-operation reporting.
        snapshot['states']['sensor.hausbatterie_kwh']['state']='15'
        snapshot['states']['sensor.ant_bms_16_soc']['state']='100'
        r=compute_plan(snapshot,config)
        self.assertTrue(r['operating_policy']['normal_operation'])
        self.assertEqual(set(r['plan']['modes']),{'serve'})
        self.assertIn('Normalbetrieb',report(r))
        self.assertNotIn('PV-Ladung bei WR-aus sind vor echter Steuerung noch zu bestätigen',report(r))
class LlmFactsTests(unittest.TestCase):
    def test_facts_state_publication_decision_and_plan_change(self):
        import json
        from pathlib import Path
        from planner import compute_plan,llm_facts,plan_summary
        base=Path(__file__).parent
        s=json.loads((base/'fixtures/test_fixture_snapshot.json').read_text());c=json.loads((base.parent/'tests/fixtures/config_legacy.json').read_text())
        plan=compute_plan(s,c)
        text=llm_facts(plan)
        self.assertIn('NEIN (nur berechnet)',text);self.assertIn('Simuliert, nicht gemessen',text)
        self.assertTrue('Gewinnschwelle' in text or 'Netzladen: nein.' in text)
        self.assertNotIn('Vorheriger',text)
        other={**plan_summary(plan),'serve':['01.01. 00:00–01:00']}
        self.assertIn('Fahrplan GEÄNDERT',llm_facts({**plan,'publication':{'verified':True}},other))
        self.assertIn('Fahrplan unverändert',llm_facts(plan,plan_summary(plan)))
        self.assertIn('Veröffentlicht und zurückgelesen: ja',llm_facts({**plan,'publication':{'verified':True}}))

class ReplanTests(unittest.TestCase):
    def plan(self):
        import json
        from pathlib import Path
        from planner import compute_plan
        base=Path(__file__).parent
        s=json.loads((base/'fixtures/test_fixture_snapshot.json').read_text());c=json.loads((base.parent/'tests/fixtures/config_legacy.json').read_text())
        return compute_plan(s,c)
    def test_change_detection_ignores_moving_start_but_sees_mode_expiry_and_target(self):
        from datetime import datetime
        from planner import schedule_changed,published_modes,plan_summary,significant_change
        plan=self.plan();now=datetime.fromisoformat(plan['plan']['intervals'][0]['end'])
        previous={**plan_summary(plan),'modes':published_modes(plan),'valid_until':plan['valid_until']}
        self.assertFalse(schedule_changed(plan,previous,now))
        moved={**previous,'modes':[[previous['modes'][0][0].replace(':11',':10'),previous['modes'][0][1]]]+previous['modes'][1:]}
        self.assertFalse(schedule_changed(plan,moved,now))
        flipped=[list(m) for m in previous['modes']];flipped[-1][1]='serve' if flipped[-1][1]!='serve' else 'hold'
        self.assertTrue(schedule_changed(plan,{**previous,'modes':flipped},now))
        self.assertTrue(schedule_changed(plan,{**previous,'valid_until':'2000-01-01T00:00:00+01:00'},now))
        self.assertTrue(schedule_changed(plan,{**previous,'target_soc':-1,'charge_kwh':2.},now))
        self.assertTrue(schedule_changed(plan,None,now))
        self.assertFalse(significant_change(plan,previous))
        self.assertTrue(significant_change(plan,{**previous,'charge_kwh':previous['charge_kwh']+2}))
    def test_replan_failure_before_publication_keeps_plan_and_stays_quiet_twice(self):
        import json,tempfile,sys
        from io import StringIO
        from contextlib import redirect_stdout,redirect_stderr
        from pathlib import Path
        from unittest.mock import patch,AsyncMock
        import planner
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'state').mkdir()
            async def broken(args):
                planner.STAGE[0]='Datenabruf aus HA';raise RuntimeError('SECRET_URL')
            closed=AsyncMock(return_value=True)
            outputs=[]
            with patch.object(planner,'BASE',root),patch.object(planner,'run',broken),patch.object(planner,'fail_closed',closed),patch.object(sys,'argv',['planner.py','--replan']):
                for _ in range(3):
                    out=StringIO()
                    with redirect_stdout(out),redirect_stderr(StringIO()):self.assertEqual(planner.main(),0)
                    outputs.append(out.getvalue())
            closed.assert_not_called()
            self.assertEqual(outputs[:2],['',''])
            self.assertIn('seit 3 Läufen',outputs[2]);self.assertNotIn('SECRET_URL',''.join(outputs))
    def test_publication_failure_still_fails_closed(self):
        import tempfile,sys
        from io import StringIO
        from contextlib import redirect_stdout,redirect_stderr
        from pathlib import Path
        from unittest.mock import patch,AsyncMock
        import planner
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'state').mkdir()
            async def broken(args):
                planner.STAGE[0]='Veröffentlichung in HA';raise RuntimeError('x')
            closed=AsyncMock(return_value=True);err=StringIO()
            with patch.object(planner,'BASE',root),patch.object(planner,'run',broken),patch.object(planner,'fail_closed',closed),patch.object(sys,'argv',['planner.py','--replan']):
                with redirect_stdout(StringIO()),redirect_stderr(err):self.assertEqual(planner.main(),1)
            closed.assert_called_once();self.assertIn('UNGÜLTIG',err.getvalue())

class PublicationHysteresisTests(unittest.TestCase):
    def setup(self):
        from datetime import datetime,timedelta
        from dataclasses import asdict
        from zoneinfo import ZoneInfo
        from optimizer import Interval,Params,optimize
        tz=ZoneInfo('Europe/Berlin');self.start=datetime(2026,11,2,18,tzinfo=tz)
        rows=[Interval(self.start+timedelta(minutes=15*i),self.start+timedelta(minutes=15*i+15),.30,.1,0.) for i in range(8)]
        result=optimize(rows,Params(10,1,5,'dc',max_discharge_kw=2,energy_step_kwh=.05))
        self.plan={'plan':result,'valid_until':rows[-1].end.isoformat(),'target_soc':0}
        return [f['start'] for f in result['intervals']],result['modes']
    def previous(self,starts,modes,**extra):
        return {'modes':[[s,m] for s,m in zip(starts,modes)],'valid_until':self.plan['valid_until'],'target_soc':0,
                'charge_kwh':0.,'charge':[],'serve':[],**extra}
    def test_small_gain_keeps_old_plan_large_gain_publishes(self):
        from planner import publication_decision
        starts,modes=self.setup();self.assertEqual(set(modes),{'serve'})
        same=publication_decision(self.plan,self.previous(starts,modes),self.start)
        self.assertFalse(same['publish'])
        small=publication_decision(self.plan,self.previous(starts,['hold']+modes[1:]),self.start)
        self.assertFalse(small['publish']);self.assertAlmostEqual(small['gain_eur'],.03)
        large=publication_decision(self.plan,self.previous(starts,['hold']*8),self.start)
        self.assertTrue(large['publish']);self.assertAlmostEqual(large['gain_eur'],.24)
        self.assertFalse(publication_decision(self.plan,self.previous(starts,['hold']*8),self.start,min_gain=.5)['publish'])
    def test_target_soc_without_any_charge_plan_is_not_a_change(self):
        from planner import publication_decision,schedule_changed
        starts,modes=self.setup()
        prev=self.previous(starts,modes,target_soc=90,charge_kwh=0.001)
        self.assertFalse(schedule_changed(self.plan,prev,self.start))
        self.assertFalse(publication_decision(self.plan,prev,self.start)['publish'])
    def test_safety_changes_always_publish(self):
        from planner import publication_decision
        starts,modes=self.setup();alt=['hold']+modes[1:]
        for prev,word in ((self.previous(starts,alt,valid_until='2000-01-01T00:00:00+01:00'),'Gültigkeit'),
                          (self.previous(starts,alt,target_soc=90,charge_kwh=2.),'Ziel-SOC'),
                          (self.previous(starts[1:],alt[1:]),'deckt'),
                          (self.previous(starts,['charge']+modes[1:]),'nachladen'),
                          (None,'kein vergleichbarer')):
            d=publication_decision(self.plan,prev,self.start)
            self.assertTrue(d['publish'],word);self.assertIn(word,d['reason'])

class IdleChargeTests(unittest.TestCase):
    def test_charge_windows_end_when_charger_stops(self):
        from datetime import datetime,timedelta
        from zoneinfo import ZoneInfo
        from optimizer import Interval,Params,optimize,_replay
        from planner import idle_charge_as_hold
        tz=ZoneInfo('Europe/Berlin');start=datetime(2026,10,26,tzinfo=tz)
        rows=[Interval(start+timedelta(minutes=15*i),start+timedelta(minutes=15*i+15),.17,.05,0.) for i in range(16)]
        p=Params(10,1,8,'dc',max_charge_kw=2,grid_charge_limit_kwh=9,energy_step_kwh=.05)
        plan=_replay(rows,['charge']*16,p)
        fixed=idle_charge_as_hold(plan,rows,p)
        charging=[f['charger_ac_kwh']>1e-9 for f in plan['intervals']]
        self.assertTrue(any(charging) and not all(charging))
        self.assertEqual(fixed['modes'],['charge' if c else 'hold' for c in charging])
        self.assertAlmostEqual(fixed['cost_eur'],plan['cost_eur']);self.assertAlmostEqual(fixed['terminal_kwh'],plan['terminal_kwh'])
        self.assertIs(idle_charge_as_hold(fixed,rows,p),fixed)
    def test_tiny_charger_sliver_is_not_a_charge_plan(self):
        from datetime import datetime,timedelta
        from zoneinfo import ZoneInfo
        from optimizer import Interval,Params,_replay
        from planner import idle_charge_as_hold
        tz=ZoneInfo('Europe/Berlin');start=datetime(2026,10,26,tzinfo=tz)
        rows=[Interval(start,start+timedelta(minutes=1),.17,.0,0.)]+[Interval(start+timedelta(minutes=1+15*i),start+timedelta(minutes=16+15*i),.17,.0,0.) for i in range(3)]
        p=Params(10,1,8.995,'dc',max_charge_kw=2,grid_charge_limit_kwh=9,energy_step_kwh=.05)
        plan=_replay(rows,['charge']*4,p)
        self.assertTrue(0<plan['intervals'][0]['charger_ac_kwh']<.02)
        fixed=idle_charge_as_hold(plan,rows,p)
        self.assertEqual(fixed['modes'],['hold']*4)
        self.assertTrue(all(f['charger_ac_kwh']==0 for f in fixed['intervals']))

class FlexTipTests(unittest.TestCase):
    def test_tips_find_cheap_blocks_floor_hours_and_serve_warning(self):
        from datetime import datetime,timedelta
        from zoneinfo import ZoneInfo
        from planner import flex_tips
        tz=ZoneInfo('Europe/Berlin');start=datetime(2026,10,26,0,tzinfo=tz)
        prices=[.30]*6+[.18]*4+[.25]*4+[.40]*4+[.30]*6
        iv=[]
        for h,p in enumerate(prices):
            for q in range(4):
                a=start+timedelta(hours=h,minutes=15*q)
                iv.append({'start':a.isoformat(),'end':(a+timedelta(minutes=15)).isoformat(),'price_eur_kwh':p,
                           'mode':'serve' if 14<=h<18 else 'hold','spill_dc_kwh':0.})
        tips=flex_tips({'plan':{'intervals':iv}})
        self.assertIn('Mo 06:00–09:00',tips[0])
        self.assertTrue(any('Tiefstpreis 18.0 ct' in t and 'Mo 06:00–10:00' in t for t in tips))
        self.assertTrue(any('Versorgen' in t and '14:00–18:00' in t for t in tips))
        self.assertFalse(any('PV-Überschuss' in t for t in tips))

if __name__=='__main__':unittest.main()

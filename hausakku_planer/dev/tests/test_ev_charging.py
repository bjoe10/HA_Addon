import unittest
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import ev_charging
from ev_charging import charging_power_kw,kwh_per_percent,plan_window,week_payload,evaluate
TZ=ZoneInfo('Europe/Berlin')

def slots(prices,modes=None,start=datetime(2026,10,26,0,tzinfo=TZ)):
    out=[]
    for i,p in enumerate(prices):
        a=start+timedelta(minutes=15*i)
        out.append({'start':a.isoformat(),'end':(a+timedelta(minutes=15)).isoformat(),'price_eur_kwh':p,'duration_hours':.25,
                    'mode':(modes or {}).get(i,'hold')})
    return out

class EvTests(unittest.TestCase):
    def test_measurements_from_sessions(self):
        base=1_000_000_000.
        cee={base+3600*i:v for i,v in enumerate((0.,0.,3.5,3.4,3.6,0.0,0.0,3.5,3.5,3.6,0.1))}
        soc={base+3600*i:v for i,v in enumerate((40,40,40,50,60,70,72,72,72,80,90,92))}
        self.assertAlmostEqual(charging_power_kw(cee),3.5)
        self.assertIsNone(charging_power_kw({1:3.5,2:3.5}))
        per,n=kwh_per_percent(cee,soc,minimum_sessions=2)
        self.assertEqual(n,2);self.assertAlmostEqual(per,.5*(10.5/32+10.6/20))
        self.assertEqual(kwh_per_percent(cee,soc),(None,2))
    def test_cheapest_block_avoids_serve_and_ties_take_earliest(self):
        prices=[.30]*4+[.20]*8+[.18]*8+[.30]*4
        # serve covers the cheapest part, so the block must move to the 20 ct hours
        r=plan_window(slots(prices,{i:'serve' for i in range(12,20)}),need_kwh=3.0,power_kw=3.5,margin=.1)
        self.assertEqual(r['status'],'ok');self.assertAlmostEqual(r['mean_price_eur_kwh'],.20)
        self.assertEqual(r['start'],slots(prices)[4]['start'])
        self.assertEqual(len(r['blocks']),4);self.assertAlmostEqual(r['cost_eur'],3.0*.20)
        flat=plan_window(slots([.2]*40),3.0,3.5)
        self.assertEqual(flat['start'],slots([.2]*40)[0]['start'])
        self.assertEqual(flat['flex_end'],slots([.2]*40)[-1]['end'])
    def test_status_cases(self):
        s=slots([.2]*8)
        self.assertEqual(plan_window(s,0,3.5)['status'],'full')
        self.assertEqual(plan_window(s,5,None)['status'],'no_power')
        self.assertEqual(plan_window(s,50,3.5)['status'],'no_block')
        self.assertEqual(plan_window(slots([.2]*8,{i:'serve' for i in range(0,8,2)}),3,3.5)['status'],'no_block')
    def test_week_payload_merges_and_splits_at_midnight(self):
        s=slots([.1]*8,start=datetime(2026,10,26,22,0,tzinfo=TZ))
        w=week_payload([(f['start'],f['end']) for f in s])
        self.assertEqual(w['monday'],[{'from':'22:00','to':'24:00'}]);self.assertEqual(w['tuesday'],[])
        s=slots([.1]*8,start=datetime(2026,10,26,23,0,tzinfo=TZ))
        w=week_payload([(f['start'],f['end']) for f in s])
        self.assertEqual(w['monday'],[{'from':'23:00','to':'24:00'}]);self.assertEqual(w['tuesday'],[{'from':'00:00','to':'01:00'}])
        self.assertEqual(set(w),set(ev_charging.DAYS))
    def test_evaluate_uses_measured_values_falls_back_and_reports_unknowns(self):
        s=slots([.2]*40)
        r=evaluate(s,{'soc':77,'target_soc':90,'kwh_per_percent':.74,'power_kw':3.5,'plugged':True},{})
        self.assertAlmostEqual(r['need_kwh'],13*.74);self.assertEqual(r['per_percent_source'],'gemessen')
        self.assertEqual(sum(len(v) for v in r['week'].values()),1)
        r=evaluate(s,{'soc':77,'target_soc':90},{'ev_kwh_per_soc_percent':.8,'ev_power_kw':3.})
        self.assertEqual((r['per_percent_source'],r['power_source']),('Config-Wert','Config-Wert'))
        self.assertEqual(evaluate(s,{'soc':90,'target_soc':90},{})['status'],'full')
        self.assertEqual(evaluate(s,{'soc':90,'target_soc':90},{})['week'],week_payload([]))
        self.assertEqual(evaluate(s,None,{})['status'],'unknown_soc')
        self.assertEqual(evaluate(s,{'soc':None,'target_soc':90,'warning':'x'},{})['status'],'unknown_soc')

class EvWriteScopeTests(unittest.TestCase):
    def test_only_the_users_ev_helper_is_writable_in_addition(self):
        from ha_client import check_call
        check_call('ha_config_set_helper',{'helper_id':'car_charge_window','action':'update'})
        check_call('ha_config_set_helper',{'helper_id':'hap_netzladen','action':'update'})
        for bad in ({'helper_id':'car_charge_window','action':'delete'},{'helper_id':'auto_netz_laden','action':'update'},{'helper_id':'preis_gut','action':'update'}):
            with self.assertRaises(ValueError):check_call('ha_config_set_helper',bad)
        with self.assertRaises(ValueError):check_call('ha_call_service',{'domain':'switch','service':'turn_off','entity_id':'switch.cee_outlet'})
    def test_publish_validates_before_any_connection(self):
        import asyncio
        from publisher import publish_ev_window,DAYS
        bad={d:[] for d in DAYS};bad['monday']=[{'from':'10:00','to':'09:00'}]
        with self.assertRaises(ValueError):asyncio.run(publish_ev_window(bad))
        with self.assertRaises(ValueError):asyncio.run(publish_ev_window({'monday':[]}))

if __name__=='__main__':unittest.main()

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
import shadow
from optimizer import Params

TZ=ZoneInfo('Europe/Berlin')
P=Params(capacity_kwh=16.,reserve_kwh=1.6,initial_kwh=0.,pv_coupling='dc',max_charge_kw=2.,max_discharge_kw=1.,
         discharge_efficiency=1.,charge_efficiency=1.,grid_charge_limit_kwh=14.4)
T0=int(datetime(2026,11,9,0,0,tzinfo=TZ).timestamp())      # a Monday

def row(i,active=True,price=.3,battery=None,grid=0.,wr=0.,charger=0.,export=0.,pv=0.,ev=0.):
    return {'start':T0+i*shadow.STEP,'active':active,'price':price,'battery_kwh':battery,
            'grid':grid,'wr':wr,'charger':charger,'export':export,'pv':pv,'ev':ev}

class AdvanceTests(unittest.TestCase):
    def state(self):return shadow.new_state(T0)

    def test_nothing_is_counted_while_the_control_is_off(self):
        s=shadow.advance(self.state(),[row(i,active=False,battery=8.,grid=.1) for i in range(4)],P,.2)
        self.assertEqual(s['cash_eur'],0.);self.assertEqual(s['active_hours'],0.);self.assertEqual(s['inactive_hours'],1.)
        self.assertIsNone(s['shadow_kwh']);self.assertEqual(shadow.summary(s,.2,8.)['total_eur'],0.)
        self.assertFalse(shadow.summary(s,.2)['control_on'])

    def test_holding_costs_now_and_pays_back_later_with_no_week_boundary_loss(self):
        # 2 quarters held at 0.30 (house from the grid), then 2 quarters served at 0.60 from the kept energy.
        rows=[row(0,price=.3,battery=8.,grid=.25),row(1,price=.3,battery=8.,grid=.25),
              row(2,price=.6,battery=8.,wr=.25),row(3,price=.6,battery=7.75,wr=.25)]
        s=shadow.advance(self.state(),rows,P,.2)
        # The shadow served everything from its battery: its cost is 0, the actual cost 2 x .25 x .30.
        self.assertAlmostEqual(s['actual_eur'],.15);self.assertAlmostEqual(s['shadow_eur'],0.)
        self.assertAlmostEqual(s['cash_eur'],-.15)
        # Both batteries are worth the same afterwards only if the energy is valued: the actual one holds 0.5 kWh more.
        self.assertAlmostEqual(s['shadow_kwh'],7.)
        sm=shadow.summary(s,.6,7.5)                       # valued at the price the kept energy displaced
        self.assertAlmostEqual(sm['total_eur'],0.15)       # -0.15 cash + 0.5 kWh x 0.60

    def test_turning_off_books_the_battery_difference_and_restarts_from_the_measured_battery(self):
        rows=[row(0,battery=8.,grid=.25),row(1,active=False,battery=8.,grid=.25),row(2,battery=9.,grid=.25)]
        s=shadow.advance(self.state(),rows,P,.2)
        # Quarter 0: shadow serves .25 -> 7.75 while actual stays 8: +0.25 kWh x 0.2 booked when switched off.
        self.assertAlmostEqual(s['booked_inventory_eur'],.05)
        self.assertAlmostEqual(s['shadow_kwh'],8.75)       # restarted at the measured 9 kWh, then served .25
        self.assertEqual(s['inactive_hours'],.25);self.assertEqual(s['active_hours'],.5)

    def test_missing_data_is_a_gap_not_zero(self):
        s=shadow.advance(self.state(),[row(0,battery=8.,grid=None),row(1,battery=8.,price=None,grid=.1)],P,.2)
        self.assertEqual(s['gap_hours'],.5);self.assertEqual(s['active_hours'],0.);self.assertEqual(s['cash_eur'],0.)

    def test_rows_must_follow_without_gaps(self):
        with self.assertRaises(ValueError):shadow.advance(self.state(),[row(1)],P,.2)

    def test_week_values_add_up_to_the_total(self):
        week=7*24*4
        rows=[row(i,battery=8.,grid=.25,price=.3) for i in range(week+8)]
        s=shadow.advance(self.state(),rows[:week+4],P,0.)
        s=shadow.advance(s,rows[week+4:],P,0.)
        sm=shadow.summary(s,0.)
        self.assertEqual([w['start'] for w in sm['per_week']],['2026-11-09','2026-11-16'])
        self.assertAlmostEqual(sum(w['eur'] for w in sm['per_week']),sm['total_eur'],places=2)
        self.assertEqual(sm['week_eur'],sm['per_week'][-1]['eur']);self.assertEqual(sm['last_week_eur'],sm['per_week'][0]['eur'])

    def test_grid_share_while_serving_is_learned_and_charged_to_the_shadow(self):
        rows=[row(i,battery=8.,wr=.2375,grid=.0125) for i in range(10)]  # 5 % of the load still from the grid
        s=shadow.advance(self.state(),rows,P,0.)
        self.assertAlmostEqual(shadow.residual_share(s),.05)
        # Once learned, a shadow quarter serving the same load also takes 5 % from the grid: no artificial gain.
        before=s['cash_eur'];s=shadow.advance(s,[row(10,battery=8.,wr=.2375,grid=.0125)],P,0.)
        self.assertAlmostEqual(s['cash_eur'],before)

    def test_model_replays_the_actual_operation(self):
        rows=[row(0,battery=8.,grid=.25),row(1,battery=8.,charger=.5,grid=.75),row(2,battery=8.5,wr=.25)]
        s=shadow.advance(self.state(),rows,P,0.)
        self.assertAlmostEqual(shadow.summary(s,0.)['model_deviation_eur'],0.,places=6)

class InverterTests(unittest.TestCase):
    def hours(self,a=1/.9,b=.03,n=40):
        import random;rnd=random.Random(1)
        return [{'wr':(w:=rnd.uniform(.1,.8)),'out':a*w+b,'pv':0.,'charger':0.,'inn':0.} for _ in range(n)]

    def test_efficiency_and_standby_are_recovered(self):
        fit=shadow.fit_inverter(self.hours())
        self.assertAlmostEqual(fit['discharge_efficiency'],.9,places=3);self.assertAlmostEqual(fit['standby_kw'],.03,places=3)
        self.assertEqual(fit['hours'],40)
        # A DC meter on real voltage (2 % above nominal): converted to the battery-kWh scale.
        fit=shadow.fit_inverter([{**h,'out':h['out']*1.02} for h in self.hours()],scale=1.02)
        self.assertAlmostEqual(fit['standby_kw'],.03,places=3);self.assertAlmostEqual(fit['discharge_efficiency'],.9,places=3)

    def test_unusable_data_gives_no_fit(self):
        self.assertIsNone(shadow.fit_inverter(self.hours(n=10)))                       # too few hours
        same=[{'wr':.3,'out':.36,'pv':0.,'charger':0.,'inn':0.}]*30
        self.assertIsNone(shadow.fit_inverter(same))                                    # one load level only
        self.assertIsNone(shadow.fit_inverter(self.hours(b=.5)))                        # 500 W: not the inverter
        pv=[{**h,'pv':.5} for h in self.hours()]
        self.assertIsNone(shadow.fit_inverter(pv))                                      # PV hours are not clean

    def test_shadow_pays_standby_while_the_actual_inverter_is_off(self):
        rows=[row(i,battery=8.,grid=.25) for i in range(4)]                             # actual: held, inverter off
        without=shadow.advance(shadow.new_state(T0),rows,P,0.)
        withsb=shadow.advance(shadow.new_state(T0),rows,P,0.,standby_kw=.04)
        self.assertAlmostEqual(without['shadow_kwh']-withsb['shadow_kwh'],.04)            # 40 W for one hour
        self.assertAlmostEqual(withsb['standby_kwh'],.04)
        self.assertAlmostEqual(withsb['model_kwh'],8.)                                    # actual inverter off: no standby
        # Worth that energy at the battery value: the control saved it.
        self.assertAlmostEqual(shadow.summary(withsb,.5,8.)['total_eur']-shadow.summary(without,.5,8.)['total_eur'],.02)

    def test_no_standby_at_the_reserve(self):
        s=shadow.advance(shadow.new_state(T0),[row(0,battery=P.reserve_kwh,grid=.25)],P,0.,standby_kw=.04)
        self.assertAlmostEqual(s['shadow_kwh'],P.reserve_kwh)

    def test_fitted_efficiency_replaces_the_ratio(self):
        cfg={'capacity_kwh':16,'reserve_fraction':.1,'max_charge_kw':2,'max_discharge_kw':1,'discharge_efficiency':.9,
             'roundtrip_efficiency':.8,'grid_charge_max_soc_fraction':.9}
        p=shadow.model_params(cfg,{'discharge_hours':56,'discharge_efficiency':.86},{'discharge_efficiency':.93,'standby_kw':.03})
        self.assertAlmostEqual(p.discharge_efficiency,.93)

class InputTests(unittest.TestCase):
    def test_quarters_need_all_three_buckets(self):
        b={float(T0+300*i):.01 for i in range(6)};del b[float(T0+300*4)]
        q=shadow.quarters(b,T0,T0+1800)
        self.assertAlmostEqual(q[T0],.03);self.assertIsNone(q[T0+900])

    def test_only_whole_quarters_with_the_switch_on_count(self):
        states=[(T0-100,'off'),(T0+1000,'on'),(T0+2800,'off')]
        self.assertEqual(shadow.active_quarters(states,T0,T0+3600),{T0+1800})
        self.assertEqual(shadow.active_quarters([],T0,T0+900),set())

    def test_measured_discharge_efficiency_is_used_once_there_is_enough_of_it(self):
        cfg={'capacity_kwh':16,'reserve_fraction':.1,'max_charge_kw':2,'max_discharge_kw':1,'discharge_efficiency':.9,
             'roundtrip_efficiency':.8,'grid_charge_max_soc_fraction':.9}
        self.assertAlmostEqual(shadow.model_params(cfg,{}).discharge_efficiency,.9)
        self.assertAlmostEqual(shadow.model_params(cfg,{'discharge_hours':56,'discharge_efficiency':.86}).discharge_efficiency,.86)
        self.assertAlmostEqual(shadow.model_params(cfg,{'discharge_hours':5,'discharge_efficiency':.86}).discharge_efficiency,.9)

    def test_battery_value_is_the_floor_or_the_lowest_recent_price(self):
        self.assertAlmostEqual(shadow.battery_value({'tail_price_floor_eur_kwh':.2},{},P,T0),.2)
        self.assertAlmostEqual(shadow.battery_value({},{T0-3600:.42,T0-60:.5,T0-9*86400:.1},P,T0),.42)

if __name__=='__main__':unittest.main()

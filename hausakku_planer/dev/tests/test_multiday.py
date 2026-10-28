import copy,json,tempfile,unittest
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from optimizer import Params,Interval,optimize,_replay
from multiday import build_tail,scenario_rows,continuation_curve,archive_prices,read_prices,archive_issue,score_issues
TZ=ZoneInfo('Europe/Berlin')

class MultidayTests(unittest.TestCase):
    def inputs(self):
        s=json.loads((Path(__file__).parent/'fixtures/test_fixture_snapshot.json').read_text())
        from planner_data import prepare
        c=json.loads((Path(__file__).parent.parent/'tests/fixtures/config_legacy.json').read_text())
        return s,c,prepare(s,c)
    def test_sparse_tail_is_baseline_and_future_actuals_do_not_leak(self):
        s,c,d=self.inputs();end=d['intervals'][-1]['end']
        a=build_tail(s,d,end,{'hours':[]},[])
        future={'hours':[{'start':end.timestamp()+3600,'load_kwh':999,'pv_kwh':999}]}
        b=build_tail(s,d,end,future,[])
        self.assertEqual(a,b);self.assertEqual(a['price_model'],'observed_known_price_baseline')
        self.assertFalse(a['promoted']);self.assertTrue(all(r['start']>=end.isoformat() for r in a['rows']))
    def test_tail_dst_contiguous_elapsed_hours(self):
        s,c,d=self.inputs();end=datetime(2026,10,24,tzinfo=TZ)
        tail=build_tail(s,d,end,{'hours':[]},[])
        starts=[datetime.fromisoformat(r['start']).timestamp() for r in tail['rows']]
        self.assertTrue(all(b-a==3600 for a,b in zip(starts,starts[1:])))
        self.assertEqual(len([t for t in starts if datetime.fromtimestamp(t,TZ).date().isoformat()=='2026-10-25']),25)
    def test_observation_vintage_future_excluded_and_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'prices.sqlite';s,c,d=self.inputs()
            archive_prices(path,s);first=read_prices(path,s['collected_at'])
            self.assertTrue(first)
            earlier=(datetime.fromisoformat(s['collected_at'])-timedelta(days=1)).isoformat()
            self.assertEqual(read_prices(path,earlier),[])
            archive_prices(path,s);self.assertEqual(first,read_prices(path,s['collected_at']))
    def test_recent_season_profile_rejects_future_and_old_winter(self):
        s,c,d=self.inputs();issue=datetime.fromisoformat(s['collected_at']);end=d['intervals'][-1]['end']
        def hours(age,value):
            day=(issue-timedelta(days=age)).replace(hour=0,minute=0,second=0,microsecond=0)
            return [{'start':(day+timedelta(hours=h)).timestamp(),'load_kwh':value,'pv_kwh':value} for h in range(24)]
        recent={'hours':sum([hours(i,1.) for i in range(1,15)],[])}
        polluted={'hours':recent['hours']+hours(150,100)+hours(-10,999)}
        self.assertEqual(build_tail(s,d,end,recent,[]),build_tail(s,d,end,polluted,[]))
    def test_price_weekday_pattern_is_not_hardcoded(self):
        s,c,d=self.inputs();issue=datetime.fromisoformat(s['collected_at']);hist=[]
        for age in range(1,57):
            t=(issue-timedelta(days=age)).replace(hour=12,minute=0,second=0,microsecond=0)
            hist.append({'start':t.timestamp(),'price':.1 if t.weekday()==0 else .4,'issued_at':(t-timedelta(days=1)).timestamp()})
        tail=build_tail(s,d,d['intervals'][-1]['end'],{'hours':[]},hist)
        self.assertFalse(tail['promoted'])
        self.assertIn('weekday',tail['candidate_model'])
        monday=[v for r,v in zip(tail['rows'],tail['candidate_prices']) if datetime.fromisoformat(r['start']).weekday()==0 and datetime.fromisoformat(r['start']).hour==12]
        other=[v for r,v in zip(tail['rows'],tail['candidate_prices']) if datetime.fromisoformat(r['start']).weekday()==1 and datetime.fromisoformat(r['start']).hour==12]
        self.assertLess(monday[0],other[0])

    def test_dwd_hourly_cloud_is_a_low_pv_scenario_not_the_central_profile(self):
        s,c,d=self.inputs();end=d['intervals'][-1]['end']
        target=end.date().isoformat()
        issue=datetime.fromisoformat(s['collected_at'])
        hours=[]
        for age in range(1,8):
            day=(issue-timedelta(days=age)).replace(hour=0,minute=0,second=0,microsecond=0)
            for hour in range(24):
                t=day+timedelta(hours=hour)
                hours.append({'start':t.timestamp(),'load_kwh':.2,'pv_kwh':.1 if 8<=hour<=16 else 0.})
        dataset={'hours':hours}
        clear=copy.deepcopy(s);clear['weather_forecasts']=[]
        cloudy=copy.deepcopy(s);cloudy['weather_forecasts']=[
            {'datetime':(end+timedelta(hours=i)).isoformat(),'cloud_coverage':87.0,'condition':'cloudy'}
            for i in range(24)]
        baseline=build_tail(clear,d,end,dataset,[],days=2)
        weather=build_tail(cloudy,d,end,dataset,[],days=2)
        rows0=[r for r in baseline['rows'] if r['start'].startswith(target)]
        rows1=[r for r in weather['rows'] if r['start'].startswith(target)]
        pv0=sum(r['pv_kwh'] for r in rows0)
        self.assertGreater(pv0,0)
        self.assertAlmostEqual(sum(r['pv_kwh'] for r in rows1),pv0,places=6)
        self.assertAlmostEqual(sum(r['weather_pv_kwh'] or 0. for r in rows1),pv0*.25,places=6)
        low=scenario_rows(weather)[2]
        self.assertAlmostEqual(sum(r.pv_kwh for r in low if r.start.date().isoformat()==target),pv0*.25,places=6)
        self.assertEqual(weather['pv_model'],'historical_28d_with_dwd_hourly_low_scenario')

    def test_future_price_vintages_cannot_change_tail_training(self):
        s,c,d=self.inputs();end=d['intervals'][-1]['end'];issue=_timestamp(s['collected_at'])
        baseline=build_tail(s,d,end,{},[])
        leaked=[{'start':issue-86400,'issued_at':issue+1,'price':99.}]
        self.assertEqual(baseline,build_tail(s,d,end,{},leaked))
    def test_curve_declines_and_solar_displaces_inventory(self):
        p=Params(4,1,1,'dc',energy_step_kwh=.25)
        start=datetime(2026,10,24,tzinfo=TZ)
        rows=[Interval(start,start+timedelta(hours=1),.5,1,0)]
        curve=continuation_curve([rows],p)
        slopes=[(b[1]-a[1])/(b[0]-a[0]) for a,b in zip(curve,curve[1:]) if a[0]>=p.reserve_kwh]
        self.assertTrue(all(a>=b-1e-9 and b>=0 for a,b in zip(slopes,slopes[1:])))
        solar=continuation_curve([[replace(rows[0],pv_kwh=5)]],p)
        self.assertLess(solar[-1][1],curve[-1][1]);self.assertAlmostEqual(curve[0][1],0)
    def test_weekend_charge_and_hold_for_later_demand_not_fixed_linear_credit(self):
        start=datetime(2026,10,24,tzinfo=TZ)
        p=Params(4,1,1,'dc',max_charge_kw=2,max_discharge_kw=2,energy_step_kwh=.1)
        tail=[Interval(start+timedelta(days=2),start+timedelta(days=2,hours=1),.5,2,0)]
        curve=continuation_curve([tail],p)
        p=replace(p,terminal_value_curve=tuple(map(tuple,curve)))
        rows=[Interval(start,start+timedelta(hours=1),.1,0,0),Interval(start+timedelta(hours=1),start+timedelta(hours=2),.4,.1,0)]
        plan=optimize(rows,p)
        self.assertEqual(plan['modes'],['charge','hold'])
        self.assertLess(plan['terminal_kwh'],4)
        self.assertAlmostEqual(plan['objective_eur'],plan['cost_eur']-plan['carryover_value_eur'])
        with self.assertRaises(ValueError):optimize(rows,replace(p,terminal_value_eur_kwh=.24))
    def test_future_cheap_recharge_reduces_present_inventory_value(self):
        start=datetime(2026,10,25,tzinfo=TZ)
        p=Params(4,1,1,'dc',max_charge_kw=3,energy_step_kwh=.1)
        tail=[Interval(start,start+timedelta(hours=1),.05,0,0),
              Interval(start+timedelta(hours=1),start+timedelta(hours=2),.5,2,0)]
        with_recharge=continuation_curve([tail],p)
        without_recharge=continuation_curve([tail],p,allow_grid_charge=False)
        self.assertLess(with_recharge[-1][1],without_recharge[-1][1]*.5)
        known=[Interval(start-timedelta(hours=1),start,.17,0,0)]
        plan=optimize(known,replace(p,terminal_value_curve=tuple(with_recharge)))
        self.assertNotIn('charge',plan['modes'])
    def test_scenario_mean_weight_moves_curve_between_worst_and_mean(self):
        start=datetime(2026,10,25,tzinfo=TZ)
        p=Params(4,1,1,'dc',max_charge_kw=3,energy_step_kwh=.25)
        cheap=[Interval(start,start+timedelta(hours=1),.1,2,0)];dear=[Interval(start,start+timedelta(hours=1),.5,2,0)]
        worst,half,mean=(continuation_curve([cheap,dear],p,mean_weight=w)[-1][1] for w in (0.,.5,1.))
        self.assertLess(worst,half);self.assertLess(half,mean)
        with self.assertRaises(ValueError):continuation_curve([cheap],p,mean_weight=1.5)
    def test_floor_end_value_credits_leftover_without_motivating_charge(self):
        start=datetime(2026,10,25,tzinfo=TZ)
        p=Params(4,1,1,'dc',max_charge_kw=3,energy_step_kwh=.25)
        idle=[Interval(start,start+timedelta(hours=1),.3,0,0)]
        self.assertAlmostEqual(continuation_curve([idle],p,end_value_eur_kwh=.1)[-1][1],.3)
        self.assertTrue(all(abs(v)<1e-9 for _,v in continuation_curve([idle],p)))
        with self.assertRaises(ValueError):continuation_curve([idle],p,end_value_eur_kwh=-1)
        from planner import tail_end_value
        self.assertAlmostEqual(tail_end_value({'tail_end_value_from_floor':True,'tail_price_floor_eur_kwh':.2,'discharge_efficiency':.8}),.16)
        self.assertEqual(tail_end_value({'tail_end_value_from_floor':False,'tail_price_floor_eur_kwh':.2,'discharge_efficiency':.8}),0.)
    def test_inventory_has_no_credit_without_future_demand(self):
        start=datetime(2026,10,25,tzinfo=TZ)
        p=Params(4,1,1,'dc',max_charge_kw=3,energy_step_kwh=.1)
        tail=[Interval(start,start+timedelta(hours=1),.1,0,0)]
        self.assertTrue(all(abs(v)<1e-9 for _,v in continuation_curve([tail],p)))
    def test_prospective_archive_and_cost_scoring_waits_for_real_outcomes(self):
        s,c,d=self.inputs();tail=build_tail(s,d,d['intervals'][-1]['end'],{'hours':[]},[])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'prices.sqlite';archive_prices(path,s)
            archive_issue(path,s,tail,{'cost_eur':1}, {'cost_eur':2})
            result=score_issues(path,{'hours':[]},s['collected_at'])
            self.assertEqual(result['scored'],0);self.assertEqual(result['pending'],1)

    def test_production_uses_curve_and_only_publishes_known_price_dates(self):
        from planner import compute_plan,report
        s,c,d=self.inputs()
        a=compute_plan(s,c)
        c['terminal_value_eur_kwh']=99
        b=compute_plan(s,c)
        self.assertEqual(a['plan']['modes'],b['plan']['modes'])
        self.assertTrue(a['plan']['params']['terminal_value_curve'])
        self.assertEqual(a['plan']['params']['terminal_value_eur_kwh'],0)
        self.assertEqual(a['valid_until'],d['intervals'][-1]['end'].isoformat())
        self.assertEqual(len(a['plan']['intervals']),len(d['intervals']))
        self.assertIn('intervals',a['forecast_baseline'])
        comp=a['plan']['comparison']
        self.assertAlmostEqual(comp['objective_savings_eur'],comp['total_savings_eur']+comp['estimated_carryover_benefit_eur'])
        self.assertIn('geschätzter',report(a))

    def test_promotion_requires_chronological_price_and_cost_holdouts(self):
        from multiday import assess_promotion
        days={(datetime(2026,9,1)+timedelta(days=i)).date().isoformat():{'price_baseline_mae':.1,'price_candidate_mae':.08,
               'decision_costs_eur':{'baseline_tail':2.,'candidate':1.9}} for i in range(35)}
        result=assess_promotion(days)
        self.assertTrue(result['promoted'])
        self.assertLess(result['validation_dates'][-1],result['test_dates'][0])
        self.assertFalse(assess_promotion(dict(list(days.items())[:27]))['promoted'])
        days['2026-10-05']['decision_costs_eur']['candidate']=9.
        self.assertFalse(assess_promotion(days)['promoted'])

    def test_historic_snapshots_are_real_vintages_not_new_prospective_issues(self):
        from multiday import seed_price_archive
        s,c,d=self.inputs()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'snapshots').mkdir()
            (root/'snapshots/a.json').write_text(json.dumps(s))
            result=seed_price_archive(root/'audit.sqlite',root/'snapshots',s['collected_at'])
            self.assertEqual(result['snapshots'],1)
            self.assertEqual(read_prices(root/'audit.sqlite',s['collected_at'])[0]['issued_at'],_timestamp(s['collected_at']))
            self.assertEqual(score_issues(root/'audit.sqlite',{},s['collected_at'])['pending'],0)

    def test_completed_prospective_scoring_replays_frozen_modes_on_real_targets(self):
        start=datetime(2026,9,1,12,tzinfo=TZ)
        params=Params(4,1,2,'dc',energy_step_kwh=.25)
        known=[Interval(start,start+timedelta(hours=1),.1,0,0)]
        selected=optimize(known,params)
        tail_start=start+timedelta(hours=1)
        tail={'rows':[{'start':tail_start.isoformat(),'end':(tail_start+timedelta(hours=1)).isoformat(),
              'price_eur_kwh':.2,'load_kwh':1.,'pv_kwh':0.}], 'baseline_price':.2,'candidate_prices':[.25]}
        snapshot={'collected_at':(start-timedelta(hours=1)).isoformat(),'prices':[
            {'start_time':(start+timedelta(minutes=15*i)).isoformat(),'price':.3} for i in range(8)]}
        data={'hours':[{'start':start.timestamp(),'load_kwh':1.,'pv_kwh':0.},
                       {'start':tail_start.timestamp(),'load_kwh':1.,'pv_kwh':0.}]}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'audit.sqlite';archive_prices(path,snapshot)
            archive_issue(path,snapshot,tail,selected,selected)
            result=score_issues(path,data,(start+timedelta(hours=2)).isoformat())
            self.assertEqual(result['scored'],1);self.assertEqual(result['pending'],0)
            outcome=next(iter(result['outcomes_by_day'].values()))
            self.assertEqual(outcome['cost_basis'],'frozen_policy_replay_observed_hourly_energy_prorated')
            self.assertAlmostEqual(outcome['price_baseline_mae'],.1)
            self.assertEqual(score_issues(path,data,snapshot['collected_at'])['scored'],0)

class ShapedPriceTests(unittest.TestCase):
    """Daily shape + level anchored on the last complete known day."""
    issue=datetime(2026,11,10,20,15,tzinfo=TZ)
    def day_prices(self,day,level,peak=0.,negative_noon=False):
        start=datetime.combine(day,datetime.min.time(),TZ).timestamp()
        rows=[]
        for i in range(96):
            t=start+i*900;hour=datetime.fromtimestamp(t,TZ).hour
            price=level+(peak if 17<=hour<=19 else 0.)-(level+.05 if negative_noon and hour==13 else 0.)
            rows.append({'start_time':datetime.fromtimestamp(t,TZ).isoformat(),'price':price})
        return rows
    def setup(self,known_level=.20,history_level=.40,peak=.12,partial=False):
        today=self.issue.date();tomorrow=today+timedelta(days=1)
        known=self.day_prices(today,known_level,peak)+self.day_prices(tomorrow,known_level,peak)
        if partial:known=known[:-4]
        hist=[]
        for age in range(1,15):
            for r in self.day_prices(today-timedelta(days=age),history_level,peak):
                t=_timestamp(r['start_time']);hist.append({'start':t,'price':r['price'],'issued_at':t-86400})
        return {'prices':known},hist
    def test_level_reverts_from_known_day_towards_long_median(self):
        from multiday import shaped_price_model,shaped_price
        snapshot,hist=self.setup()
        model=shaped_price_model(snapshot,hist,self.issue,persistence=.5)
        self.assertEqual(model['anchor_date'],(self.issue.date()+timedelta(days=1)).isoformat())
        night=lambda d:shaped_price(model,datetime.combine(self.issue.date()+timedelta(days=d),datetime.min.time(),TZ).replace(hour=3))
        # Shape is the median deviation from daily mean: night is .12*12/96 below mean.
        offset=-.12*12/96
        self.assertAlmostEqual(model['long_level'],.40+.12*12/96)
        for d,weight in ((2,.5),(3,.25),(4,.125)):
            level=model['long_level']+(model['known_level']-model['long_level'])*weight
            self.assertAlmostEqual(night(d),level+offset)
        peak=shaped_price(model,datetime.combine(self.issue.date()+timedelta(days=2),datetime.min.time(),TZ).replace(hour=18))
        self.assertAlmostEqual(peak-night(2),.12)
    def test_persistence_extremes(self):
        from multiday import shaped_price_model,shaped_price
        snapshot,hist=self.setup()
        later=datetime.combine(self.issue.date()+timedelta(days=3),datetime.min.time(),TZ).replace(hour=3)
        pure=shaped_price_model(snapshot,hist,self.issue,persistence=1.)
        self.assertAlmostEqual(shaped_price(pure,later),pure['known_level']+pure['shape'][3])
        none=shaped_price_model(snapshot,hist,self.issue,persistence=0.)
        self.assertAlmostEqual(shaped_price(none,later),none['long_level']+none['shape'][3])
        with self.assertRaises(ValueError):shaped_price_model(snapshot,hist,self.issue,persistence=1.5)
    def test_incomplete_known_day_is_not_the_anchor(self):
        from multiday import shaped_price_model
        snapshot,hist=self.setup(partial=True)
        self.assertEqual(shaped_price_model(snapshot,hist,self.issue)['anchor_date'],self.issue.date().isoformat())
    def test_future_history_vintage_does_not_shape_tail(self):
        from multiday import _eligible_prices,shaped_price_model
        snapshot,hist=self.setup()
        leaked=hist+[{'start':_timestamp(r['start_time'])-86400*20,'price':9.,'issued_at':self.issue.timestamp()+1}
                     for r in self.day_prices(self.issue.date(),9.)]
        self.assertEqual(shaped_price_model(snapshot,_eligible_prices(hist,self.issue),self.issue),
                         shaped_price_model(snapshot,_eligible_prices(leaked,self.issue),self.issue))
    def test_negative_prices_stay_valid(self):
        from multiday import shaped_price_model,shaped_price
        today=self.issue.date()
        snapshot={'prices':self.day_prices(today,.10,negative_noon=True)}
        model=shaped_price_model(snapshot,[],self.issue,persistence=1.)
        noon=datetime.combine(today+timedelta(days=1),datetime.min.time(),TZ).replace(hour=13)
        self.assertLess(shaped_price(model,noon),0)
    def test_no_complete_known_day_falls_back(self):
        from multiday import shaped_price_model
        snapshot,hist=self.setup()
        self.assertIsNone(shaped_price_model({'prices':snapshot['prices'][:50]},hist,self.issue))

class ShapedTailIntegrationTests(unittest.TestCase):
    def test_planner_uses_shaped_three_day_tail_only_when_configured(self):
        from planner import compute_plan,report
        s=json.loads((Path(__file__).parent/'fixtures/test_fixture_snapshot.json').read_text())
        c=json.loads((Path(__file__).parent.parent/'tests/fixtures/config_legacy.json').read_text())
        c.update(tail_price_model='flat_median',forecast_tail_days=7)
        flat=compute_plan(s,c)
        self.assertEqual(len(set(flat['multiday_forecast']['baseline_prices'])),1)
        c.update(tail_price_model='daily_shape',forecast_tail_days=3)
        shaped=compute_plan(s,c)
        tail=shaped['multiday_forecast']
        self.assertEqual(tail['price_model'],'daily_shape_level_reversion_baseline')
        self.assertGreater(len(set(tail['baseline_prices'])),12)
        self.assertEqual(len({r['start'][:10] for r in tail['rows']}),3)
        self.assertEqual([r['price_eur_kwh'] for r in tail['rows']],tail['baseline_prices'])
        self.assertEqual(shaped['valid_until'],flat['valid_until'])
        self.assertIn('Preisniveau Folgetage',report(shaped))
        with self.assertRaises(ValueError):compute_plan(s,{**c,'tail_price_model':'magic'})

class FloorWeatherDstTests(unittest.TestCase):
    def inputs(self):
        s=json.loads((Path(__file__).parent/'fixtures/test_fixture_snapshot.json').read_text())
        from planner_data import prepare
        c=json.loads((Path(__file__).parent.parent/'tests/fixtures/config_legacy.json').read_text())
        return s,c,prepare(s,c)
    def test_price_floor_clips_forecast_and_low_scenario_only(self):
        s,c,d=self.inputs();end=d['intervals'][-1]['end']
        tail=build_tail(s,d,end,{'hours':[]},[],price_model='daily_shape',persistence=1.,price_floor=.20)
        self.assertTrue(all(p>=.20 for p in tail['baseline_prices']))
        self.assertTrue(all(r.price_eur_kwh>=.20 for rows in scenario_rows(tail) for r in rows))
        free=build_tail(s,d,end,{'hours':[]},[],price_model='daily_shape',persistence=1.)
        self.assertLess(min(free['baseline_prices']),.20)
        self.assertEqual(s['prices'],json.loads((Path(__file__).parent/'fixtures/test_fixture_snapshot.json').read_text())['prices'])
    def test_weather_weight_blends_central_pv_and_keeps_dwd_low_case(self):
        s,c,d=self.inputs();end=d['intervals'][-1]['end'];issue=datetime.fromisoformat(s['collected_at'])
        hours=[{'start':((issue-timedelta(days=a)).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(hours=h)).timestamp(),
                'load_kwh':.2,'pv_kwh':.4 if 9<=h<=15 else 0.} for a in range(1,8) for h in range(24)]
        cloudy=copy.deepcopy(s);cloudy['weather_forecasts']=[
            {'datetime':(end+timedelta(hours=i)).isoformat(),'cloud_coverage':100.,'condition':'cloudy'} for i in range(72)]
        totals=[]
        for w in (0.,.5,1.):
            t=build_tail(cloudy,d,end,{'hours':hours},[],weather_weight=w)
            totals.append(sum(r['pv_kwh'] for r in t['rows']))
            self.assertAlmostEqual(sum(r.pv_kwh for r in scenario_rows(t)[2]),totals[0]*.25,places=6)
        self.assertAlmostEqual(totals[1],totals[0]*.625,places=6)
        self.assertAlmostEqual(totals[2],totals[0]*.25,places=6)
        with self.assertRaises(ValueError):build_tail(cloudy,d,end,{'hours':hours},[],weather_weight=2.)
    def test_repeated_dst_hour_is_planned_as_hold_instead_of_failing(self):
        from optimizer import schedules
        start=datetime(2026,10,25,1,tzinfo=TZ).astimezone(timezone.utc)
        rows=[Interval((start+timedelta(minutes=15*i)).astimezone(TZ),(start+timedelta(minutes=15*i+15)).astimezone(TZ),
                       .05 if i<12 else .60,.3,0.) for i in range(20)]
        plan=optimize(rows,Params(10,1,1,'dc',max_charge_kw=2,energy_step_kwh=.25,decision_block_minutes=30))
        repeated=[m for r,m in zip(rows,plan['modes']) if r.start.astimezone(TZ).hour==2]
        self.assertEqual(len(repeated),8);self.assertEqual(set(repeated),{'hold'})
        self.assertIn('charge',plan['modes'])
        self.assertEqual(set(m for r,m in zip(rows,plan['comparison']['serve_baseline']['modes']) if r.start.astimezone(TZ).hour==2),{'hold'})
        schedules(rows,plan['modes'],rows[-1].end)

class SeasonalPvTests(unittest.TestCase):
    issue=datetime(2026,10,24,20,15,tzinfo=TZ)
    def dataset(self,days,value=lambda d:1.):
        hours=[]
        for d in days:
            t=datetime.combine(d,datetime.min.time(),TZ).astimezone(timezone.utc)
            stop=datetime.combine(d+timedelta(days=1),datetime.min.time(),TZ).astimezone(timezone.utc)
            while t<stop:
                hours.append({'start':t.timestamp(),'load_kwh':.2,'pv_kwh':value(d)/4 if 10<=t.hour<14 else 0.})
                t+=timedelta(hours=1)
        return {'hours':hours}
    def test_autumn_matches_spring_by_declination_and_ignores_future(self):
        from multiday import seasonal_pv_model,seasonal_pv_day
        from datetime import date
        spring=[date(2026,2,1)+timedelta(days=i) for i in range(40)]
        summer=[date(2026,6,1)+timedelta(days=i) for i in range(30)]
        future=[self.issue.date()+timedelta(days=i) for i in range(5)]
        data=self.dataset(spring+summer+future,lambda d:2. if d.month<6 else 99. if d>=self.issue.date() else 15.)
        info=seasonal_pv_day(seasonal_pv_model(data,self.issue),date(2026,10,26))
        self.assertAlmostEqual(info['mean_total'],2.)
        self.assertTrue(info['matched_to']<'2026-04-01')
        self.assertIsNone(seasonal_pv_model(self.dataset(spring[:10]),self.issue))
    def test_dwd_cloud_selects_quantile_of_real_season_days(self):
        s=json.loads((Path(__file__).parent/'fixtures/test_fixture_snapshot.json').read_text())
        from planner_data import prepare
        c=json.loads((Path(__file__).parent.parent/'tests/fixtures/config_legacy.json').read_text());d=prepare(s,c)
        end=d['intervals'][-1]['end'];issue=datetime.fromisoformat(s['collected_at'])
        past=[(issue-timedelta(days=200+i)).date() for i in range(60)]+[(issue-timedelta(days=i+1)).date() for i in range(30)]
        data=self.dataset(past,lambda d:1.+d.day%5)
        def tail(cloud,w):
            snap=copy.deepcopy(s);snap['weather_forecasts']=[{'datetime':(end+timedelta(hours=i)).isoformat(),'cloud_coverage':cloud,'condition':'x'} for i in range(72)]
            return build_tail(snap,d,end,data,[],weather_weight=w,pv_model='seasonal_declination')
        dark,bright,base=tail(100.,1.),tail(0.,1.),tail(100.,0.)
        total=lambda t:sum(r['pv_kwh'] for r in t['rows'])
        self.assertEqual(dark['pv_model'],'seasonal_declination_with_dwd_quantile')
        self.assertLess(total(dark),total(base));self.assertGreater(total(bright),total(base))
        self.assertGreaterEqual(total(dark),3*1.-1e-9);self.assertLessEqual(total(bright),3*5.+1e-9)
        with self.assertRaises(ValueError):build_tail(s,d,end,data,[],pv_model='magic')
    def test_weather_vintages_are_archived_once(self):
        from multiday import archive_weather,_db
        s=json.loads((Path(__file__).parent/'fixtures/test_fixture_snapshot.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'audit.sqlite'
            n=archive_weather(path,s);archive_weather(path,s)
            with _db(path) as db:stored=db.execute('SELECT count(*) FROM weather').fetchone()[0]
            self.assertGreater(n,0);self.assertEqual(stored,n)
            self.assertEqual(archive_weather(path,{'collected_at':s['collected_at']}),0)

def _timestamp(value):return datetime.fromisoformat(value).timestamp()

if __name__=='__main__':unittest.main()

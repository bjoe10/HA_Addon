import json,random,tempfile,unittest
from datetime import date,datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import price_weather
from calendar_de import easter,day_type
from multiday import shaped_from_profiles,shaped_level
TZ=ZoneInfo('Europe/Berlin')


class CalendarTests(unittest.TestCase):
    def test_easter_and_holiday_day_types(self):
        self.assertEqual(easter(2026),date(2026,4,5));self.assertEqual(easter(2027),date(2027,3,28))
        self.assertEqual(day_type(date(2026,12,25)),6)        # Christmas: like Sunday
        self.assertEqual(day_type(date(2026,12,24)),5)        # Christmas Eve: like Saturday
        self.assertEqual(day_type(date(2026,4,3)),6)          # Good Friday
        self.assertEqual(day_type(date(2026,11,18)),2)        # ordinary Wednesday
        self.assertEqual(day_type(date(2026,12,25),False),4)

    def test_holiday_uses_sunday_offset(self):
        profiles={}
        for i in range(100):     # Sundays cheap, all other days expensive
            d=date(2026,9,15)+timedelta(days=i);level=.10 if d.weekday()==6 else .30
            profiles[d]=(level,{h:level for h in range(24)})
        anchor=max(profiles)
        with_holidays=shaped_from_profiles(profiles,anchor,.3,56,True,True)
        plain=shaped_from_profiles(profiles,anchor,.3,56,True,False)
        christmas=date(2026,12,25)     # a Friday
        self.assertLess(shaped_level(with_holidays,christmas),shaped_level(plain,christmas)-.1)


def weather_payload(days,wind,sun=lambda d:100.,points=8):
    out=[]
    for _ in range(points):
        times=[];w=[];s=[]
        for d in days:
            for h in range(24):
                times.append(f'{d.isoformat()}T{h:02d}:00');w.append(wind(d));s.append(sun(d))
        out.append({'hourly':{'time':times,'wind_speed_100m':w,'shortwave_radiation':s}})
    return out


def synthetic(days=420,effect=-.08,noise=.01,seed=1):
    """Exchange prices whose daily level drops with wind; weather history with the matching wind."""
    rng=random.Random(seed);today=date(2026,11,17);first=today-timedelta(days=days)
    wind={};spot={};history={}
    for i in range(days+5):
        d=first+timedelta(days=i);cf=rng.random();wind[d]=cf
        history[d.isoformat()]=[cf,100.]
        level=.12+effect*cf+rng.gauss(0,noise)
        for h in range(24):
            t=datetime.combine(d,datetime.min.time(),TZ).replace(hour=h).timestamp()
            spot[t]=level+(.02 if 17<=h<=20 else 0.)
    return today,spot,{'history':history}


class FitTests(unittest.TestCase):
    def test_capacity_factor_and_daily_features(self):
        self.assertEqual(price_weather.capacity_factor(2.),0.);self.assertEqual(price_weather.capacity_factor(12.),1.)
        self.assertEqual(price_weather.capacity_factor(30.),0.)
        days=[date(2026,11,18),date(2026,11,19)]
        features=price_weather.daily_features(weather_payload(days,lambda d:12.,lambda d:50.))
        self.assertEqual(features['2026-11-18'],[1.,50.])
        partial=weather_payload(days,lambda d:12.)
        for loc in partial:
            for key in ('time','wind_speed_100m','shortwave_radiation'):loc['hourly'][key]=loc['hourly'][key][:30]
        self.assertNotIn('2026-11-19',price_weather.daily_features(partial))     # incomplete day skipped

    def test_fit_learns_wind_effect_and_passes_validation(self):
        today,spot,state=synthetic()
        model=price_weather.fit(spot,state,today)
        self.assertTrue(model['active'],model.get('reason'))
        self.assertLess(model['validation_error_weather'],model['validation_error_plain'])
        self.assertLess(model['coefficients']['2'][1],-.05)          # windy target day: cheaper
        state['forecast']={'days':{'2026-11-18':[.5,100.],'2026-11-20':[1.,100.]}}
        corr=price_weather.correction(state,model,1.19)
        windy=corr(date(2026,11,18),date(2026,11,20));calm_unknown=corr(date(2026,11,18),date(2026,11,21))
        self.assertLess(windy,0);self.assertIsNone(calm_unknown)

    def test_fit_without_weather_effect_stays_off(self):
        today,spot,state=synthetic(effect=0.,noise=.02,seed=3)
        model=price_weather.fit(spot,state,today)
        if model['active']:     # pure noise may pass by chance; then the effect must be small
            self.assertLess(abs(model['coefficients']['1'][1]),.02)
        self.assertIsNone(price_weather.correction({},model,1.19)(date(2026,11,18),date(2026,11,19)))

    def test_too_little_history_is_not_active(self):
        today,spot,state=synthetic(days=90)
        model=price_weather.fit(spot,state,today)
        self.assertFalse(model['active']);self.assertIn('zu wenig',model['reason'])

    def test_refresh_is_incremental_and_bounded(self):
        calls=[]
        def fake(url,params,timeout=60):
            calls.append((url,params))
            if 'start_date' in params:
                s=date.fromisoformat(params['start_date']);e=date.fromisoformat(params['end_date'])
                days=[s+timedelta(days=i) for i in range((e-s).days+1)]
            else:days=[date(2026,11,16)+timedelta(days=i) for i in range(7)]
            return weather_payload(days,lambda d:8.)
        state=price_weather.refresh({},date(2026,11,17),get=fake)
        self.assertEqual(calls[0][1]['start_date'],(date(2026,11,17)-timedelta(days=price_weather.HISTORY_DAYS)).isoformat())
        self.assertIn('2026-11-16',state['history']);self.assertIn('2026-11-20',state['forecast']['days'])
        state=price_weather.refresh(state,date(2026,11,18),get=fake)
        self.assertEqual(calls[2][1]['start_date'],'2026-11-14')
        self.assertGreaterEqual(min(state['history']),(date(2026,11,18)-timedelta(days=price_weather.HISTORY_DAYS)).isoformat())
        self.assertEqual(calls[0][1]['latitude'].count(','),len(price_weather.POINTS)-1)


class LogTests(unittest.TestCase):
    def test_log_and_week_errors(self):
        rows=[{'start':(datetime(2026,11,19,tzinfo=TZ)+timedelta(hours=h)).isoformat()} for h in range(48)]
        tail={'rows':rows,'uncorrected_prices':[.40]*48,'baseline_prices':[.36]*24+[.38]*24}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'log.json'
            price_weather.log_forecast(path,tail,date(2026,11,17))
            log=price_weather.log_forecast(path,{**tail,'baseline_prices':[0.]*48},date(2026,11,17))   # second run same day ignored
        self.assertEqual(len(log),2);self.assertAlmostEqual(log[0]['weather'],.36)
        errors=price_weather.week_errors(log,{'2026-11-19':.35,'2026-11-20':.40},date(2026,11,16),date(2026,11,23))
        self.assertEqual(errors['count'],2)
        self.assertAlmostEqual(errors['plain'],.025);self.assertAlmostEqual(errors['weather'],.015)
        self.assertIsNone(price_weather.week_errors(log,{},date(2026,11,16),date(2026,11,23)))


if __name__=='__main__':unittest.main()

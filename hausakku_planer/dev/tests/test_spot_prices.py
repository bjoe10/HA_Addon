import json,tempfile,unittest
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo
import spot_prices
from spot_prices import parse,calibrate,reconstructed_history,refresh
TZ=ZoneInfo('Europe/Berlin')

def payload(start,count,price=lambda i:50.):
    t0=start.timestamp()
    return {'unit':'EUR / MWh','unix_seconds':[int(t0+900*i) for i in range(count)],'price':[price(i) for i in range(count)]}

class SpotPriceTests(unittest.TestCase):
    def test_parse_converts_mwh_and_rejects_unknown_unit(self):
        rows=parse({**payload(datetime(2026,10,24,tzinfo=TZ),3),'price':[50.,None,-10.]})
        self.assertEqual(list(rows.values()),[.05,-.01])
        with self.assertRaises(ValueError):parse({'unit':'ct/kWh','unix_seconds':[],'price':[]})
    def test_exact_tariff_fit_reconstructs_missing_quarter_hours_only(self):
        start=datetime(2026,10,1,tzinfo=TZ)
        spot=parse(payload(start,96*3,lambda i:(i%96)-20.))
        archive=[{'start':t,'issued_at':t-86400,'price':.1735+1.19*p} for t,p in list(spot.items())[96*2:]]
        cal=calibrate(spot,archive)
        self.assertTrue(cal['valid']);self.assertAlmostEqual(cal['fixed_eur_kwh'],.1735);self.assertAlmostEqual(cal['factor'],1.19)
        rows=reconstructed_history(spot,cal,archive)
        self.assertEqual(len(rows),96*2);self.assertTrue(all(r['start'] not in {a['start'] for a in archive} for r in rows))
        first=rows[0];self.assertAlmostEqual(first['price'],.1735+1.19*spot[first['start']])
        self.assertEqual(datetime.fromtimestamp(first['issued_at'],TZ),datetime(2026,9,30,12,tzinfo=TZ))
    def test_tariff_change_disables_reconstruction(self):
        spot=parse(payload(datetime(2026,10,1,tzinfo=TZ),200,lambda i:float(i%40)))
        archive=[{'start':t,'issued_at':t,'price':.1735+1.19*p+(.01 if i%2 else 0)} for i,(t,p) in enumerate(spot.items())]
        cal=calibrate(spot,archive)
        self.assertFalse(cal['valid']);self.assertEqual(reconstructed_history(spot,cal,archive),[])
        self.assertFalse(calibrate(spot,archive[:10])['valid'])
    def test_refresh_is_incremental(self):
        calls=[]
        def fake(params,timeout=60):
            calls.append(params);s=datetime.fromisoformat(params['start']).replace(tzinfo=TZ)
            days=(date.fromisoformat(params['end'])-date.fromisoformat(params['start'])).days+1
            return payload(s,96*days)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(spot_prices,'_get',fake):
            path=Path(tmp)/'s.json'
            first=refresh(path,date(2026,1,5));second=refresh(path,date(2026,1,8))
        self.assertEqual(calls[0]['start'],'2026-01-01');self.assertEqual(calls[1]['start'],'2026-01-04')
        self.assertEqual(calls[0]['bzn'],'DE-LU');self.assertGreater(len(second),len(first))

class WeekdayPriceTests(unittest.TestCase):
    def test_weekday_offsets_raise_expensive_weekdays(self):
        from multiday import shaped_price_model,shaped_price
        issue=datetime(2026,10,24,20,15,tzinfo=TZ)
        hist=[];known=[]
        for age in range(-1,60):
            day=issue.date()-timedelta(days=age)
            level=.40 if day.weekday()==0 else .25
            t=datetime.combine(day,datetime.min.time(),TZ).timestamp()
            for i in range(96):
                row={'start':t+900*i,'price':level,'issued_at':t+900*i-86400}
                if age<=0:known.append({'start_time':datetime.fromtimestamp(t+900*i,TZ).isoformat(),'price':level})
                else:hist.append(row)
        model=shaped_price_model({'prices':known},hist,issue,persistence=.3,long_days=56,weekday=True)
        monday=datetime(2026,10,26,12,tzinfo=TZ);tuesday=datetime(2026,10,27,12,tzinfo=TZ)
        self.assertGreater(shaped_price(model,monday)-shaped_price(model,tuesday),.1)
        flat=shaped_price_model({'prices':known},hist,issue,persistence=.3,long_days=56)
        self.assertAlmostEqual(shaped_price(flat,monday)-shaped_price(flat,tuesday),
                               (flat['known_level']-flat['long_level'])*(.3-.09))
        with self.assertRaises(ValueError):shaped_price_model({'prices':known},hist,issue,long_days=99)

if __name__=='__main__':unittest.main()

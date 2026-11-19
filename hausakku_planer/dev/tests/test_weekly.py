import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
import weekly_report

TZ=ZoneInfo('Europe/Berlin')

def hours(n,t0=1_800_000_000):
    return [{'start':t0+3600*i,'ev':0.,'grid':1.,'wr':0.,'charger':0.,'export':0.,'pv':0.} for i in range(n)]

class TrailingCompleteTests(unittest.TestCase):
    def test_full_week_keeps_requested_start(self):
        hs=hours(48);start=datetime.fromtimestamp(hs[0]['start'],TZ)
        block,s=weekly_report.trailing_complete(hs,{h['start']:.3 for h in hs},start)
        self.assertEqual(len(block),48);self.assertEqual(s,start)
    def test_missing_prices_shorten_to_the_latest_unbroken_block(self):
        hs=hours(72);prices={h['start']:.3 for h in hs[30:]}   # archive begins 30 h into the period
        block,s=weekly_report.trailing_complete(hs,prices,datetime.fromtimestamp(hs[0]['start'],TZ))
        self.assertEqual(len(block),42);self.assertEqual(block[0]['start'],hs[30]['start'])
        self.assertEqual(int(s.timestamp()),hs[30]['start'])
    def test_a_gap_cuts_the_block(self):
        hs=hours(60);prices={h['start']:.3 for h in hs};del prices[hs[20]['start']]
        block,_=weekly_report.trailing_complete(hs,prices,datetime.fromtimestamp(hs[0]['start'],TZ))
        self.assertEqual(len(block),39)
    def test_too_short_is_an_error(self):
        hs=hours(40);prices={h['start']:.3 for h in hs[25:]}
        with self.assertRaises(ValueError):weekly_report.trailing_complete(hs,prices,datetime.fromtimestamp(hs[0]['start'],TZ))
    def test_incomplete_measurement_counts_as_gap(self):
        hs=hours(50);hs[10]['pv']=None
        block,_=weekly_report.trailing_complete(hs,{h['start']:.3 for h in hs},datetime.fromtimestamp(hs[0]['start'],TZ))
        self.assertEqual(len(block),39)

if __name__=='__main__':unittest.main()


class PhoneTextTests(unittest.TestCase):
    def test_phone_text_is_short_and_uses_the_facts(self):
        from datetime import timedelta
        r={'cash_saving_eur':-.8,'saving_incl_inventory_eur':.4,'grid_charged_ac_kwh':12.9,'mean_charge_price_eur_kwh':.338,
           'battery_served_ac_kwh':18.,'mean_served_price_eur_kwh':.587,'house_load_kwh':58.9,'pv_kwh':17.2}
        start=datetime(2026,11,16,tzinfo=ZoneInfo('Europe/Berlin'))
        text=weekly_report.phone_text(r,(start,start+timedelta(days=7)),{'last_week_eur':1.6,'total_eur':0.},{'plain':.047,'weather':.031})
        lines=text.split('\n')
        self.assertEqual(lines[0],'16.11.–22.11.')
        self.assertIn('Woche +1,60 €, gesamt +0,00 €',text);self.assertIn('Netzladen 12,9 kWh zu Ø 33,8 ct',text)
        self.assertIn('ohne Wetter 4,7 ct, mit Wetter 3,1 ct',text);self.assertLessEqual(len(lines),7)
        self.assertNotIn('Netzladen',weekly_report.phone_text({**r,'grid_charged_ac_kwh':0.},(start,start+timedelta(days=7))))

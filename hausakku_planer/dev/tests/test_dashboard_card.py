import asyncio, json, os, shutil, subprocess, tempfile, unittest
from urllib.parse import quote
import dashboard_card as card, settings
from ha_client import HA, WritesDisabled

def run(coro):return asyncio.run(coro)

class FakeTransport:
    """Lovelace resources in memory; records every write."""
    def __init__(self,resources=()):
        self.resources=[dict(r) for r in resources];self.writes=[]
    async def command(self,**p):
        kind=p.pop('type')
        if kind=='lovelace/resources':return [dict(r) for r in self.resources]
        self.writes.append((kind,p))
        if kind=='lovelace/resources/create':
            self.resources.append({'id':'new','type':p['res_type'],'url':p['url']});return {'id':'new'}
        if kind=='lovelace/resources/update':
            next(r for r in self.resources if r['id']==p['resource_id'])['url']=p['url'];return {}
        raise AssertionError('unexpected command '+kind)

def module(source):return card.resource_url(source)

class CardSourceTests(unittest.TestCase):
    def test_defaults_come_from_the_settings(self):
        cfg=settings.current();names=cfg.helpers()
        d=card.card_defaults(cfg,'1.2.3')
        self.assertEqual(d['version'],'1.2.3')
        self.assertEqual(d['battery_entity'],cfg.entity('battery_soc'))
        self.assertEqual(d['charge_schedule'],'schedule.'+names['charge'])
        self.assertEqual(d['expiry_entity'],'input_datetime.'+names['expiry'])
        self.assertEqual(d['plan_report_entity'],'sensor.'+names['report'])
        self.assertNotIn(None,d.values())

    def test_defaults_are_filled_in_once(self):
        source=card.card_source({'version':'1.2.3','battery_entity':'sensor.soc'})
        self.assertIn('const ADDON = {"battery_entity": "sensor.soc", "version": "1.2.3"}; // hausakku-addon-defaults',source)
        self.assertNotIn(card.MARKER,source)
        with self.assertRaises(ValueError):card.card_source({},template='no marker here')

    def test_resource_url_round_trip_and_version(self):
        source=card.card_source({'version':'0.10.0'})
        resource={'id':'a','url':card.resource_url(source)}
        self.assertEqual(card.decode_resource(resource['url']),source)
        self.assertEqual(card.installed_version(resource),'0.10.0')
        self.assertEqual(card.decode_resource('data:text/javascript;charset=utf-8,'+quote('let a = 1;')),'let a = 1;')
        self.assertIsNone(card.decode_resource('/local/card.js'))
        self.assertIsNone(card.installed_version({'url':'/local/card.js'}))

    def test_finds_an_earlier_copy_of_the_card_but_no_other_resource(self):
        other={'id':'x','url':'/hacsfiles/mushroom/mushroom.js'}
        inline_other={'id':'y','url':module("customElements.define('hausakku-timeline', X);")}
        earlier={'id':'z','url':module("customElements.define('tibber-prices-battery-chart-card', C);")}
        self.assertEqual(card.find_card([other,inline_other,earlier])['id'],'z')
        self.assertIsNone(card.find_card([other,inline_other]))

    def test_tibber_home_from_the_registry(self):
        registry=[{'platform':'tibber','device_id':'a','translation_key':'current_interval_price'},
                  {'platform':'tibber_prices','device_id':'b','translation_key':'best_price_period'},
                  {'platform':'tibber_prices','device_id':'c','translation_key':'current_interval_price'}]
        self.assertEqual(card.tibber_device(registry),'c')
        self.assertIsNone(card.tibber_device(registry[:2]))

    def test_shipped_card_has_no_household_entities(self):
        text=card.CARD.read_text()
        for word in ('ant_bms','vom_stein','meross','zigbee','hausakku_','raw_pv','hausbatterie'):self.assertNotIn(word,text)
        self.assertEqual(text.count(card.MARKER),1)

class InstallTests(unittest.TestCase):
    def test_creates_updates_and_leaves_other_resources_alone(self):
        other={'id':'x','url':'/hacsfiles/mushroom/mushroom.js'}
        t=FakeTransport([other]);ha=HA(t,mode='publish')
        url=card.resource_url(card.card_source({'version':'1'}))
        self.assertEqual(run(ha.install_card(url))['action'],'created')
        self.assertEqual(run(ha.install_card(url))['action'],'unchanged')
        newer=card.resource_url(card.card_source({'version':'2'}))
        self.assertEqual(run(ha.install_card(newer)),{'action':'updated','resource_id':'new'})
        self.assertEqual(t.resources[0],other)
        self.assertEqual([w[0] for w in t.writes],['lovelace/resources/create','lovelace/resources/update'])

    def test_adopt_only_updates_but_never_creates(self):
        url=card.resource_url(card.card_source({'version':'1'}))
        t=FakeTransport();self.assertEqual(run(HA(t,mode='publish').install_card(url,adopt_only=True)),{'action':'absent'})
        self.assertEqual(t.writes,[])
        earlier={'id':'z','url':module("customElements.define('tibber-prices-battery-chart-card', C);")}
        t=FakeTransport([earlier]);self.assertEqual(run(HA(t,mode='publish').install_card(url,adopt_only=True))['action'],'updated')
        self.assertEqual(t.resources[0]['url'],url)

    def test_observe_writes_nothing(self):
        t=FakeTransport()
        with self.assertRaises(WritesDisabled):run(HA(t,mode='observe').install_card('data:,x'))
        self.assertEqual(t.writes,[])

@unittest.skipUnless(shutil.which('node'),'node not installed')
class CardScriptTests(unittest.TestCase):
    """The filled-in card still parses, and its pure helpers compute what the tiles and lines show."""
    def test_card_helpers(self):
        source=card.card_source({'version':'1','battery_entity':'sensor.soc','capacity_kwh':16})
        check="""
import * as c from './card.mjs';
const out = {
  measured: c.batteryEnergyPresentation('33', '5.2').label,
  fromCapacity: c.batteryEnergyPresentation('50', undefined, 10, 16).label,
  missing: c.batteryEnergyPresentation('unavailable', undefined, 10, 16).available,
  target: c.chargeTargetPresentation('40', '80', undefined, 16).label,
  grid: c.gridPresentation('0', '1250').label,
  next: c.nextPeriod([{start: '2026-11-02T12:15:00+01:00', end: '2026-11-02T14:45:00+01:00'},
                      {start: '2026-11-02T22:45:00+01:00', end: '2026-11-03T05:45:00+01:00'}], Date.parse('2026-11-02T20:00:00+01:00')),
  plan: c.socPlanPoints({start: '2026-11-02T20:00:00+01:00', initial_kwh: 2.5, minutes: [15, 30], kwh: [2.4, 2.3]}).length,
};
out.period = c.periodPresentation(out.next.start, out.next.end, Date.parse('2026-11-02T20:00:00+01:00'), 'Europe/Berlin').text;
console.log(JSON.stringify(out));
"""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d,'card.mjs'),'w') as f:f.write(source)
            with open(os.path.join(d,'check.mjs'),'w') as f:f.write(check)
            r=subprocess.run(['node','check.mjs'],cwd=d,capture_output=True,text=True,timeout=60)
        self.assertEqual(r.returncode,0,r.stderr)
        out=json.loads(r.stdout)
        self.assertEqual(out['measured'],'5,2 kWh');self.assertEqual(out['fromCapacity'],'8,0 kWh');self.assertFalse(out['missing'])
        self.assertEqual(out['target'],'+6,4 kWh bis Ziel');self.assertEqual(out['grid'],'−1,25 kW')
        self.assertEqual(out['period'],'22:45–05:45');self.assertEqual(out['plan'],3)

if __name__=='__main__':unittest.main()

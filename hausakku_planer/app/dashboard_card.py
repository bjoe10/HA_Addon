"""The dashboard card shipped with the add-on: the Tibber Prices chart with battery, plan and clock.

The add-on fills in its own entities (helpers, battery, capacity) and installs the card as one inline Lovelace
resource when asked, then keeps exactly that resource current. No other resource is ever written.
"""
import base64, json, os, re
from pathlib import Path
from urllib.parse import unquote
import settings

CARD=Path(__file__).resolve().parent/'card'/'hausakku-card.js'
ELEMENT='tibber-prices-battery-chart-card'
MARKER='const ADDON = {}; // hausakku-addon-defaults'
FILLED=re.compile(r'const ADDON = (\{.*?\}); // hausakku-addon-defaults')

def version():
    return os.environ.get('HAUSAKKU_VERSION') or 'dev'

def card_defaults(cfg,addon_version=None):
    """What the card takes from the add-on unless the dashboard config says otherwise."""
    names=cfg.helpers()
    values={'version':addon_version or version(),
            'battery_entity':cfg.entity('battery_soc',required=False),
            'battery_kwh_entity':cfg.entity('battery_kwh',required=False),
            'capacity_kwh':(cfg.data.get('battery') or {}).get('capacity_kwh'),
            'charge_schedule':'schedule.'+names['charge'],'serve_schedule':'schedule.'+names['serve'],
            'expiry_entity':'input_datetime.'+names['expiry'],'permission_entity':'input_boolean.'+names['permission'],
            'owner_entity':'input_boolean.'+names['owner'],'target_soc_entity':'input_number.'+names['target'],
            'plan_report_entity':'sensor.'+names['report']}
    return {k:v for k,v in values.items() if v not in (None,'')}

def card_source(defaults,template=None):
    text=CARD.read_text() if template is None else template
    if text.count(MARKER)!=1:raise ValueError('Kartenvorlage ohne Platzhalter für die Add-on-Werte')
    return text.replace(MARKER,'const ADDON = '+json.dumps(defaults,ensure_ascii=False,sort_keys=True)+'; // hausakku-addon-defaults')

def resource_url(source):
    """An inline module: the card needs no file in Home Assistant's config folder."""
    return 'data:text/javascript;base64,'+base64.b64encode(source.encode()).decode()

def current_url(cfg=None):
    return resource_url(card_source(card_defaults(cfg or settings.current())))

def decode_resource(url):
    if not isinstance(url,str) or not url.startswith('data:'):return None
    head,_,body=url.partition(',')
    try:return base64.b64decode(body).decode() if head.endswith(';base64') else unquote(body)
    except ValueError:return None

def find_card(resources):
    """The resource that registers the card's element: one installed by the add-on or an earlier copy of the card."""
    for resource in resources or []:
        source=decode_resource(resource.get('url'))
        if source and f"customElements.define('{ELEMENT}'" in source:return resource
    return None

def installed_version(resource):
    match=FILLED.search(decode_resource((resource or {}).get('url')) or '')
    try:return json.loads(match.group(1)).get('version') if match else None
    except ValueError:return None

def tibber_device(registry):
    """The Tibber Prices home (its device), which the chart needs as device_id."""
    entry=next((e for e in registry or [] if e.get('platform')=='tibber_prices'
                and e.get('translation_key')=='current_interval_price' and e.get('device_id')),None)
    return entry['device_id'] if entry else None

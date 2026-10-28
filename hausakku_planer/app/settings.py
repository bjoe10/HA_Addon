"""User settings: which HA entities play which role, location, planner overrides.

Stored in <data>/settings.json (written by the web UI). The add-on options only carry the
operating mode and log level. Nothing household-specific is defaulted: an unconfigured
role raises NotConfigured with a message naming the role.
"""
import json, os, re
from pathlib import Path
import paths

HERE=Path(__file__).resolve().parent
MODES=('observe','publish','control')

# role -> (label, needed for: 'plan' = computing a plan, 'control' = switching hardware, 'optional')
ROLES={
 'grid_import':('Netzbezug (kWh-Zähler)','plan'),
 'grid_export':('Einspeisung (kWh-Zähler)','plan'),
 'pv_energy':('PV-Erzeugung (kWh-Zähler)','plan'),
 'inverter_energy':('Wechselrichter-Ausgang AC (kWh-Zähler)','plan'),
 'charger_energy':('Netzladegerät AC-Eingang (kWh-Zähler)','plan'),
 'battery_soc':('Akku-Ladestand in %','plan'),
 'battery_kwh':('Akku-Inhalt in kWh (sonst SOC × Kapazität)','optional'),
 'battery_voltage':('Akku-Spannung (nur für Wirkungsgrad-Messung)','optional'),
 'battery_in_energy':('Akku-Ladeenergie DC (Wirkungsgrad-Messung)','optional'),
 'battery_out_energy':('Akku-Entladeenergie DC (Wirkungsgrad-Messung)','optional'),
 'charger_switch':('Schalter Netzladegerät','control'),
 'inverter_switch':('Schalter Wechselrichter','control'),
 'pv_forecast_today':('PV-Prognose heute (z. B. Forecast.Solar)','optional'),
 'pv_forecast_today_remaining':('PV-Prognose Rest heute','optional'),
 'pv_forecast_tomorrow':('PV-Prognose morgen','optional'),
 'weather':('Wetter-Entität mit stündlicher Vorhersage','optional'),
 'ev_energy':('Fahrzeug-Ladezähler, die nicht zum Hausverbrauch zählen (Liste)','optional'),
 'ev_soc':('Fahrzeug-Ladestand','optional'),
 'ev_target_soc':('Fahrzeug-Ladeziel','optional'),
 'ev_plug':('Fahrzeug eingesteckt','optional'),
 'ev_window_helper':('Name eines Zeitplan-Helfers für das Fahrzeug-Ladefenster','optional'),
}
LISTS={'ev_energy'}

DEFAULTS={
 'helper_prefix':'hap',
 'adopt_legacy_helpers':False,
 'location':{'latitude':None,'longitude':None},
 'entities':{r:([] if r in LISTS else None) for r in ROLES},
 'prices':{'provider':'tibber','tibber_home':None,'entity':None,'attribute':None,'bidding_zone':'DE-LU','markup_ct':0.0,'vat_percent':0.0},
 'battery':{'capacity_kwh':None,'max_charge_kw':None,'max_discharge_kw':None,'nominal_voltage':None},
 'tariff':{'price_floor_eur_kwh':None},
 'planner':{},
}

# Pseudo-roles that can be missing without being an entity role.
EXTRA_LABELS={'price_entity':'Preis-Sensor (Strompreis)'}

def label(role):
    return ROLES[role][0] if role in ROLES else EXTRA_LABELS.get(role,role)

class NotConfigured(RuntimeError):
    pass

PREFIX_RE=re.compile(r'^[a-z][a-z0-9]{1,15}$')
# Names the original single-household planner uses; the add-on must never write them.
RESERVED_PREFIX='hausakku'

def check_prefix(prefix,adopt_legacy=False):
    """Error text for an unusable helper prefix, else None. `adopt_legacy` allows exactly "hausakku":
    the add-on then takes over the helpers of an existing single-household controller."""
    if adopt_legacy and prefix==RESERVED_PREFIX:return None
    if not isinstance(prefix,str) or not PREFIX_RE.match(prefix):
        return 'Präfix: 2 bis 16 Zeichen, nur Kleinbuchstaben und Ziffern, mit Buchstabe beginnend'
    if prefix.startswith(RESERVED_PREFIX):
        return 'Präfix darf nicht mit "'+RESERVED_PREFIX+'" beginnen (so heißen die Helfer des Original-Planers)'
    return None

def _merge(base,over):
    out={k:(dict(v) if isinstance(v,dict) else v) for k,v in base.items()}
    for k,v in over.items():
        out[k]=_merge(out[k],v) if isinstance(v,dict) and isinstance(out.get(k),dict) else v
    return out

class Settings:
    def __init__(self,data=None):
        self.data=_merge(DEFAULTS,data or {})

    def entity(self,role,required=True):
        value=self.data['entities'].get(role)
        if role in LISTS:
            raise ValueError(role+' is a list; use entities()')
        if not value and required:
            raise NotConfigured('Nicht eingerichtet: '+ROLES[role][0])
        return value or None

    def entities(self,role):
        return list(self.data['entities'].get(role) or [])

    def missing(self,stage='plan'):
        """Roles that must be set before `stage` ('plan' or 'control') can work."""
        need={'plan'} if stage=='plan' else {'plan','control'}
        missing=[r for r,(text,when) in ROLES.items() if when in need and not self.data['entities'].get(r)]
        prices=self.data['prices']
        if prices.get('provider')=='entity' and not prices.get('entity'):missing.append('price_entity')
        return missing

    def helpers(self):
        """Object ids of the add-on's own helpers, derived from the prefix."""
        prefix=self.data['helper_prefix']
        error=check_prefix(prefix,bool(self.data.get('adopt_legacy_helpers')))
        if error:raise ValueError(error)
        return {'charge':prefix+'_netzladen','serve':prefix+'_entladen','expiry':prefix+'_plan_gueltig_bis',
                'status':prefix+'_plan_status','report':prefix+'_bericht','owner':prefix+'_regler_uebernommen','timer':prefix+'_schaltsperre','target':prefix+'_ziel_soc','permission':prefix+'_planer_freigabe'}

    def location(self):
        loc=self.data['location']
        if loc.get('latitude') is None or loc.get('longitude') is None:return None
        return float(loc['latitude']),float(loc['longitude'])

    def planner_config(self):
        """Neutral defaults, overridden by the user's planner values, plus location and capacity."""
        config=json.loads((HERE/'planner_defaults.json').read_text())
        config.update(self.data['planner'])
        loc=self.location()
        if loc:config['openmeteo_latitude'],config['openmeteo_longitude']=loc
        elif config.get('pv_forecast_source')=='openmeteo_radiation':
            config['pv_forecast_source']='ha_solarforecast'
        battery=self.data['battery']
        for key in ('capacity_kwh','max_charge_kw','max_discharge_kw'):
            if battery.get(key):config[key]=float(battery[key])
        floor=self.data['tariff'].get('price_floor_eur_kwh')
        if floor is not None:   # fixed price parts that no market price falls below: bounds forecasts and leftover energy value
            config['tail_price_floor_eur_kwh']=float(floor);config['tail_end_value_from_floor']=True
        return config

def operating_mode():
    mode=os.environ.get('HAUSAKKU_MODE','observe')
    return mode if mode in MODES else 'observe'

def load(path=None):
    path=Path(path or os.environ.get('HAUSAKKU_SETTINGS') or paths.DATA/'settings.json')
    return Settings(json.loads(path.read_text()) if path.exists() else None)

_current=None
def current():
    global _current
    if _current is None:_current=load()
    return _current

def use(settings):
    """Replace the active settings (tests, UI after saving)."""
    global _current
    _current=settings if isinstance(settings,Settings) or settings is None else Settings(settings)

def save(data,path=None):
    path=Path(path or paths.DATA/'settings.json');path.parent.mkdir(parents=True,exist_ok=True)
    merged=Settings(data).data
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(merged,indent=2,ensure_ascii=False));tmp.replace(path)
    use(None)
    return merged

"""Build UI-editable HA controller config; pure config, never actuates hardware.
Guard core is shared verbatim between local fixtures and the live HA template.
"""
CHARGER='switch.charger_plug'
INVERTER='switch.inverter_plug'
PERMISSION='input_boolean.hausakku_planer_freigabe'
OWNER='input_boolean.hausakku_regler_uebernommen'
GUARD='sensor.hausakku_regelmodus'
TIMER='timer.hausakku_schaltsperre'
AUTOMATION='automation.hausakku_fahrplan_steuerung'

GUARD_PREAMBLE="""{%- set hb = states('sensor.ant_bms_16_total_runtime') -%}
{%- set boot = as_timestamp(states('sensor.uptime'), 0) -%}
{%- set hb_updated = as_timestamp(states.sensor.ant_bms_16_total_runtime.last_updated, 0) if has_value('sensor.ant_bms_16_total_runtime') else 0 -%}
{%- set age = as_timestamp(now()) - hb_updated if has_value('sensor.ant_bms_16_total_runtime') else 999999 -%}
{%- set v = {
'enabled': is_state('input_boolean.hausakku_planer_freigabe','on'),
'online': is_state('binary_sensor.ant_bms_16_online_status','on'),
'hb_age': age, 'hb_after_start': boot > 0 and hb_updated > boot, 'soc': states('sensor.ant_bms_16_soc'),
'voltage': states('sensor.ant_bms_16_total_voltage'),
'temps': [states('sensor.ant_bms_16_temperature_1'),states('sensor.ant_bms_16_temperature_2'),states('sensor.ant_bms_16_temperature_3'),states('sensor.ant_bms_16_temperature_4')],
'charge_mos': states('sensor.ant_bms_16_charge_mosfet_status')|lower,
'discharge_mos': states('sensor.ant_bms_16_discharge_mosfet_status')|lower,
'low_batt': states('input_boolean.batt_leer'),
'reserve': states('binary_sensor.keller_ant_bms_16_hausakku_reserve_sperre'),
'low_voltage': states('binary_sensor.keller_ant_bms_16_hausakku_spannung_niedrig'),
'legacy_block': 'absent' if states.input_boolean.auto_netz_laden is none else states('input_boolean.auto_netz_laden'),
'charger': states('switch.charger_plug'), 'inverter': states('switch.inverter_plug'),
'plan': states('sensor.hausakku_betriebsstrategie'),
'plan_valid': state_attr('input_datetime.hausakku_plan_gueltig_bis','timestamp')|float(0) > as_timestamp(now()),
 'target': states('input_number.hausakku_ziel_soc')
} -%}
"""
GUARD_LOGIC="""{%- set valid = namespace(ok=true) -%}
{%- for x in [v.soc,v.voltage,v.hb_age] + v.temps -%}
  {%- if not is_number(x) -%}{%- set valid.ok=false -%}{%- endif -%}
{%- endfor -%}
{%- set soc=v.soc|float(-999) -%}
{%- set voltage=v.voltage|float(-999) -%}
{%- set lowtemp=v.temps|map('float',-999)|min -%}
{%- set hightemp=v.temps|map('float',999)|max -%}
{%- set target=[v.target|float(0),90]|min -%}
{%- if not v.enabled -%}manuell
{%- elif not valid.ok or not v.online or not v.get('hb_after_start',false) or not 0 <= v.hb_age|float(999999) <= 120
    or not 0 <= soc <= 100 or not 40 <= voltage <= 60
    or lowtemp < 0 or hightemp > 45
    or v.charger not in ['on','off'] or v.inverter not in ['on','off']
    or (v.charger == 'on' and v.inverter == 'on')
    or v.legacy_block not in ['off','absent']
    or v.low_batt not in ['on','off']
    or v.reserve not in ['on','off'] or v.low_voltage not in ['on','off']
    or v.charge_mos not in ['on','off','overcharge protection','battery full'] or v.discharge_mos not in ['on','off']
    or v.plan == 'fehler' -%}sicher_aus
{%- elif v.plan_valid and v.plan == 'netzladen' -%}
  {%- if v.charge_mos == 'on' and lowtemp >= 5 and hightemp <= 40 and voltage < 56
       and target > 0 and soc < target
       and (v.charger == 'on' or soc <= target - 2) -%}netzladen
  {%- else -%}ladepause{%- endif -%}
{%- elif v.low_batt != 'off' or v.reserve != 'off' or v.low_voltage != 'off'
    or soc <= 10 or voltage <= 48.9 or v.discharge_mos != 'on' -%}reserve
{%- elif v.plan_valid and v.plan == 'aufheben' -%}aufheben
{%- elif v.plan_valid and v.plan == 'versorgen' -%}versorgen
{%- else -%}plan_fallback
{%- endif -%}"""
GUARD_TEMPLATE=GUARD_PREAMBLE+GUARD_LOGIC

def state(entity,value):return {'condition':'state','entity_id':entity,'state':value}
def neg(condition):return {'condition':'not','conditions':[condition]}
def all_of(*conditions):return {'condition':'and','conditions':list(conditions)}
def any_of(*conditions):return {'condition':'or','conditions':list(conditions)}
def action(service,entity,**data):
    d={'action':service,'target':{'entity_id':entity}}
    if data:d['data']=data
    return d

def wait_off(entity):
    return {'wait_template':"{{ is_state('"+entity+"','off') }}",'timeout':{'seconds':10},'continue_on_timeout':False}

def both_off():
    # Attempt BOTH shutdowns even when one network/device call fails.
    return [dict(action('switch.turn_off',CHARGER),continue_on_error=True),
            dict(action('switch.turn_off',INVERTER),continue_on_error=True)]

def start_timer():return action('timer.start',TIMER,duration='00:05:00')

def transition(mode,on_entity,off_entity):
    return {'conditions':[state(GUARD,mode)],'sequence':[
        state(TIMER,'idle'),state(PERMISSION,'on'),
        action('switch.turn_off',off_entity),wait_off(off_entity),{'delay':{'seconds':2}},
        state(PERMISSION,'on'),state(GUARD,mode),state(off_entity,'off'),state(on_entity,'off'),
        state(TIMER,'idle'),
        *([{'condition':'numeric_state','entity_id':'sensor.ant_bms_16_soc','below':'input_number.hausakku_ziel_soc'},
           {'condition':'numeric_state','entity_id':'sensor.ant_bms_16_soc','below':90},
           state('sensor.hausakku_betriebsstrategie','netzladen')] if mode=='netzladen' else []),
        start_timer(),action('switch.turn_on',on_entity),
        {'wait_template':"{{ is_state('"+on_entity+"','on') }}",'timeout':{'seconds':30},'continue_on_timeout':False},
    ]}

def automation_config():
    manually_disabled=neg(state(PERMISSION,'on'))
    any_not_off=any_of(neg(state(CHARGER,'off')),neg(state(INVERTER,'off')))
    off_confirmed=all_of(state(CHARGER,'off'),state(INVERTER,'off'))
    matched=any_of(
        all_of(state(GUARD,['versorgen','plan_fallback']),state(CHARGER,'off'),state(INVERTER,'on')),
        all_of(state(GUARD,'netzladen'),state(CHARGER,'on'),state(INVERTER,'off')),
        all_of(state(GUARD,'aufheben'),off_confirmed))
    serve=transition('versorgen',INVERTER,CHARGER)
    serve['conditions']=[state(GUARD,['versorgen','plan_fallback'])]
    # Recheck accepts the same safe fallback modes immediately before energizing.
    for item in serve['sequence']:
        if item.get('condition')=='state' and item.get('entity_id')==GUARD:item['state']=['versorgen','plan_fallback']
    return {
      'alias':'Hausakku Fahrplan Steuerung',
      'description':'Lokale Ausführung des gültigen Hausakku-Plans. Freigabe standardmäßig aus. 10/12%-Reserve, BMS-Heartbeat, MOS/Temperatur/Spannung, bestätigtes AUS und 2s Totzeit, 5min Schaltsperre. Schutzstopps und Ladeende dürfen sofort ausschalten. Kein Zugriff auf Car oder Scooter-Steuerung; bestehende externe WR-Sperre wird nur respektiert.',
      'mode':'restart','max_exceeded':'silent',
      'triggers':[
        {'trigger':'state','entity_id':[GUARD,PERMISSION], 'to':None,'id':'sollmodus'},
        {'trigger':'time_pattern','minutes':'/1','seconds':'0','id':'watchdog'},
        {'trigger':'timer.finished','target':{'entity_id':TIMER},'id':'schaltsperre_ende'},
        {'trigger':'homeassistant','event':'start','id':'start'},
      ],'conditions':[],
      'actions':[
        {'if':[manually_disabled],'then':[
            {'if':[state(OWNER,'on')],'then':both_off()+[
                {'if':[off_confirmed],'then':[action('input_boolean.turn_off',OWNER)]}]},
            {'stop':'Freigabe aus: nur zuvor übernommene Geräte sicher freigeben; keine manuellen Geräte übernehmen.'},
        ]},
        state(PERMISSION,'on'),action('input_boolean.turn_on',OWNER),
        {'if':[neg(state(GUARD,['netzladen','versorgen','plan_fallback','aufheben']))],
         'then':[{'if':[any_not_off],'then':both_off()+[start_timer()]},
                 {'stop':'Schutzstopp, Reserve, Ladeziel oder ungültige Daten: beide Geräte aus.'}]},
        # Leaving grid charge must stop it immediately, regardless of cooldown.
        {'if':[neg(state(GUARD,'netzladen')),state(CHARGER,'on')],
         'then':[action('switch.turn_off',CHARGER),wait_off(CHARGER),start_timer()]},
        {'if':[matched],'then':[{'stop':'Istzustand passt bereits; keine Schaltung und kein Timer-Neustart.'}]},
        state(TIMER,'idle'),
        {'choose':[
            transition('netzladen',CHARGER,INVERTER),serve,
            {'conditions':[state(GUARD,'aufheben')],'sequence':both_off()+[start_timer()]},
         ],'default':both_off()},
      ],
    }

HELPERS=[
    {'helper_type':'input_boolean','name':'Hausakku Regler uebernommen','config':{}},
    {'helper_type':'timer','name':'Hausakku Schaltsperre','config':{'duration':'00:05:00','restore':True}},
    {'helper_type':'threshold','name':'Hausakku Reserve Sperre','config':{'entity_id':'sensor.ant_bms_16_soc','lower':11,'hysteresis':.9}},
    {'helper_type':'threshold','name':'Hausakku Spannung niedrig','config':{'entity_id':'sensor.ant_bms_16_total_voltage','lower':49.05,'hysteresis':.14}},
    {'helper_type':'template','name':'Hausakku Regelmodus','config':{'next_step_id':'sensor','state':GUARD_TEMPLATE}},
]

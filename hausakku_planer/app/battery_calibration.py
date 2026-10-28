"""Measured charge/discharge efficiency from hourly HA energy counters (stdlib only).

Clean hours only, so PV and simultaneous flows cannot distort the ratio:
- charge: charger >= 0.8 kWh AC, no PV, WR off, no battery output;
- discharge: WR >= 0.3 kWh AC, no PV, charger off, no battery input.
battery_in/out_sum integrate BMS current x real voltage (DC). The planner's energy
unit is the battery-kWh sensor = remaining Ah x 51.2 V nominal, so both
efficiencies are converted to that scale with the mean BMS voltage of the used
hours. Charging happens at a higher voltage (~54 V) than discharging (~52 V), so
this conversion also captures the voltage-hysteresis loss: the nominal-scale
product is the true AC-to-AC round trip (25.10.2026: about 0.73).
"""
import math
from statistics import mean

# Roles of the hourly counters; the collector maps them to the configured entities.
ENTITIES=('charger','battery_in','battery_out','pv','wr')
NOMINAL_VOLTAGE=51.2


def calibrate(energy,voltage,min_charge_hours=10,min_discharge_hours=20):
    """energy: {key in ENTITIES: {hour start: kWh}}, voltage: {hour start: mean V}."""
    hours=set.intersection(*(set(energy.get(k,{})) for k in ENTITIES)) if all(energy.get(k) for k in ENTITIES) else set()
    rows={t:{k:energy[k][t] for k in ENTITIES} for t in hours}
    charge=[t for t,r in rows.items() if r['charger']>=.8 and r['pv']<.01 and r['wr']<.01 and r['battery_out']<.01]
    discharge=[t for t,r in rows.items() if r['wr']>=.3 and r['pv']<.01 and r['charger']<.01 and r['battery_in']<.01]
    result={'charge_hours':len(charge),'discharge_hours':len(discharge),'valid':False}
    if not charge or not discharge:
        result['reason']='keine sauberen Lade- oder Entladestunden';return result
    def scale(stamps):
        values=[voltage[t] for t in stamps if t in voltage and math.isfinite(voltage[t]) and 40<voltage[t]<60]
        return (mean(values) if values else NOMINAL_VOLTAGE)/NOMINAL_VOLTAGE
    real_charge=sum(rows[t]['battery_in'] for t in charge)/sum(rows[t]['charger'] for t in charge)
    out=sum(rows[t]['battery_out'] for t in discharge)
    real_discharge=sum(rows[t]['wr'] for t in discharge)/out if out>0 else 0.
    charge_eff=real_charge/scale(charge);discharge_eff=real_discharge*scale(discharge)
    result.update(charge_efficiency=charge_eff,discharge_efficiency=discharge_eff,roundtrip=charge_eff*discharge_eff,
                  real_voltage_charge=real_charge,real_voltage_discharge=real_discharge)
    if len(charge)<min_charge_hours or len(discharge)<min_discharge_hours:
        result['reason']=f'zu wenige saubere Stunden (nötig {min_charge_hours} Laden / {min_discharge_hours} Entladen)'
    elif not (.75<=charge_eff<=1 and .7<=discharge_eff<=.97 and .55<=charge_eff*discharge_eff<=.9):
        result['reason']='Messwert außerhalb plausibler Grenzen'
    else:
        result.update(valid=True,reason='gemessen')
    return result

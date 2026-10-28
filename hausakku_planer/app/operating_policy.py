"""Select normal service when intervention has no robust/practical justification.
Not a safety controller. BMS/HA protections remain required independently.
The minimum expected-gain threshold applies only to incremental grid charging.
"""
from dataclasses import replace
import math
from optimizer import _replay

def choose_operation(rows,params,candidate,config):
    pv_factor=float(config.get('normal_pv_factor',.65))
    load_factor=float(config.get('normal_load_factor',1.10))
    threshold=float(config.get('minimum_savings_eur',.10))
    if not 0<=pv_factor<=1 or not 1<=load_factor<=2 or not math.isfinite(threshold) or threshold<0:
        raise ValueError('Invalid normal-operation policy parameters')
    cautious=[replace(r,pv_kwh=r.pv_kwh*pv_factor,load_kwh=r.load_kwh*load_factor) for r in rows]
    cautious_baseline=_replay(cautious,['serve']*len(rows),params)
    # Check chronology, not just a daily kWh sum: tomorrow's sun cannot feed
    # tonight's house. Only energy scarcity is counted; inverter-power-limited
    # imports would be unavoidable even with a full battery.
    shortage=0.
    for f in cautious_baseline['intervals']:
        deliverable=min(f['load_kwh'],params.max_discharge_kw*f['duration_hours'])
        shortage+=max(0.,deliverable-f['served_ac_kwh'])
    sufficient=any(r.pv_kwh>0 for r in rows) and shortage<=1e-8
    saving=candidate['comparison']['total_savings_eur']
    baseline=candidate['comparison']['serve_baseline']
    no_charge=candidate['comparison']['optimized_no_charge']
    hold_gain=baseline['cost_eur']-no_charge['cost_eur']
    hold_objective_gain=baseline['objective_eur']-no_charge['objective_eur']
    charge_gain=candidate['comparison']['incremental_grid_charge_benefit_eur']
    uses_grid_charge=any(f['charger_ac_kwh']>1e-10 for f in candidate['intervals'])
    # A configured carry-over value (terminal_value_eur_kwh) prices energy that
    # is still in the battery when the known price horizon ends. Without it the
    # cost-only comparison ALWAYS rejects charging whose benefit lies on a later
    # day (horizon simply ends at the last known Tibber interval).
    terminal_value=float(getattr(params,'terminal_value_eur_kwh',0.) or 0.)
    charge_gain_gate=no_charge['objective_eur']-candidate['objective_eur']
    # The tolerance applies only to ADDITIONAL grid charging, not preservation
    # of existing/PV energy for price peaks. Compare against the best no-charge
    # plan; total savings may mostly come from holding and cannot justify charge.
    if sufficient and hold_objective_gain<=1e-9 and charge_gain_gate<=1e-9:
        reason='energy_sufficient'
    elif uses_grid_charge and charge_gain_gate>1e-9 and charge_gain_gate+1e-10>=threshold:
        reason='economic_optimization'
    elif hold_objective_gain>1e-9:
        reason='peak_hold'
    else:
        reason='gain_below_threshold'
    if reason=='economic_optimization':selected=candidate
    elif reason=='peak_hold':
        selected={**no_charge,'params':candidate['params'],
                  'comparison':{'serve_baseline':baseline,'optimized_no_charge':no_charge,
                      'hold_benefit_eur':hold_gain,'incremental_grid_charge_benefit_eur':0.,'total_savings_eur':hold_gain},
                  'approximation':candidate['approximation']}
    else:
        # All comparison fields describe the SELECTED policy. Do not claim a
        # hypothetical optimization gain after deliberately choosing normal mode.
        selected={**baseline,'params':candidate['params'],
                  'comparison':{'serve_baseline':baseline,'optimized_no_charge':baseline,
                      'hold_benefit_eur':0.,'incremental_grid_charge_benefit_eur':0.,'total_savings_eur':0.},
                  'approximation':candidate['approximation']}
    texts={
        'energy_sufficient':'Normalbetrieb: Akku und vorsichtige PV-Prognose decken die zeitlich lieferbare Last.',
        'gain_below_threshold':'Normalbetrieb: kein berechneter Aufhebevorteil; zusätzliche Netzladung erreicht die Mindest-Ersparnis nicht.',
        'peak_hold':'Spitzenbetrieb: vorhandene/PV-Energie für teure Stunden aufheben; keine zusätzliche Netzladung. Die Mindest-Ersparnis gilt nur für Netzladung.',
        'economic_optimization':'Optimierung: zusätzliche Netzladung hat gegenüber reinem Aufheben ausreichend berechneten Mehrwert.',
    }
    selected['comparison']['objective_savings_eur']=baseline['objective_eur']-selected['objective_eur']
    selected['comparison']['estimated_carryover_benefit_eur']=selected.get('carryover_value_eur',0.)-baseline.get('carryover_value_eur',0.)
    return {'plan':selected,'reason_code':reason,'reason':texts[reason],
            'carryover_curve_active':bool(params.terminal_value_curve),
            'candidate_savings_eur':saving,'minimum_savings_eur':threshold,
            'candidate_incremental_grid_charge_benefit_eur':charge_gain,
            'terminal_value_eur_kwh':terminal_value,
            'candidate_incremental_grid_charge_objective_eur':charge_gain_gate,
            'normal_pv_factor':pv_factor,'normal_load_factor':load_factor,
            'cautious_energy_shortfall_ac_kwh':shortage,
            'normal_operation':reason in ('energy_sufficient','gain_below_threshold')}

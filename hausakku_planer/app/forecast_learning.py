"""Conservative application of evaluated models; operational baseline always works.
Candidates are not enabled merely because a model file exists. Both independent
validation/test promotion and a fresh, causally valid training cutoff are required.
No HA service calls are made here; yearly refresh is read-only via annual_data.
"""
import copy,json,math,hashlib
from contextlib import redirect_stdout
from datetime import datetime,timedelta
from io import StringIO
from pathlib import Path
from forecast import TZ
from forecast_models import evaluate_models,predict_load,predict_pv


def apply_learning(data,snapshot,artifact):
    out=copy.deepcopy(data)
    calibration=out['pv_calibration']
    base_factor=calibration['factor'] if calibration['pairs']>=3 else 1.
    calibration['applied_factor']=base_factor
    meta={'load':'median28','pv':'ratio28','applied':{'load':False,'pv':False},'warnings':[],
          'backtest':artifact.get('backtest',{}) if artifact else {},
          'coverage':artifact.get('coverage',{}) if artifact else {},'as_of':artifact.get('as_of') if artifact else None,
          'artifact_id':artifact.get('artifact_id') if artifact else None}
    if artifact is None:
        meta['warnings'].append('no_artifact');return out,meta
    issue=datetime.fromisoformat(snapshot['collected_at']).astimezone(TZ)
    as_of=datetime.fromisoformat(artifact['as_of']).astimezone(TZ)
    boundary=datetime.fromisoformat(artifact['trained_before']).astimezone(TZ)
    if as_of.timestamp()>issue.timestamp():
        meta['warnings'].append('future_artifact');return out,meta
    if boundary!=issue.replace(hour=0,minute=0,second=0,microsecond=0):
        meta['warnings'].append('stale_training_cutoff');return out,meta
    if not artifact['load']['is_baseline'] and artifact['backtest']['load']['promoted']:
        try:
            proposed=[predict_load(artifact,r['start'])*(r['end'].timestamp()-r['start'].timestamp())/3600 for r in out['intervals']]
            if any(not math.isfinite(v) or v<0 for v in proposed):raise ValueError('Invalid load predictions')
            for r,v in zip(out['intervals'],proposed):r['load_kwh']=v
            meta['load']=artifact['selected_model']['load'];meta['applied']['load']=True
        except (KeyError,ValueError,TypeError,OverflowError):meta['warnings'].append('load_candidate_rejected')
    if not artifact['pv']['is_baseline'] and artifact['backtest']['pv']['promoted']:
        try:
            tomorrow=(issue.date()+timedelta(days=1)).isoformat()
            factor=predict_pv(artifact,1.,tomorrow,issued_at=issue)
            if not .1<=factor<=10 or not .1<=base_factor<=10:raise ValueError('PV calibration outside safety envelope')
            ratio=factor/base_factor
            proposed=[r['pv_kwh']*ratio for r in out['intervals']]
            totals={d:v*ratio for d,v in out['pv_totals_corrected_kwh'].items()}
            if any(not math.isfinite(v) or v<0 for v in [*proposed,*totals.values()]):raise ValueError('Invalid PV predictions')
            for r,v in zip(out['intervals'],proposed):r['pv_kwh']=v
            out['pv_totals_corrected_kwh']=totals;calibration['applied_factor']=factor
            meta['pv']=artifact['selected_model']['pv'];meta['applied']['pv']=True
        except (KeyError,ValueError,TypeError,OverflowError):meta['warnings'].append('pv_candidate_rejected')
    return out,meta


def public_model_summary(meta):
    applied=meta.get('applied',{})
    if not any(applied.values()):
        text='Prognose-Lernen: bisheriges Verfahren beibehalten'
        if 'future_artifact' in meta.get('warnings',[]):text+=' (Modell zeitlich nicht zulässig)'
        elif 'stale_training_cutoff' in meta.get('warnings',[]):text+=' (Trainingsdaten nicht aktuell)'
        elif 'no_artifact' in meta.get('warnings',[]):text+=' (kein geprüftes Modell verfügbar)'
        elif any('insufficient' in meta.get('backtest',{}).get(k,{}).get('reason','') for k in ('load','pv')):
            text+=' (noch zu wenige unabhängige Prüftage)'
        else:text+=' (Alternativen ohne ausreichenden nachgewiesenen Vorteil)'
    else:text='Prognose-Lernen: geprüfte Auswahl'
    load=meta.get('operational_load') or meta.get('load','median28')
    return text+f"; Verbrauch {load}, PV {meta.get('pv','ratio28')}."


def snapshot_observations(snapshot):
    """Current 28-day fallback actuals; no missing PV or load filled with zero."""
    from collector import normalize_statistics,energy_map
    ENERGY=energy_map()
    now=datetime.fromisoformat(snapshot['planning_start']).astimezone(TZ)
    cutoff=now.replace(hour=0,minute=0,second=0,microsecond=0)
    values={}
    for row in snapshot.get('balances',[]):
        required=('grid','wr','charger','export','ev')
        if not all(row.get(k) is not None for k in required):continue
        value=row['grid']+row['wr']-row['charger']-row['export']-row['ev']
        if not math.isfinite(value) or value<-.15:continue
        values.setdefault(float(row['start']),{'load_kwh':None,'pv_kwh':None})['load_kwh']=max(0.,value)
    raw=snapshot.get('raw',{}).get('energy')
    if raw is not None:
        data=normalize_statistics(raw)
        for t,value in data.get(ENERGY['pv'],{}).items():
            values.setdefault(t,{'load_kwh':None,'pv_kwh':None})['pv_kwh']=value
    return {'cutoff':cutoff.isoformat(),'hours':[{'start':t,**v} for t,v in sorted(values.items()) if t+3600<=cutoff.timestamp()]}


async def refresh_learning(snapshot,root):
    """Refresh recent observations, reuse frozen calendar chunks, fit causal models.
    Caller handles network/model errors by keeping the operational baseline.
    stdout from the collector is captured to keep Qwen's input a short report.
    """
    from annual_data import collect,save
    issue=datetime.fromisoformat(snapshot['collected_at']).astimezone(TZ)
    root=Path(root)
    with redirect_stdout(StringIO()):
        dataset=await collect(root,now=issue,require_disabled=False)
    artifact=evaluate_models(dataset,issue)
    artifact['artifact_id']=hashlib.sha256(json.dumps(artifact,sort_keys=True,allow_nan=False).encode()).hexdigest()
    version=root/'models'/f"{artifact['artifact_id']}.json"
    if version.exists():
        if json.loads(version.read_text())!=artifact:raise ValueError('Immutable model version conflict')
    else:save(version,artifact)
    save(root/'model.json',artifact)
    save(root/'backtest.json',artifact['backtest'])
    return dataset,artifact

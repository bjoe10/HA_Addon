"""Immutable issued forecasts and later measured error. No HA or hardware access.
Calendar-day targets are scored only after complete local days, with UTC hour
coverage (23/25h across DST). Historical hindcasts belong to model backtests,
NOT this genuinely issued forecast ledger. Actual source is inferred RAW_PV
and balanced house load, not certified independent meters.
"""
import hashlib,json,math,sqlite3
from contextlib import contextmanager
from datetime import datetime,timedelta
from pathlib import Path
from forecast import TZ

@contextmanager
def database(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(path,timeout=20)
    try:
        con.execute('PRAGMA foreign_keys=ON')
        con.executescript('''
        CREATE TABLE IF NOT EXISTS issues (
          id TEXT PRIMARY KEY, issued_at TEXT NOT NULL,
          source_collected_at TEXT NOT NULL, metadata TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS targets (
          issue_id TEXT NOT NULL REFERENCES issues(id), kind TEXT NOT NULL,
          start REAL NOT NULL, end REAL NOT NULL, prediction REAL NOT NULL,
          baseline REAL, model TEXT NOT NULL,
          PRIMARY KEY(issue_id,kind,start));
        CREATE TABLE IF NOT EXISTS scores (
          issue_id TEXT NOT NULL, kind TEXT NOT NULL, start REAL NOT NULL,
          actual REAL NOT NULL, error REAL NOT NULL, abs_error REAL NOT NULL,
          baseline_abs_error REAL, evaluated_at TEXT NOT NULL,
          PRIMARY KEY(issue_id,kind,start),
          FOREIGN KEY(issue_id,kind,start) REFERENCES targets(issue_id,kind,start));
        ''')
        yield con
        con.commit()
    except BaseException:
        con.rollback();raise
    finally:con.close()

def aware(value):
    d=datetime.fromisoformat(value) if isinstance(value,str) else value
    if not isinstance(d,datetime) or d.tzinfo is None:raise ValueError('Timezone-aware forecast time required')
    return d.astimezone(TZ)

def number(x):
    f=float(x)
    if not math.isfinite(f) or f<0:raise ValueError('Finite nonnegative forecast/actual energy required')
    return f

def hourly_predictions(rows,issued_at):
    buckets={}
    for row in rows:
        start,end=aware(row['start']),aware(row['end'])
        a,b=start.timestamp(),end.timestamp()
        load,pv=number(row['load_kwh']),number(row['pv_kwh'])
        if b<=a:raise ValueError('Forecast end must follow start')
        if a<issued_at.timestamp():continue
        # Quarter-hour/partial intervals must never be silently moved across hours.
        hour=math.floor(a/3600)*3600
        if b>hour+3600+1e-6:raise ValueError('Forecast interval crosses a UTC hour')
        buckets.setdefault(hour,[]).append((a,b,load,pv))
    out={}
    for hour,parts in buckets.items():
        parts.sort();cursor=hour
        valid=True
        for a,b,load,pv in parts:
            if abs(a-cursor)>1e-6:valid=False;break
            cursor=b
        if valid and abs(cursor-(hour+3600))<1e-6:
            out[hour]={'load_hour':math.fsum(x[2] for x in parts),'pv_hour':math.fsum(x[3] for x in parts)}
    return out

def archive_forecast(path,plan,snapshot):
    issued=aware(plan['created_at']);collected=aware(snapshot['collected_at'])
    if collected.timestamp()>issued.timestamp()+1:raise ValueError('Source collected after forecast issuance')
    central=hourly_predictions(plan['plan']['intervals'],issued)
    baseline_info=plan.get('forecast_baseline',{})
    baseline=hourly_predictions(baseline_info.get('intervals',[]),issued)
    model=plan.get('forecast_model',{})
    meta={'source_collected_at':collected.isoformat(),'model':model,
          'observation_source':'HA balanced house AC / inferred RAW_PV DC',
          'ev_source':snapshot.get('ev_source','legacy_unspecified'),
          'publication_verified':bool(plan.get('publication',{}).get('verified'))}
    targets=[]
    for start,values in sorted(central.items()):
        for kind,value in values.items():
            label=model.get('load' if kind=='load_hour' else 'pv','baseline')
            if not isinstance(label,str):label=json.dumps(label,sort_keys=True)
            targets.append((kind,start,start+3600,value,baseline.get(start,{}).get(kind),label))
    for day,value in sorted(plan['inputs'].get('pv_totals_corrected_kwh',{}).items()):
        start=aware(datetime.fromisoformat(day).replace(tzinfo=TZ));end=start+timedelta(days=1)
        # Today's remaining-energy forecast is not a full-day forecast.
        if start.timestamp()<issued.timestamp():continue
        b=baseline_info.get('pv_totals_corrected_kwh',{}).get(day)
        label=model.get('pv','baseline')
        if not isinstance(label,str):label=json.dumps(label,sort_keys=True)
        targets.append(('pv_day',start.timestamp(),end.timestamp(),number(value),number(b) if b is not None else None,label))
    canonical=json.dumps({'issued_at':issued.isoformat(),'metadata':meta,'targets':targets},sort_keys=True,allow_nan=False)
    issue_id=hashlib.sha256(canonical.encode()).hexdigest()
    with database(path) as con:
        con.execute('INSERT OR IGNORE INTO issues VALUES (?,?,?,?)',(issue_id,issued.isoformat(),collected.isoformat(),json.dumps(meta,sort_keys=True,allow_nan=False)))
        con.executemany('INSERT OR IGNORE INTO targets VALUES (?,?,?,?,?,?,?)',[(issue_id,*t) for t in targets])
    return issue_id

def score_forecasts(path,dataset,as_of):
    as_of=aware(as_of)
    midnight=as_of.replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    cutoff=min(midnight,aware(dataset['cutoff']).timestamp()) if dataset.get('cutoff') else midnight
    actual={}
    for row in dataset.get('hours',[]):
        stamp=float(row['start'])
        if not math.isfinite(stamp) or stamp%3600:raise ValueError('Actual must have aligned UTC hourly timestamp')
        vals={key:number(row[key]) if row.get(key) is not None else None for key in ('load_kwh','pv_kwh')}
        if stamp in actual and actual[stamp]!=vals:raise ValueError('Conflicting duplicate observation')
        actual[stamp]=vals
    added=0
    with database(path) as con:
        pending=con.execute('''SELECT t.issue_id,t.kind,t.start,t.end,t.prediction,t.baseline
            FROM targets t LEFT JOIN scores s ON s.issue_id=t.issue_id AND s.kind=t.kind AND s.start=t.start
            WHERE s.issue_id IS NULL AND t.end <= ?''',(cutoff,)).fetchall()
        for issue,kind,start,end,prediction,baseline in pending:
            key='load_kwh' if kind=='load_hour' else 'pv_kwh'
            stamps=range(int(start),int(end),3600)
            values=[actual.get(t,{}).get(key) for t in stamps]
            if not values or any(v is None for v in values):continue
            observed=math.fsum(values);error=prediction-observed
            base_error=abs(baseline-observed) if baseline is not None else None
            con.execute('INSERT INTO scores VALUES (?,?,?,?,?,?,?,?)',(issue,kind,start,observed,error,abs(error),base_error,as_of.isoformat()));added+=1
    return {'new_scores':added,'cutoff':datetime.fromtimestamp(cutoff,TZ).isoformat()}

def audit_summary(path):
    with database(path) as con:
        issues=con.execute('SELECT COUNT(*) FROM issues').fetchone()[0]
        targets=con.execute('SELECT COUNT(*) FROM targets').fetchone()[0]
        scored=con.execute('SELECT COUNT(*) FROM scores').fetchone()[0]
        metrics={}
        for kind,n,mae,bias,base,paired in con.execute('''SELECT kind,COUNT(*),AVG(abs_error),AVG(error),AVG(baseline_abs_error),COUNT(baseline_abs_error) FROM scores GROUP BY kind'''):
            metrics[kind]={'count':n,'mae_kwh':mae,'bias_kwh':bias,'baseline_mae_kwh':base,'paired_baseline_count':paired}
        distinct=con.execute('SELECT COUNT(DISTINCT start) FROM scores WHERE kind="pv_day"').fetchone()[0]
    return {'issued_forecasts':issues,'targets':targets,'scored_targets':scored,'pending_targets':targets-scored,
            'distinct_scored_pv_days':distinct,'metrics':metrics,
            'interpretation':'Recorded forecast errors, not measured money savings; baseline comparisons require paired rows.'}

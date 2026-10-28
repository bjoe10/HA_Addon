#!/usr/bin/env python3
"""Fill a data directory with a demo plan (shifted to 'now') and sample runs, for UI development.

Usage: tools/demo_data.py <data-dir> [--settings legacy]
Computes a plan from the test fixture, then shifts every timestamp by whole days into the present.
"""
import json, re, sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(ROOT.parent/'app')]
TZ=ZoneInfo('Europe/Berlin')
ISO=re.compile(r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d')

def shift(o,delta):
    if isinstance(o,dict):return {k:shift(v,delta) for k,v in o.items()}
    if isinstance(o,list):return [shift(v,delta) for v in o]
    if isinstance(o,str) and ISO.match(o) and len(o)>=19:
        try:return (datetime.fromisoformat(o)+delta).astimezone(TZ).isoformat()
        except ValueError:return o
    return o

def main(target):
    import os
    os.environ['HAUSAKKU_SETTINGS']=str(ROOT/'tests/fixtures/settings_legacy.json')
    from planner import compute_plan
    fixture=json.loads((ROOT/'tests/fixtures/test_fixture_snapshot.json').read_text())
    plan=compute_plan(fixture,json.loads((ROOT/'tests/fixtures/config_legacy.json').read_text()))
    first=datetime.fromisoformat(plan['plan']['intervals'][0]['start'])
    now=datetime.now(TZ).replace(second=0,microsecond=0)
    # Whole days only, so PV and price shapes keep their real time of day; the plan then started up to a day ago.
    delta=timedelta(days=(now-first).days)
    plan=shift(json.loads(json.dumps(plan,default=str)),delta)
    state=Path(target)/'state';state.mkdir(parents=True,exist_ok=True)
    (state/'plan.json').write_text(json.dumps(plan,indent=2))
    runs=[]
    for k,(kind,ok,msg) in enumerate([('replan',True,''),('replan',True,''),('main',True,''),('replan',False,'Home Assistant nicht erreichbar (ClientError)'),('replan',True,'')]):
        t=now-timedelta(hours=k+1)
        runs.append({'time':t.isoformat(),'kind':kind,'trigger':'zeit','mode':'observe','ok':ok,'seconds':14.2+k,
                     'stdout':'Hausakku-Planer\n(Demo-Ausgabe)' if ok else '','stderr':'' if ok else '[CRON_FAILURE] Abbruch bei: Datenabruf aus HA','message':msg})
    (state/'runs.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in reversed(runs))+'\n')
    print('Demo data written to',state)

if __name__=='__main__':main(sys.argv[1])

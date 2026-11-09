"""Keep the add-on's data from growing without bound. Runs once a day from a main run.

What is kept (everything else that piles up is removed):
- raw snapshots (state/snapshots): the last SNAPSHOT_DAYS days, for audits; state/snapshot.json is the current one.
- versioned model files (training/models, training/multiday_models): the newest KEEP_FILES; model.json is the current one.
- price, weather and radiation forecasts (multiday_audit.sqlite): every vintage for VINTAGE_DAYS, after that only the
  last vintage per target time (the realised price history the planner uses stays complete).
- archived multi-day forecasts: one per issue day while waiting to be scored (the evaluation counts one per day),
  none older than PENDING_DAYS; once scored only the outcome is kept, not the full plans.
- forecast audit (forecast_audit.sqlite): scores for SCORE_DAYS; unscored targets and empty issues for AUDIT_DAYS.
The databases are compacted (VACUUM) on Mondays when something was removed. Stdlib only.
"""
import json, sqlite3, time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ=ZoneInfo('Europe/Berlin')
SNAPSHOT_DAYS=14
KEEP_FILES=20
VINTAGE_DAYS=30
PENDING_DAYS=30
AUDIT_DAYS=90
SCORE_DAYS=365


def _tables(con):
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def prune_files(folder,keep_days=None,keep_newest=None,now=None,pattern='*.json'):
    folder=Path(folder)
    if not folder.exists():return 0
    files=sorted(folder.glob(pattern),key=lambda p:p.stat().st_mtime,reverse=True)
    now=now or time.time();removed=0
    for i,f in enumerate(files):
        old=keep_days is not None and now-f.stat().st_mtime>keep_days*86400
        surplus=keep_newest is not None and i>=keep_newest
        if old or surplus:f.unlink();removed+=1
    return removed


def prune_multiday(path,now=None):
    """Rows removed from the price/weather/radiation archive and the multi-day forecast issues."""
    path=Path(path)
    if not path.exists():return 0
    now=now or time.time();cutoff=now-VINTAGE_DAYS*86400;removed=0
    con=sqlite3.connect(path,timeout=20)
    try:
        tables=_tables(con)
        for table in ('prices','weather','radiation'):
            if table not in tables:continue
            removed+=con.execute(f'''DELETE FROM {table} WHERE target<? AND issued<(
                SELECT MAX(issued) FROM {table} AS newest WHERE newest.target={table}.target)''',(cutoff,)).rowcount
        if 'issues' in tables:
            removed+=con.execute('DELETE FROM issues WHERE outcome IS NULL AND issued<?',(now-PENDING_DAYS*86400,)).rowcount
            # One pending issue per local issue day: the latest (the evening main run) is the one the evaluation counts.
            pending=con.execute('SELECT id,issued FROM issues WHERE outcome IS NULL ORDER BY issued').fetchall()
            latest={}
            for key,issued in pending:latest[datetime.fromtimestamp(issued,TZ).date()]=key
            keep=set(latest.values())
            drop=[(key,) for key,_ in pending if key not in keep]
            if drop:con.executemany('DELETE FROM issues WHERE id=?',drop);removed+=len(drop)
            # Scored issues only need their outcome.
            removed+=con.execute("UPDATE issues SET payload='{}' WHERE outcome IS NOT NULL AND payload!='{}'").rowcount
        con.commit()
    finally:con.close()
    return removed


def prune_audit(path,now=None):
    """Scores older than SCORE_DAYS go; targets of issues older than AUDIT_DAYS go once they have no score
    (scores reference their targets); issues go when no target is left."""
    path=Path(path)
    if not path.exists():return 0
    now=now or datetime.now(TZ);removed=0
    con=sqlite3.connect(path,timeout=20)
    try:
        con.execute('PRAGMA foreign_keys=ON')
        tables=_tables(con)
        if 'scores' in tables:
            removed+=con.execute('DELETE FROM scores WHERE start<?',((now-timedelta(days=SCORE_DAYS)).timestamp(),)).rowcount
        if {'issues','targets'}<=tables:
            old=(now-timedelta(days=AUDIT_DAYS)).isoformat()
            scored='AND NOT EXISTS (SELECT 1 FROM scores s WHERE s.issue_id=targets.issue_id AND s.kind=targets.kind AND s.start=targets.start)' if 'scores' in tables else ''
            removed+=con.execute(f'DELETE FROM targets WHERE issue_id IN (SELECT id FROM issues WHERE issued_at<?) {scored}',(old,)).rowcount
            removed+=con.execute('DELETE FROM issues WHERE issued_at<? AND NOT EXISTS (SELECT 1 FROM targets t WHERE t.issue_id=issues.id)',(old,)).rowcount
        con.commit()
    finally:con.close()
    return removed


def vacuum(*paths):
    for p in paths:
        if Path(p).exists():
            con=sqlite3.connect(p,timeout=20)
            try:con.execute('VACUUM')
            finally:con.close()


def daily(base,now=None):
    """Clean up once per local day; returns a short summary or None when already done today."""
    base=Path(base);state=base/'state';now=now or datetime.now(TZ)
    marker=state/'housekeeping.json'
    try:last=json.loads(marker.read_text()).get('date')
    except (OSError,ValueError):last=None
    if last==now.date().isoformat():return None
    ts=now.timestamp()
    files=(prune_files(state/'snapshots',keep_days=SNAPSHOT_DAYS,now=ts)
           +prune_files(state/'training/models',keep_newest=KEEP_FILES)
           +prune_files(state/'training/multiday_models',keep_newest=KEEP_FILES))
    rows=prune_multiday(state/'multiday_audit.sqlite',ts)+prune_audit(state/'forecast_audit.sqlite',now)
    if rows and now.weekday()==0:vacuum(state/'multiday_audit.sqlite',state/'forecast_audit.sqlite')
    summary={'date':now.date().isoformat(),'files_removed':files,'rows_removed':rows}
    marker.write_text(json.dumps(summary))
    return summary

import json, os, sqlite3, tempfile, time, unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import housekeeping, multiday

TZ=ZoneInfo('Europe/Berlin')
NOW=datetime(2026,11,20,21,0,tzinfo=TZ)

class FileTests(unittest.TestCase):
    def test_old_snapshots_and_surplus_models_go(self):
        d=Path(tempfile.mkdtemp())
        for i in range(5):
            f=d/f'{i}.json';f.write_text('{}');os.utime(f,(time.time()-i*10*86400,)*2)
        self.assertEqual(housekeeping.prune_files(d,keep_days=14),3)          # 20, 30, 40 days old
        self.assertEqual(sorted(p.name for p in d.glob('*.json')),['0.json','1.json'])
        self.assertEqual(housekeeping.prune_files(d,keep_newest=1),1)
        self.assertEqual([p.name for p in d.glob('*.json')],['0.json'])
        self.assertEqual(housekeeping.prune_files(d/'missing',keep_days=1),0)

class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.path=Path(tempfile.mkdtemp())/'multiday_audit.sqlite'
        with multiday._db(self.path) as db:pass

    def rows(self,sql):
        con=sqlite3.connect(self.path)
        try:return con.execute(sql).fetchall()
        finally:con.close()

    def test_old_targets_keep_only_their_last_vintage_recent_ones_all(self):
        now=NOW.timestamp();old=now-40*86400;recent=now-5*86400
        con=sqlite3.connect(self.path)
        for target in (old,recent):
            for k in range(3):con.execute('INSERT INTO prices VALUES (?,?,?)',(target,target-86400+k*3600,.3+k/100))
        con.commit();con.close()
        housekeeping.prune_multiday(self.path,now)
        self.assertEqual(self.rows(f'SELECT price FROM prices WHERE target={old}'),[(.32,)])   # the last vintage
        self.assertEqual(len(self.rows(f'SELECT * FROM prices WHERE target={recent}')),3)

    def test_issues_one_pending_per_day_none_too_old_scored_without_plans(self):
        day=datetime(2026,11,18,14,15,tzinfo=TZ).timestamp()
        con=sqlite3.connect(self.path)
        con.executemany('INSERT INTO issues VALUES (?,?,?,?)',[
            ('a',day,'{"big":1}',None),('b',day+6*3600,'{"big":1}',None),          # same day: the evening one stays
            ('c',NOW.timestamp()-40*86400,'{"big":1}',None),                        # never scorable
            ('d',day-86400,'{"big":1}','{"x":1}')])                                 # scored
        con.commit();con.close()
        housekeeping.prune_multiday(self.path,NOW.timestamp())
        self.assertEqual(self.rows('SELECT id,payload FROM issues ORDER BY id'),[('b','{"big":1}'),('d','{}')])

    def test_audit_keeps_scored_targets_for_a_year_and_drops_old_unscored_ones(self):
        import forecast_audit
        path=self.path.parent/'forecast_audit.sqlite'
        t=lambda days:(NOW-timedelta(days=days)).timestamp()
        with forecast_audit.database(path) as con:
            for key,age in (('old',100),('ancient',500),('new',10)):
                con.execute('INSERT INTO issues VALUES (?,?,?,?)',(key,(NOW-timedelta(days=age)).isoformat(),NOW.isoformat(),'{}'))
            targets=[('old',t(99)),('old',t(98)),('ancient',t(499)),('new',t(9))]
            con.executemany("INSERT INTO targets VALUES (?,'load_hour',?,?,1.,NULL,'m')",[(k,s,s+3600) for k,s in targets])
            con.executemany("INSERT INTO scores VALUES (?,'load_hour',?,1.,0.,0.,NULL,?)",[(k,s,NOW.isoformat()) for k,s in (('old',t(99)),('ancient',t(499)),('new',t(9)))])
        housekeeping.prune_audit(path,NOW)
        con=sqlite3.connect(path)
        self.assertEqual(sorted(con.execute('SELECT id FROM issues').fetchall()),[('new',),('old',)])
        self.assertEqual(sorted(con.execute('SELECT issue_id,start FROM targets').fetchall()),[('new',t(9)),('old',t(99))])
        self.assertEqual(con.execute('SELECT COUNT(*) FROM scores').fetchone()[0],2)
        con.close()

class DailyTests(unittest.TestCase):
    def test_runs_once_per_day(self):
        base=Path(tempfile.mkdtemp());(base/'state').mkdir()
        self.assertEqual(housekeeping.daily(base,NOW)['date'],'2026-11-20')
        self.assertIsNone(housekeeping.daily(base,NOW+timedelta(hours=1)))
        self.assertIsNotNone(housekeeping.daily(base,NOW+timedelta(days=1)))

class RawCacheTests(unittest.TestCase):
    def test_unused_batches_and_their_manifest_entries_go_only_after_a_collect(self):
        import annual_data
        root=Path(tempfile.mkdtemp());raw=root/'raw';raw.mkdir()
        for n in ('ev_2026-11-01_a.json','ev_2026-11-02_b.json'):(raw/n).write_text('{}')
        (root/'manifest.json').write_text(json.dumps({'batches':{'ev_2026-11-01_a.json':{},'ev_2026-11-02_b.json':{}}}))
        annual_data.USED.clear()
        self.assertEqual(annual_data.prune_raw(root),0)                 # nothing collected: keep the cache
        annual_data.USED.add('ev_2026-11-01_a.json')
        self.assertEqual(annual_data.prune_raw(root),1)
        self.assertEqual([p.name for p in raw.glob('*.json')],['ev_2026-11-01_a.json'])
        self.assertEqual(list(json.loads((root/'manifest.json').read_text())['batches']),['ev_2026-11-01_a.json'])
        annual_data.USED.clear()

if __name__=='__main__':unittest.main()

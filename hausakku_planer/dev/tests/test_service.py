import asyncio, json, os, sys, tempfile, unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from aiohttp.test_utils import AioHTTPTestCase
os.environ['HAUSAKKU_NO_SCHEDULER']='1'
import paths, service, settings
TZ=ZoneInfo('Europe/Berlin')

class SchedulingTests(unittest.TestCase):
    def test_due_runs_main_and_hourly(self):
        t=lambda h,m:datetime(2026,10,27,h,m,tzinfo=TZ)
        self.assertEqual(service.due_runs(t(14,16),t(14,10)),['main'])
        self.assertEqual(service.due_runs(t(11,46),t(11,40)),['replan'])
        self.assertEqual(service.due_runs(t(20,16),t(20,14)),['main'])
        self.assertEqual(service.due_runs(t(11,50),t(11,46)),[])

    def test_missed_minutes_are_not_lost(self):
        t=lambda h,m:datetime(2026,10,27,h,m,tzinfo=TZ)
        self.assertEqual(service.due_runs(t(15,50),t(13,50)),['main'])
        self.assertEqual(service.due_runs(t(18,50),t(16,50)),['replan'])

    def test_observe_never_publishes(self):
        self.assertEqual(service.planner_args('main','observe'),[]);self.assertEqual(service.planner_args('replan','observe'),[])
        self.assertEqual(service.planner_args('main','publish'),['--publish']);self.assertEqual(service.planner_args('replan','control'),['--replan'])

class RunTests(unittest.TestCase):
    def setUp(self):
        self.old=paths.STATE;paths.STATE=__import__('pathlib').Path(tempfile.mkdtemp());settings.use(settings.load())
    def tearDown(self):paths.STATE=self.old;settings.use(None)

    def test_unconfigured_run_is_skipped_with_reason(self):
        settings.use({})
        r=asyncio.run(service.run_planner('main','observe'))
        self.assertTrue(r['skipped']);self.assertIn('Einrichtung unvollständig',r['message'])
        self.assertEqual(service.read_runs()[0]['skipped'],True)

    def test_run_is_logged_with_output(self):
        r=asyncio.run(service.run_planner('main','observe',command=[sys.executable,'-c','print("plan ok")']))
        self.assertTrue(r['ok']);self.assertIn('plan ok',r['stdout'])
        bad=asyncio.run(service.run_planner('replan','observe',command=[sys.executable,'-c','import sys;print("boom",file=sys.stderr);sys.exit(1)']))
        self.assertFalse(bad['ok']);self.assertEqual([x['ok'] for x in service.read_runs()],[False,True])

class ServiceTests(AioHTTPTestCase):
    async def get_application(self):
        settings.use({});return service.make_app()
    async def tearDownAsync(self):settings.use(None)

    async def test_index_status_and_runs(self):
        r=await self.client.get('/');self.assertEqual(r.status,200);self.assertIn('Hausakku',await r.text())
        s=await (await self.client.get('/api/status')).json()
        self.assertIn(s['mode'],('observe','publish','control'));self.assertTrue(s['missing']);self.assertIsNone(s['plan'])
        self.assertEqual(await (await self.client.get('/api/runs')).json(),[] if not (paths.STATE/'runs.jsonl').exists() else await (await self.client.get('/api/runs')).json())

if __name__=='__main__':unittest.main()

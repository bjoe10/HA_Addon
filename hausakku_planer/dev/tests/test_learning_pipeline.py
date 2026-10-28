"""Pipeline regression tests isolate disk and mock only HA/network boundaries."""
import copy,json,tempfile,unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock,patch
import planner
from forecast_audit import audit_summary

class LearningPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import asyncio
        asyncio.get_running_loop().slow_callback_duration=10
    def setup_files(self,root):
        config=json.loads((Path(__file__).parent/'fixtures/config_legacy.json').read_text());config['forecast_learning_enabled']=True
        snapshot=json.loads((Path(__file__).parent/'fixtures/test_fixture_snapshot.json').read_text())
        (root/'state').mkdir();(root/'config.json').write_text(json.dumps(config));(root/'state/snapshot.json').write_text(json.dumps(snapshot))
        return snapshot
    async def test_failed_learning_refresh_keeps_baseline_and_archives_without_leaking_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);snapshot=self.setup_files(root);stdout=StringIO()
            with patch.object(planner,'BASE',root),patch.object(planner,'collect',new_callable=AsyncMock,return_value=snapshot),patch.object(planner,'refresh_learning',new_callable=AsyncMock,side_effect=RuntimeError('SECRET_URL_MUST_NOT_PRINT')),redirect_stdout(stdout):
                await planner.run(Namespace(from_snapshot=False,publish=False))
            result=json.loads((root/'state/plan.json').read_text())
            self.assertEqual(result['forecast_learning_error'],'RuntimeError')
            self.assertEqual(result['forecast_model']['load'],'median28')
            self.assertEqual(audit_summary(root/'state/forecast_audit.sqlite')['issued_forecasts'],1)
            self.assertNotIn('SECRET_URL_MUST_NOT_PRINT',stdout.getvalue())
            self.assertIn('Prognose-Lernen',stdout.getvalue())
    async def test_saved_snapshot_replay_does_not_create_genuine_issued_forecast(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);snapshot=self.setup_files(root)
            with patch.object(planner,'BASE',root),patch.object(planner,'collect',new_callable=AsyncMock) as collect,patch.object(planner,'refresh_learning',new_callable=AsyncMock) as refresh,redirect_stdout(StringIO()):
                await planner.run(Namespace(from_snapshot=True,publish=False))
            collect.assert_not_called();refresh.assert_not_called()
            self.assertFalse((root/'state/forecast_audit.sqlite').exists())
            result=json.loads((root/'state/plan.json').read_text());self.assertEqual(result['forecast_audit']['status'],'snapshot_replay_not_archived')
if __name__=='__main__':unittest.main()

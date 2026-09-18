import tempfile
import unittest
import unittest.mock
from pathlib import Path

from experiment_supervisor import ExperimentSupervisor


class ExperimentSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'docs' / 'experiment_validation').mkdir(parents=True)
        self.service = ExperimentSupervisor(self.root, dry_run=True)

    def test_completed_days_come_only_from_explicit_markers(self):
        progress = self.root / 'docs' / 'experiment_validation' / 'PROGRESS.md'
        progress.write_text('DAY_1_COMPLETE\nDAY 3 COMPLETE\nDAY_99_COMPLETE\n')
        self.assertEqual(self.service.completed_days(), (2, [1, 3]))

    def test_dry_run_writes_an_html_report_without_telegram(self):
        self.service.tick(report_only=True)
        reports = list((self.root / '.experiment-control' / 'reports').glob('*.html'))
        self.assertEqual(len(reports), 1)
        document = reports[0].read_text()
        self.assertIn('Quant 2주 전략 검증 보고', document)
        self.assertIn('/experiment stop', document)

    def test_next_validation_prompt_is_one_incomplete_day(self):
        (self.root / 'docs' / 'experiment_validation' / 'PROGRESS.md').write_text('DAY_1_COMPLETE\n')
        state = self.service.state()
        task = self.service.activity_prompt(state)
        self.assertIn('Day 2', task)
        self.assertEqual(state['phase'], 'validation')

    def test_launch_agent_skipped_when_no_headroom(self):
        # The Telegram queue and the scheduler's nightly tuning loop run independently on the
        # same VM -- this supervisor must not launch a 3rd heavy Codex process on top of them.
        service = ExperimentSupervisor(self.root, dry_run=False)
        service.has_headroom = lambda: False
        launched = []
        service.launch_agent = lambda state: launched.append(state)
        service.tick()
        self.assertEqual(launched, [])
        self.assertIn('여유 리소스 부족', service.state()['current_activity'])

    def test_launch_agent_proceeds_when_headroom_available(self):
        service = ExperimentSupervisor(self.root, dry_run=False)
        service.has_headroom = lambda: True
        launched = []
        service.launch_agent = lambda state: launched.append(state)
        service.tick()
        self.assertEqual(len(launched), 1)

    def test_has_headroom_blocks_on_high_load(self):
        self.service.max_load_per_cpu = 1.0
        with unittest.mock.patch('experiment_supervisor.os.getloadavg', return_value=(9.0, 9.0, 9.0)), \
             unittest.mock.patch('experiment_supervisor.os.cpu_count', return_value=2):
            self.assertFalse(self.service.has_headroom())

    def test_has_headroom_true_under_normal_conditions(self):
        with unittest.mock.patch('experiment_supervisor.os.getloadavg', return_value=(0.1, 0.1, 0.1)), \
             unittest.mock.patch('experiment_supervisor.os.cpu_count', return_value=2), \
             unittest.mock.patch.object(self.service, 'available_memory_mb', return_value=8000):
            self.assertTrue(self.service.has_headroom())

import tempfile
import unittest
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

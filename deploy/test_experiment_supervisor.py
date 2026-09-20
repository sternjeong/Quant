import tempfile
import unittest
import unittest.mock
from pathlib import Path

from experiment_supervisor import LIMIT, ExperimentSupervisor


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
        # same VM -- this supervisor must not launch a 3rd heavy Claude process on top of them.
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

    def test_claude_binary_defaults_to_standard_install_path(self):
        self.assertEqual(str(self.service.claude), '/usr/local/bin/claude')

    def test_claude_config_dir_defaults_under_root(self):
        self.assertEqual(self.service.claude_config_dir, str(self.root / '.claude'))

    def test_launch_agent_invokes_claude_cli_not_codex(self):
        # 2026-09-19: Codex에서 Claude CLI로 전환 -- 명령이 실제로 claude 바이너리를 부르고,
        # 프롬프트는 stdin으로 전달되며(claude -p는 위치 인자 없이 stdin에서 읽음), 세션을
        # 남기지 않고(--no-session-persistence) 확인 없이 진행하는지(--dangerously-skip-permissions)
        # 확인한다.
        service = ExperimentSupervisor(self.root, dry_run=False)
        service.claude = Path('/usr/local/bin/claude')
        with unittest.mock.patch.object(Path, 'exists', return_value=True), \
             unittest.mock.patch('experiment_supervisor.subprocess.Popen') as popen:
            mock_child = unittest.mock.MagicMock()
            mock_child.pid = 4242
            mock_child.stdin = unittest.mock.MagicMock()
            popen.return_value = mock_child

            state = service.state()
            service.launch_agent(state)

            cmd = popen.call_args.args[0]
            self.assertIn(str(service.claude), cmd)
            self.assertIn('-p', cmd)
            self.assertIn('--dangerously-skip-permissions', cmd)
            self.assertIn('--no-session-persistence', cmd)
            self.assertNotIn('exec', cmd)  # codex 전용 서브커맨드가 남아있지 않아야 함
            env = popen.call_args.kwargs['env']
            self.assertEqual(env.get('CLAUDE_CONFIG_DIR'), service.claude_config_dir)
            self.assertEqual(state['agent_pid'], 4242)

    def test_launch_agent_records_error_when_claude_binary_missing(self):
        service = ExperimentSupervisor(self.root, dry_run=False)
        service.claude = self.root / 'no-such-claude-binary'
        state = service.state()
        service.launch_agent(state)
        self.assertIn('Claude CLI가 없습니다', state['last_error'])

    def test_limit_regex_catches_claude_specific_phrasing(self):
        self.assertRegex('Error: hit your limit for this period', LIMIT)
        self.assertRegex('you are out of extra usage', LIMIT)
        self.assertRegex('rate limit exceeded', LIMIT)

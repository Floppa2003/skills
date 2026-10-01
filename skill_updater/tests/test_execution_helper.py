from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'skills/executing-plans/scripts/task-done'
WORKSPACE = ROOT / 'skills/subagent-driven-development/scripts/sdd-workspace'


class TaskCompletionTests(unittest.TestCase):
    def test_successful_silent_checks_and_failed_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                            'commit', '-q', '--allow-empty', '-m', 'baseline'], cwd=root, check=True)
            plan = root / 'plan.md'
            plan.write_text('# Control plan\n', encoding='utf-8')
            workspace = Path(subprocess.check_output(['bash', str(WORKSPACE), str(plan)], cwd=root, text=True).strip())
            for number, command in enumerate(('true', "printf ' \\n'", "printf 'PASS\\n'", 'exit 42'), 1):
                with self.subTest(command=command):
                    result = subprocess.run(['bash', str(SCRIPT), str(plan), str(number), 'HEAD',
                                             '--', 'bash', '-c', command], cwd=root, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 42 if number == 4 else 0, result.stderr)
                    ledger = (workspace / 'progress.md').read_text()
                    self.assertEqual(f'Task {number}: complete' in ledger, number != 4)
            self.assertIn('exit 0; no output', ledger)


if __name__ == '__main__':
    unittest.main()

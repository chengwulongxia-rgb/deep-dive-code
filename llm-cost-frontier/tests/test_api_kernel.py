"""Real IPC kernel / independent watchdog checks, never API inference."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def load_runner():
    path = ROOT / 'run_drcd_api_notebook.py'
    if not path.exists(): return None
    spec = importlib.util.spec_from_file_location('api_runner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def live(pid):
    p = Path(f'/proc/{pid}/stat')
    return p.exists() and p.read_text().split(') ')[1].split()[0] != 'Z'

class KernelTests(unittest.TestCase):
    def test_replay_real_kernel_no_http_no_key_read(self):
        runner = load_runner()
        self.assertIsNotNone(runner, 'API IPC runner missing')
        with tempfile.TemporaryDirectory() as tmp:
            report = runner.run_notebook('replay', output=Path(tmp) / 'replayed.ipynb')
            self.assertTrue(report['kernel_stopped'])
            self.assertTrue(report['all_cells_executed'])
            self.assertTrue(report['replay_http_and_key_blocked'])
            self.assertFalse(live(report['kernel_pid']))

    def test_notebook_output_write_failure_still_stops_real_kernel(self):
        runner = load_runner()
        self.assertIsNotNone(runner, 'API IPC runner missing')
        managers = []
        original = runner.KernelManager
        def manager(*args, **kwargs):
            km = original(*args, **kwargs); managers.append(km); return km
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, 'KernelManager', manager):
            with self.assertRaises(IsADirectoryError):
                runner.run_notebook('replay', output=Path(tmp))
        self.assertEqual(len(managers), 1)
        self.assertFalse(managers[0].has_kernel)

    def test_final_cell_callback_disarms_only_after_successful_body(self):
        import ast
        from types import SimpleNamespace
        nb = json.loads((ROOT / 'drcd_api.ipynb').read_text())
        source = ''.join(next(c for c in nb['cells'] if c['id'] == 'execution')['source'])
        node = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == 'api_post_cell')
        ns = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<callback>', 'exec'), ns)
        events = []
        ns.update(GUARD=SimpleNamespace(abort=lambda code: events.append('abort'), finish=lambda: events.append('finish')),
            get_ipython=lambda: SimpleNamespace(events=SimpleNamespace(unregister=lambda *a: None)))
        successful = SimpleNamespace(error_in_exec=None, error_before_exec=None)
        ns['api_post_cell'](successful)
        self.assertEqual(events, [])
        ns['guard_ready_to_finish'] = True
        ns['api_post_cell'](SimpleNamespace(error_in_exec=RuntimeError('body failed'), error_before_exec=None))
        self.assertEqual(events, ['abort'])
        ns['api_post_cell'](successful)
        self.assertEqual(events, ['abort', 'finish'])

    def test_native_watchdog_kills_blocking_request_pending_survives(self):
        nb = json.loads((ROOT / 'drcd_api.ipynb').read_text())
        pure = '\n'.join(''.join(c['source']) for c in nb['cells'] if 'api-pure' in c.get('metadata', {}).get('tags', []))
        guard = '\n'.join(''.join(c['source']) for c in nb['cells'] if 'api-guard' in c.get('metadata', {}).get('tags', []))
        self.assertTrue(guard, 'native independent watchdog missing')
        with tempfile.TemporaryDirectory() as tmp:
            program = pure + '\n' + guard + '''
import signal
out = Path(sys.argv[1])
with BudgetLedger(out / 'budget.json') as ledger:
    token = ledger.reserve(MODELS[0], 100, {'run_id': 'offline_guard'})
    g = ResourceGuard(out, overall_seconds=5)
    g.request(.3, {'id': 'offline_blocked_io'})
    child = subprocess.Popen([sys.executable, '-c', 'import signal; signal.pause()'])
    (out / 'pids.json').write_text(json.dumps([os.getpid(), child.pid, g.proc.pid]))
    signal.pause()
'''
            worker = subprocess.Popen([sys.executable, '-c', program, tmp], start_new_session=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                stdout, stderr = worker.communicate(timeout=10)
                self.assertEqual(worker.returncode, -signal.SIGKILL, stderr)
                ids = json.loads((Path(tmp) / 'pids.json').read_text())
                for _ in range(100):
                    if not any(live(pid) for pid in ids): break
                    time.sleep(.02)
                self.assertFalse(any(live(pid) for pid in ids))
                ledger = json.loads((Path(tmp) / 'budget.json').read_text())
                self.assertEqual(next(iter(ledger['entries'].values()))['state'], 'pending')
                failure = json.loads((Path(tmp) / 'failure.json').read_text())
                self.assertEqual(failure['status'], 'partial')
                self.assertIn('request', failure['reason'])
            finally:
                if worker.poll() is None:
                    os.killpg(worker.pid, signal.SIGKILL); worker.wait()
                worker.communicate(timeout=3)

if __name__ == '__main__': unittest.main()

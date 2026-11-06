"""Real dedicated-process kill tests; never signal the test runner group."""
import json, os, signal, subprocess, sys, tempfile, time, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def guard_source():
    nb = json.loads((ROOT / 'drcd_cpu.ipynb').read_text())
    source = '\n'.join(''.join(c['source']) for c in nb['cells'] if 'guard' in c.get('metadata', {}).get('tags', []))
    assert source, 'Notebook lacks independent process ResourceGuard for blocked IO'
    return source

def live(pid):
    p = Path(f'/proc/{pid}/stat')
    return p.exists() and p.read_text().split(') ')[1].split()[0] != 'Z'

def persist_evidence(out, mode):
    if not os.environ.get('DRCD_GUARD_EVIDENCE'):
        return
    dest = Path(os.environ['DRCD_GUARD_EVIDENCE']) / mode
    dest.mkdir(parents=True, exist_ok=True)
    for p in out.glob('*.json'):
        if p.is_file(): (dest / p.name).write_bytes(p.read_bytes())

class GuardTests(unittest.TestCase):
    def worker(self, mode):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            program = guard_source() + '\n' + '''
import signal
out = Path(sys.argv[1]); mode = sys.argv[2]
g = ResourceGuard(out, overall_seconds=(.7 if mode in {'overall','evidencewrite'} else 8))
if mode == 'evidencewrite': (out / 'watchdog.json').mkdir()
child = subprocess.Popen([sys.executable, '-c', 'import signal; signal.pause()'])
(out / 'pids.json').write_text(json.dumps([os.getpid(), child.pid, g.proc.pid]))
if mode == 'inference': g.inference(.7)
if mode == 'request': g.request(.7, {'id': 'blocked'})
if mode == 'normal':
    child.terminate(); child.wait(); g.finish(); time.sleep(1); sys.exit(0)
if mode == 'parentdeath': os._exit(23)
if mode == 'exception': g.abort('dummy cell exception')
signal.pause()
'''
            p = subprocess.Popen([sys.executable, '-c', program, tmp, mode], start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                stdout, stderr = p.communicate(timeout=12)
                self.assertTrue((out / 'pids.json').exists(), stderr)
                ids = json.loads((out / 'pids.json').read_text())
                for _ in range(100):
                    if not any(live(i) for i in ids): break
                    time.sleep(.02)
                self.assertFalse(any(live(i) for i in ids), ids)
                (out / 'test-verification.json').write_text(json.dumps({'returncode':p.returncode, 'no_live_worker_child_watchdog':True, 'worker_stderr':stderr}))
                persist_evidence(out, mode)
                if mode == 'evidencewrite':
                    self.assertEqual(p.returncode, -signal.SIGKILL)
                    self.assertTrue((out / 'failure.json').exists())
                    return
                evidence = json.loads((out / 'watchdog.json').read_text())
                if mode == 'normal':
                    self.assertEqual(p.returncode, 0, stderr)
                    self.assertEqual(evidence['status'], 'complete')
                    self.assertFalse((out / 'failure.json').exists())
                else:
                    self.assertEqual(evidence['status'], 'partial')
                    failure = json.loads((out / 'failure.json').read_text())
                    self.assertIn(mode, failure['reason'])
                    if mode != 'parentdeath': self.assertEqual(p.returncode, -signal.SIGKILL)
            finally:
                if p.poll() is None:
                    os.killpg(p.pid, signal.SIGKILL); p.wait()
                p.communicate(timeout=3)
    def test_overall_kills_blocked_worker_and_child(self): self.worker('overall')
    def test_inference_kills_blocked_worker_and_child(self): self.worker('inference')
    def test_request_kills_blocked_worker_and_child(self): self.worker('request')
    def test_normal_disarm_no_kill_or_residue(self): self.worker('normal')
    def test_parentdeath_cleans_children(self): self.worker('parentdeath')
    def test_evidence_write_failure_still_kills(self): self.worker('evidencewrite')
    def test_exception_cleans_children(self): self.worker('exception')
    def test_dataset_cache_requires_official_pinned_sha(self):
        nb = json.loads((ROOT / 'drcd_cpu.ipynb').read_text())
        config = next(''.join(c['source']) for c in nb['cells'] if c.get('id') == 'cell-04')
        import hashlib
        ns = {'hashlib': hashlib}; exec(config, ns)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'drcd-test.parquet'; path.write_bytes(b'corrupt')
            ns['urlopen'] = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('fetch attempted'))
            with self.assertRaisesRegex(ValueError, 'expected SHA256'):
                ns['download']('https://invalid', path)
            with self.assertRaisesRegex(RuntimeError, 'fetch attempted'):
                ns['download']('https://invalid', path, 'c96bd232753f77096a05fa16e58904018495ae3fefd062216042600818666364')
        setup = next(''.join(c['source']) for c in nb['cells'] if c.get('id') == 'cell-05')
        self.assertIn("dataset_item['lfs']['sha256']", setup)
        self.assertNotIn("CACHE / 'drcd-test.parquet', None", setup)
    def test_kernel_callback_disarms_only_after_final_cell(self):
        self.kernel_case('normal')
    def test_kernel_setup_cell_exception_cleans_group(self):
        self.kernel_case('exception')
    def test_kernel_blocking_setup_overall_deadline(self):
        self.kernel_case('overall')
    def kernel_case(self, mode):
        import nbformat
        from nbclient import NotebookClient
        from jupyter_client import KernelManager
        nb = nbformat.read(ROOT / 'drcd_cpu.ipynb', as_version=4)
        cells = [c for c in nb.cells if c.get('id') in {'cell-01','cell-02','resource-guard','cell-04'}]
        tail = """
child = subprocess.Popen([sys.executable, '-c', 'import signal; signal.pause()'])
save('kernel-test-pids.json', [os.getpid(), child.pid, guard.proc.pid])
"""
        if mode == 'normal': tail += "child.terminate(); child.wait(); guard_ready_to_finish = True\n"
        elif mode == 'exception': tail += "raise ValueError('setup exception probe')\n"
        else: tail += "guard.state['overall'] = time.monotonic()+.7; guard._write(); signal.pause()\n"
        cells.append(nbformat.v4.new_code_cell(tail))
        probe = nbformat.v4.new_notebook(cells=cells)
        with tempfile.TemporaryDirectory() as tmp:
            km = KernelManager(kernel_name='python3', transport='ipc', ip=str(Path(tmp) / 'kernel-ipc'), client_class='jupyter_client.asynchronous.AsyncKernelClient')
            km.kernel_spec.argv = [sys.executable, '-m','ipykernel_launcher','-f','{connection_file}']
            previous = os.environ.get('DRCD_MODE'); os.environ['DRCD_MODE'] = 'fresh'
            client = NotebookClient(probe, km=km, timeout=8)
            try:
                try: client.execute(cwd=tmp)
                except Exception:
                    if mode == 'normal': raise
                out = Path(tmp) / 'results/drcd-cpu'
                for _ in range(150):
                    if (out / 'watchdog.json').exists(): break
                    time.sleep(.02)
                self.assertTrue((out / 'watchdog.json').exists(), 'watchdog did not disarm after final cell or clean up setup exception')
                evidence = json.loads((out / 'watchdog.json').read_text())
                self.assertEqual(evidence['status'], 'complete' if mode == 'normal' else 'partial')
                ids = json.loads((out / 'kernel-test-pids.json').read_text())
                for _ in range(150):
                    if not any(live(i) for i in (ids[1:] if mode == 'normal' else ids)): break
                    time.sleep(.02)
                self.assertFalse(any(live(i) for i in (ids[1:] if mode == 'normal' else ids)))
                persist_evidence(out, 'kernel-'+mode)
            finally:
                if client.kc is not None: client.kc.stop_channels()
                if km.has_kernel: km.shutdown_kernel(now=True)
                if previous is None: os.environ.pop('DRCD_MODE', None)
                else: os.environ['DRCD_MODE'] = previous
    def test_fail_closed_shared_process_group(self):
        ns = {}; exec(guard_source(), ns)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, 'dedicated'):
                ns['ResourceGuard'](Path(tmp))

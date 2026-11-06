"""Infrastructure runner only; all evaluation logic stays in native Notebook cells.
Uses an owned, session-leading IPC kernel. Replay blocks every urllib HTTP call.
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
import nbformat
from nbclient import NotebookClient
from jupyter_client import KernelManager

parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=['fresh', 'replay'])
args = parser.parse_args()
root = Path(__file__).resolve().parent
os.environ['DRCD_MODE'] = args.mode
nb = nbformat.read(root / 'drcd_cpu.ipynb', as_version=4)
source_sha = hashlib.sha256((root / 'drcd_cpu.ipynb').read_bytes()).hexdigest()
raw = root / 'results/drcd-cpu/raw-generations.jsonl'
before = hashlib.sha256(raw.read_bytes()).hexdigest() if args.mode == 'replay' else None
ipc_dir = tempfile.TemporaryDirectory(prefix='drcd-ipc-')
km = KernelManager(kernel_name='python3', transport='ipc', ip=str(Path(ipc_dir.name)/'ipc'), client_class='jupyter_client.asynchronous.AsyncKernelClient')
bootstrap = """
import os, runpy, urllib.request
if os.environ.get('DRCD_MODE') == 'replay':
    def deny_http(*a, **k):
        raise AssertionError('HTTP forbidden during replay')
    urllib.request.urlopen = deny_http
runpy.run_module('ipykernel_launcher', run_name='__main__')
"""
km.kernel_spec.argv = [sys.executable, '-c', bootstrap, '-f', '{connection_file}']
# Jupyter local provisioner starts a new session; ResourceGuard independently checks it.
client = NotebookClient(nb, km=km, timeout=2150, allow_errors=False,
                        resources={'metadata': {'path': str(root)}})
output = root / ('drcd_cpu.executed.ipynb' if args.mode == 'fresh' else 'drcd_cpu.replayed.ipynb')
try:
    client.execute(cwd=str(root))
finally:
    nbformat.write(nb, output)
    if client.kc is not None:
        client.kc.stop_channels()
    if km.has_kernel:
        km.shutdown_kernel(now=True)
    ipc_dir.cleanup()
assert hashlib.sha256((root / 'drcd_cpu.ipynb').read_bytes()).hexdigest() == source_sha
assert all(c.execution_count is not None for c in nb.cells if c.cell_type == 'code')
assert not any(o.output_type == 'error' for c in nb.cells for o in c.get('outputs', []))
if args.mode == 'replay':
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == before
report = {'mode': args.mode, 'source_sha256': source_sha, 'cells': len(nb.cells),
          'code_cells': sum(c.cell_type == 'code' for c in nb.cells),
          'all_cells_executed': True, 'ipc_transport': True, 'kernel_stopped': not km.has_kernel,
          'replay_http_blocked': args.mode == 'replay', 'raw_sha256': hashlib.sha256(raw.read_bytes()).hexdigest()}
(root / 'results/drcd-cpu' / f'{args.mode}-execution.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))

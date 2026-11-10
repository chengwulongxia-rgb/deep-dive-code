"""IPC/kernel lifecycle only. Experiment source lives in drcd_api.ipynb."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from jupyter_client import KernelManager
import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parent
BOOTSTRAP = r'''
import builtins, io, os, runpy, urllib.request
if os.environ.get('DRCD_API_MODE', 'replay') == 'replay':
    def deny_http(*args, **kwargs):
        raise AssertionError('HTTP forbidden during API replay')
    urllib.request.urlopen = deny_http
    urllib.request.OpenerDirector.open = deny_http
    denied = [os.environ.get('DRCD_API_KEY_FILE'),
              os.path.expanduser('~/.local/state/llm-cost-frontier/drcd-openai-budget.json')]
    denied = {os.path.abspath(p) for p in denied if p}
    def guarded(original):
        def call(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)) and os.path.abspath(os.fsdecode(file)) in denied:
                raise AssertionError('Key/private ledger IO forbidden during API replay')
            return original(file, *args, **kwargs)
        return call
    builtins.open = guarded(builtins.open)
    io.open = guarded(io.open)
    os.open = guarded(os.open)
runpy.run_module('ipykernel_launcher', run_name='__main__')
'''

def run_notebook(mode='replay', output=None):
    if mode not in ('replay', 'fresh'):
        raise ValueError('mode must be replay or fresh')
    os.environ['DRCD_API_MODE'] = mode
    source = ROOT / 'drcd_api.ipynb'
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    nb = nbformat.read(source, as_version=4)
    output = Path(output) if output is not None else ROOT / f'drcd_api.{"executed" if mode == "fresh" else "replayed"}.ipynb'
    scratch = Path(os.environ.get('TMPDIR', str(Path.home() / '.hermes/cache/scratch')))
    scratch.mkdir(parents=True, exist_ok=True)
    ipc = tempfile.TemporaryDirectory(prefix='drcd-api-ipc-', dir=scratch)
    km = KernelManager(kernel_name='python3', transport='ipc', ip=str(Path(ipc.name) / 'ipc'),
                       client_class='jupyter_client.asynchronous.AsyncKernelClient')
    km.kernel_spec.argv = [sys.executable, '-c', BOOTSTRAP, '-f', '{connection_file}']
    client = NotebookClient(nb, km=km, timeout=1250, allow_errors=False,
                            resources={'metadata': {'path': str(ROOT)}})
    pid = None
    try:
        # Explicit startup permits recording the owned PID even if writing the output fails.
        km.start_kernel(cwd=str(ROOT))
        pid = km.provisioner.pid
        client.execute(cwd=str(ROOT))
    finally:
        try:
            nbformat.write(nb, output)
        finally:
            try:
                if client.kc is not None: client.kc.stop_channels()
            finally:
                try:
                    if km.has_kernel: km.shutdown_kernel(now=True)
                finally:
                    ipc.cleanup()
    assert not km.has_kernel
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha
    assert all(c.execution_count is not None for c in nb.cells if c.cell_type == 'code')
    assert not any(o.output_type == 'error' for c in nb.cells for o in c.get('outputs', []))
    return {'mode': mode, 'source_sha256': source_sha, 'kernel_pid': pid, 'kernel_stopped': not km.has_kernel,
            'ipc_transport': True, 'all_cells_executed': True,
            'code_cells': sum(c.cell_type == 'code' for c in nb.cells),
            'replay_http_and_key_blocked': mode == 'replay', 'output': str(output)}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', nargs='?', default='replay', choices=['replay', 'fresh'])
    args = parser.parse_args()
    print(json.dumps(run_notebook(args.mode), indent=2))

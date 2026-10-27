#!/usr/bin/env python3
"""Bounded, explicitly approved L4 smoke run; private CLI logs stay in scratch."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

HERE = Path(__file__).resolve().parent
UPSTREAM = '2074cc44256200bb37540103fa4572901faa10f3'
UV = '0.12.2'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-l4-20min', action='store_true')
    args = parser.parse_args()
    if not args.approved_l4_20min:
        parser.error('Explicit L4/20-minute approval flag required')
    for name in ['remote_smoke.py', 'cwa_dom.json']:
        if not (HERE / name).is_file():
            raise FileNotFoundError(name)
    os.umask(0o077)
    scratch = Path.home() / '.hermes/cache/scratch'
    private = Path(tempfile.mkdtemp(prefix='kev-colab-private-', dir=scratch))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    session = 'kev-smoke-' + stamp.lower()
    base = ['colab', '--auth', 'adc', '--config', str(private / 'sessions.json')]
    output = HERE / 'results' / stamp
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    previous_seconds = sum(json.loads(p.read_text()).get('elapsed_seconds', 0)
                           for p in (HERE/'results').glob('*/lifecycle.json'))
    work_seconds = 1200 - previous_seconds - 120
    if work_seconds <= 0:
        raise RuntimeError('Cumulative approved GPU budget exhausted; no new session created')
    deadline = started + work_seconds  # cumulative budget, leaving two minutes for cleanup
    entries = []
    stop_lock = threading.Lock()
    report = {'session_name': session, 'requested_gpu': 'L4', 'approved_minutes': 20,
              'private_logs': str(private), 'started_utc': datetime.now(timezone.utc).isoformat(),
              'previous_attempt_seconds': previous_seconds,
              'inference_completed': False, 'stop_exit': None}

    def cli(label, arguments, *, timeout=60, check=True, budget=True):
        if budget:
            timeout = min(timeout, max(1, deadline-time.monotonic()))
            if time.monotonic() >= deadline:
                raise TimeoutError('GPU work deadline reached')
        command = [*base, *arguments]
        begin = time.monotonic()
        try:
            p = subprocess.run(command, stdin=subprocess.DEVNULL, text=True,
                               capture_output=True, timeout=timeout)
            code, stdout, stderr = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired as exc:
            code = 124
            stdout = exc.stdout or b''
            stderr = exc.stderr or b''
            if isinstance(stdout, bytes): stdout = stdout.decode(errors='replace')
            if isinstance(stderr, bytes): stderr = stderr.decode(errors='replace')
        (private / (label+'.stdout')).write_text(stdout)
        (private / (label+'.stderr')).write_text(stderr)
        entries.append({'label': label, 'argv': command, 'exit_code': code,
                        'seconds': time.monotonic()-begin})
        print(label, 'exit', code, flush=True)
        if check and code:
            raise RuntimeError(f'{label} failed (exit {code}); private logs: {private}')
        return code, stdout, stderr

    def stop(label):
        with stop_lock:
            code, _, _ = cli(label, ['stop', '-s', session], timeout=40, check=False, budget=False)
            report['stop_exit'] = code

    def guard():
        report['watchdog_triggered'] = True
        stop('watchdog-stop')

    def interrupted(*_):
        raise KeyboardInterrupt('Interrupted; releasing only our Colab runtime')

    signal.signal(signal.SIGTERM, interrupted)
    watchdog = threading.Timer(max(0, deadline-time.monotonic()), guard)
    watchdog.daemon = True
    watchdog.start()
    try:
        cli('create-l4', ['new', '-s', session, '--gpu', 'L4'], timeout=150)
        probe = private / 'probe.py'
        probe.write_text("import subprocess,json,sys\ns=subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader'],text=True)\nprint(s)\nassert 'L4' in s, 'Refusing non-L4 accelerator'\nprint(sys.version)\n")
        cli('probe-l4', ['exec', '-s', session, '-f', str(probe), '--timeout', '45'], timeout=65)
        cli('upload-script', ['upload', '-s', session, str(HERE/'remote_smoke.py'), '/content/remote_smoke.py'])
        cli('upload-dom', ['upload', '-s', session, str(HERE/'cwa_dom.json'), '/content/cwa_dom.json'])
        bootstrap = private / 'bootstrap.py'
        bootstrap.write_text("""import os,subprocess,sys,zipfile,urllib.request,hashlib
from pathlib import Path
os.environ['GIT_TERMINAL_PROMPT']='0'
def run(argv, **kwargs):
    p=subprocess.run(argv, capture_output=True, text=True, timeout=750, **kwargs)
    print(p.stdout, flush=True)
    print(p.stderr, file=sys.stderr, flush=True)
    p.check_returncode()
root=Path('/content/kev-source')
run(['git','init','-q','--initial-branch=main',str(root)])
run(['git','-C',str(root),'-c','core.hooksPath=/dev/null','fetch','--depth=1','https://github.com/jaredpalmer/kev.git','"""+UPSTREAM+"""'])
run(['git','-C',str(root),'-c','core.hooksPath=/dev/null','checkout','--detach','FETCH_HEAD'])
assert subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()=='"""+UPSTREAM+"""'
wheel=Path('/content/uv-0.12.2.whl')
urllib.request.urlretrieve('https://files.pythonhosted.org/packages/a7/fe/a87be2a492440945e745b0dc81aef7fea9730d8194af88d854b7641f5ddf/uv-0.12.2-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl',wheel)
assert hashlib.sha256(wheel.read_bytes()).hexdigest()=='3a8d93d1fe019561b70494a8e1332492afb5f14dadc33d5239569d0964164d10'
with zipfile.ZipFile(wheel) as archive:
    names=[n for n in archive.namelist() if n.endswith('.data/scripts/uv') or n=='uv/uv']
    assert len(names)==1,names
    uv_path=Path('/content/uv-pinned');uv_path.write_bytes(archive.read(names[0]));uv_path.chmod(0o755)
uv=str(uv_path)
run([uv,'sync','--frozen','--extra','serve','--no-dev'],cwd=root)
run([uv,'run','--frozen','--extra','serve','--no-dev','python','/content/remote_smoke.py'],cwd=root)
""")
        remaining = max(1, int(deadline-time.monotonic())-70)
        code, _, _ = cli('execute-model', ['exec', '-s', session, '-f', str(bootstrap), '--timeout', str(remaining)],
                          timeout=remaining+20, check=False)
        downloaded, _, _ = cli('download-results', ['download', '-s', session,
                           '/content/kev-smoke-artifacts.zip', str(output/'artifacts.zip')], check=False)
        report['execute_exit'] = code
        report['download_exit'] = downloaded
        if downloaded == 0:
            with zipfile.ZipFile(output/'artifacts.zip') as archive:
                for item in archive.infolist():
                    p = Path(item.filename)
                    if p.is_absolute() or '..' in p.parts:
                        raise ValueError('Unsafe artifact archive path')
                archive.extractall(output/'artifacts')
            result=json.loads((output/'artifacts'/'kev-smoke-result.json').read_text())
            report['inference_completed'] = (code == 0 and result.get('inference_status')=='completed'
                                             and result.get('status')=='completed')
            report['model_summary'] = result.get('summary')
    except BaseException as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        watchdog.cancel()
        stop('final-stop')
        _, sessions, _ = cli('sessions-after-stop', ['sessions'], timeout=30, check=False, budget=False)
        report['sessions_after_stop'] = sessions
        report['elapsed_seconds'] = time.monotonic()-started
        report['ended_utc'] = datetime.now(timezone.utc).isoformat()
        (private/'commands.json').write_text(json.dumps(entries, ensure_ascii=False, indent=2)+'\n')
        (output/'lifecycle.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0 if report['inference_completed'] and report['stop_exit']==0 else 1


if __name__ == '__main__':
    sys.exit(main())

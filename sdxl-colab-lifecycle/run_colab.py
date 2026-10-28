"""Owned Colab runtime -> local durable backup -> verified GCS -> teardown."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import uuid
import zipfile

HERE = Path(__file__).resolve().parent

class BudgetExpired(BaseException):
    """Must escape HTTP libraries' Exception/Timeout retry handlers."""


def remaining_seconds(reports):
    elapsed = []
    for report in reports:
        seconds = float(report['elapsed_seconds'])
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError('Invalid prior lifecycle duration; refusing to allocate')
        elapsed.append(seconds)
    remaining = 1200 - sum(elapsed) - 120
    if remaining <= 0:
        raise ValueError('Cumulative approved budget exhausted')
    return remaining


def extract_artifacts(archive, destination):
    destination = Path(destination)
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist()) > 32 * 1024 * 1024:
            raise ValueError('Archive larger than expected')
        for info in z.infolist():
            p = Path(info.filename)
            if p.is_absolute() or '..' in p.parts or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('Unsafe archive member')
        destination.mkdir(parents=True, exist_ok=True)
        z.extractall(destination)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--approved-l4-20min', action='store_true', required=True)
    parser.add_argument('--bucket', required=True)
    parser.add_argument('--prefix', required=True)
    args = parser.parse_args()
    from gcs_store import GCSStore
    store = GCSStore(args.bucket, args.prefix)
    # Permission validation occurs before any billable allocation.
    probe = json.dumps({'purpose': 'SDXL lifecycle preflight', 'nonce': uuid.uuid4().hex}).encode()
    store.put_verified('preflight-' + uuid.uuid4().hex[:8] + '.json', probe, 'application/json')
    history = HERE / '.private-runs'
    history.mkdir(mode=0o700, exist_ok=True)
    reports = [json.loads(p.read_text()) for p in history.glob('*/lifecycle.json')]
    work_seconds = remaining_seconds(reports)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    run_dir = history / run_id
    run_dir.mkdir(mode=0o700)
    scratch = Path(tempfile.mkdtemp(prefix='sdxl-colab-private-', dir=str(Path.home() / '.hermes/cache/scratch')))
    scratch.chmod(0o700)
    config = scratch / 'sessions.json'
    session = 'sdxl-' + run_id.lower()
    started = time.monotonic()
    deadline = started + work_seconds
    lifecycle = {'run_id': run_id, 'session_name': session, 'bucket': args.bucket, 'prefix': args.prefix,
                 'started_utc': datetime.now(timezone.utc).isoformat(), 'previous_attempt_seconds': sum(float(r['elapsed_seconds']) for r in reports),
                 'gpu_requested': 'L4', 'generation_completed': False, 'gcs_verified': False, 'private_logs': str(scratch)}

    def command(stage, *arguments, cleanup=False, allowed_failure=False):
        timeout = 45 if cleanup else min(900, max(1, deadline - time.monotonic()))
        if not cleanup and time.monotonic() >= deadline:
            raise TimeoutError('Working deadline reached; preserving cleanup reserve')
        result = subprocess.run(['colab', '--auth', 'adc', '--config', str(config), *arguments],
                                capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        (scratch / (stage + '.stdout')).write_text(result.stdout)
        (scratch / (stage + '.stderr')).write_text(result.stderr)
        print(stage, 'exit', result.returncode, flush=True)
        if result.returncode and not allowed_failure:
            raise RuntimeError(stage + ' failed; private diagnostics: ' + str(scratch))
        return result

    def alarm_handler(signum, frame):
        raise BudgetExpired('Approved working time exhausted')

    previous_handler = signal.signal(signal.SIGALRM, alarm_handler)
    signal.alarm(max(1, int(work_seconds)))
    try:
        command('create-l4', 'new', '-s', session, '--gpu', 'L4')
        probe_file = scratch / 'probe.py'
        probe_file.write_text("import subprocess,json\nfrom pathlib import Path\ns=subprocess.check_output(['nvidia-smi','--query-gpu=name','--format=csv,noheader'],text=True)\nprint(s)\nassert 'L4' in s,s\nPath('/content/sdxl-probe.json').write_text(json.dumps({'gpu':s.strip()}))\n")
        command('probe-l4', 'exec', '-s', session, '-f', str(probe_file), '--timeout', '60')
        command('download-probe', 'download', '-s', session, '/content/sdxl-probe.json', str(run_dir / 'probe.json'))
        if 'L4' not in json.loads((run_dir / 'probe.json').read_text())['gpu']:
            raise RuntimeError('Runtime is not L4')
        for name in ['generate.py', 'requirements.txt', 'bootstrap.py']:
            command('upload-' + name, 'upload', '-s', session, str(HERE / name), '/content/' + name)
        bootstrap = scratch / 'install.py'
        bootstrap.write_text("import subprocess,sys,json\nfrom pathlib import Path\np=subprocess.run([sys.executable,'/content/bootstrap.py','--requirements','/content/requirements.txt'],capture_output=True,text=True)\nprint(p.stdout);print(p.stderr,file=sys.stderr)\nPath('/content/sdxl-install.json').write_text(json.dumps({'returncode':p.returncode,'isolated_environment':'/content/sdxl-env'}))\nif p.returncode: raise RuntimeError('Isolated dependency setup failed')\n")
        command('install', 'exec', '-s', session, '-f', str(bootstrap), '--timeout', str(min(600, int(deadline - time.monotonic()))))
        command('download-install', 'download', '-s', session, '/content/sdxl-install.json', str(run_dir / 'install.json'))
        if json.loads((run_dir / 'install.json').read_text())['returncode']:
            raise RuntimeError('Remote installation failed despite transport completion')
        execute = scratch / 'execute.py'
        execute.write_text("import subprocess,sys,json\nfrom pathlib import Path\np=subprocess.run(['/content/sdxl-env/bin/python','/content/generate.py','--output','/content/sdxl-output'],capture_output=True,text=True)\nprint(p.stdout);print(p.stderr,file=sys.stderr)\nPath('/content/sdxl-execute.json').write_text(json.dumps({'returncode':p.returncode}))\nif p.returncode: raise RuntimeError('Image generation failed')\n")
        command('generate', 'exec', '-s', session, '-f', str(execute), '--timeout', str(max(1, int(deadline - time.monotonic()))))
        command('download-execute', 'download', '-s', session, '/content/sdxl-execute.json', str(run_dir / 'execute.json'))
        archive = run_dir / 'result.zip'
        command('download-results', 'download', '-s', session, '/content/sdxl-output/result.zip', str(archive))
        artifacts = run_dir / 'artifacts'
        extract_artifacts(archive, artifacts)
        shutil.copyfile(archive, artifacts / 'result.zip')
        if json.loads((run_dir / 'execute.json').read_text())['returncode']:
            raise RuntimeError('Remote generation failed; partial artifacts backed up before teardown')
        for name in ['image.png', 'parameters.json', 'metrics.json', 'manifest.json']:
            if not (artifacts / name).is_file():
                raise RuntimeError('Missing generated artifact: ' + name)
        lifecycle['generation_completed'] = True
        receipt = store.publish(artifacts)
        (run_dir / 'gcs-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
        lifecycle['gcs_verified'] = True
        print('GCS readback verified:', 'gs://' + args.bucket + '/' + args.prefix + '/', flush=True)
    except BaseException as exc:
        lifecycle['error_type'] = type(exc).__name__
        lifecycle['error'] = str(exc)
        raise
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)
        try:
            result = command('final-stop', 'stop', '-s', session, cleanup=True, allowed_failure=True)
            lifecycle['stop_exit'] = result.returncode
        except Exception as exc:
            lifecycle['stop_error'] = str(exc)
        try:
            result = command('sessions-after-stop', 'sessions', cleanup=True, allowed_failure=True)
            lifecycle['sessions_after_stop'] = result.stdout
        except Exception as exc:
            lifecycle['sessions_readback_error'] = str(exc)
        lifecycle['elapsed_seconds'] = time.monotonic() - started
        lifecycle['ended_utc'] = datetime.now(timezone.utc).isoformat()
        (run_dir / 'lifecycle.json').write_text(json.dumps(lifecycle, ensure_ascii=False, indent=2))
        print(json.dumps(lifecycle, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()

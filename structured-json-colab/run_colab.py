"""Owned Colab lifecycle; imports are CPU-only and stdlib."""
import math
import re
from pathlib import Path
import stat
import zipfile


def extract_results(archive, destination):
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist()) > 64*1024*1024:
            raise ValueError('Archive exceeds evidence size limit')
        for i in z.infolist():
            p = Path(i.filename)
            if p.is_absolute() or '..' in p.parts or stat.S_ISLNK(i.external_attr >> 16):
                raise ValueError('Unsafe result archive')
        Path(destination).mkdir(parents=True, exist_ok=True)
        z.extractall(destination)


def parse_usage(text):
    patterns = [r'Current balance:\s*([0-9]+(?:\.[0-9]+)?)\s+compute units',
                r'Usage rate:\s*([0-9]+(?:\.[0-9]+)?)/hr',
                r'Active assignments:\s*(\d+)']
    parts = []
    for pattern in patterns:
        match = re.search(pattern, text)
        if match is None:
            raise ValueError('Could not parse Colab account usage; refusing allocation')
        parts.append(match.group(1))
    balance, rate = [float(value) for value in parts[:2]]
    if not all(math.isfinite(x) for x in [balance, rate]):
        raise ValueError('Invalid account usage')
    return balance, rate, int(parts[2])


def limits(*, elapsed, prior_seconds, spent, rate):
    values = [elapsed, prior_seconds, spent, rate]
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError('Budget inputs must be finite and nonnegative')
    seconds = 1200 - prior_seconds - elapsed - 120
    remaining = 5 - spent
    reserve = max(0.25, rate * 120 / 3600)
    return {'work_seconds': seconds, 'cu_remaining': remaining,
            'can_work': seconds > 0 and remaining > reserve}


def prior_budget(reports):
    seconds = cu = 0.0
    for report in reports:
        elapsed = float(report['elapsed_seconds'])
        spent = float(report['conservative_cu'])
        if any(not math.isfinite(x) or x < 0 for x in [elapsed, spent]):
            raise ValueError('Invalid prior attempt budget; refusing a silent reset')
        seconds += elapsed
        cu += spent
    return seconds, cu


class BudgetExpired(BaseException):
    """Do not allow a library's retry handler to swallow budget expiry."""


def main():
    import argparse
    from datetime import datetime, timezone
    import hashlib
    import json
    import os
    import signal
    import subprocess
    import time
    import uuid

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-l4-20min-5cu', action='store_true', required=True)
    args = parser.parse_args()
    assert args.approved_l4_20min_5cu
    here = Path(__file__).resolve().parent
    history = here/'.private-runs'
    history.mkdir(mode=0o700, exist_ok=True)
    reports = []
    for p in history.glob('*/lifecycle.json'):
        r = json.loads(p.read_text())
        if not r.get('finalized') or not r.get('owned_session_absent'):
            raise RuntimeError('Unresolved prior runtime; inspect private lifecycle before allocating')
        reports.append(r)
    prior_seconds, prior_cu = prior_budget(reports)
    if not limits(elapsed=0, prior_seconds=prior_seconds, spent=prior_cu, rate=0)['can_work']:
        raise RuntimeError('Cumulative approved budget exhausted')
    pre = subprocess.run(['colab','--auth','adc','usage'],capture_output=True,text=True,timeout=20,check=True)
    balance0, rate0, active0 = parse_usage(pre.stdout)
    if active0 or rate0 or balance0 < 5:
        raise RuntimeError('Require no other active runtimes and >=5 CU before allocation')
    ident = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6]
    run = history/ident
    run.mkdir(mode=0o700)
    config = run/'sessions.json'
    session = 'json-abc-'+ident.lower()
    started = time.monotonic()
    allocated = False
    max_rate = 0.0
    observed_spent = 0.0
    last_usage = 0.0
    state = {'run_id':ident,'session_name':session,'gpu_requested':'L4','budget_seconds':1200,
             'budget_cu':5,'previous_seconds':prior_seconds,'previous_conservative_cu':prior_cu,
             'started_utc':datetime.now(timezone.utc).isoformat(),'balance_before':balance0,
             'completed':False,'finalized':False,'usage_samples':[]}
    base = ['colab','--auth','adc','--config',str(config)]

    def save():
        elapsed = time.monotonic()-started
        state.update(elapsed_seconds=elapsed, conservative_cu=max(observed_spent,max_rate*elapsed/3600),
                     max_rate_cu_per_hour=max_rate)
        (run/'lifecycle.json').write_text(json.dumps(state,ensure_ascii=False,indent=2))

    def usage(force=False):
        nonlocal max_rate, observed_spent, last_usage
        now = time.monotonic()
        if not force and now-last_usage < 15:
            return
        result = subprocess.run(base+['usage'],capture_output=True,text=True,timeout=15,check=True)
        balance, rate, assignments = parse_usage(result.stdout)
        last_usage = time.monotonic()
        observed_spent = max(observed_spent,balance0-balance)
        max_rate = max(max_rate,rate)
        state['usage_samples'].append({'elapsed_seconds':last_usage-started,'balance':balance,'rate':rate,'active':assignments})
        save()
        if assignments > 1:
            raise BudgetExpired('Another account runtime appeared; cannot isolate budget attribution')
        if allocated and (assignments != 1 or rate <= 0):
            raise BudgetExpired('Cannot verify owned L4 billing rate; stopping safely')

    def guard():
        usage()
        elapsed = time.monotonic()-started
        spent = prior_cu+max(observed_spent,max_rate*elapsed/3600)
        if not limits(elapsed=elapsed,prior_seconds=prior_seconds,spent=spent,rate=max_rate)['can_work']:
            raise BudgetExpired('Approved cumulative time/CU limit reached (cleanup reserve preserved)')

    def command(stage,*argv,cleanup=False,allowed_failure=False,timeout=None):
        if not cleanup:
            guard()
        stdout_path, stderr_path = run/(stage+'.stdout'),run/(stage+'.stderr')
        with stdout_path.open('w') as out, stderr_path.open('w') as err:
            p = subprocess.Popen(base+list(argv),stdout=out,stderr=err,stdin=subprocess.DEVNULL,start_new_session=True)
            command_started = time.monotonic()
            try:
                while p.poll() is None:
                    if timeout is not None and time.monotonic()-command_started > timeout:
                        raise TimeoutError(stage+' timed out')
                    if not cleanup:
                        guard()
                    time.sleep(0.2)
            except BaseException:
                try:
                    os.killpg(p.pid,signal.SIGKILL)
                except ProcessLookupError:
                    pass
                p.wait()
                raise
        print(stage,'exit',p.returncode,flush=True)
        if p.returncode and not allowed_failure:
            raise RuntimeError(stage+' failed; inspect private logs '+str(run))
        return p.returncode, stdout_path.read_text(), stderr_path.read_text()

    save()
    try:
        command('create','new','-s',session,'--gpu','L4',timeout=120)
        allocated = True
        usage(force=True)
        probe = run/'probe.py'
        probe.write_text("import json,subprocess\nfrom pathlib import Path\ns=subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader'],text=True).strip()\nPath('/content/json-probe.json').write_text(json.dumps({'gpu':s}))\nassert 'L4' in s,s\nprint(s)\n")
        command('probe','exec','-s',session,'-f',str(probe),'--timeout','45')
        command('probe-download','download','-s',session,'/content/json-probe.json',str(run/'probe.json'))
        if 'L4' not in json.loads((run/'probe.json').read_text())['gpu']:
            raise RuntimeError('Actual GPU is not L4; refusing escalation')
        for name in ['benchmark.py','fixtures.json','requirements.txt','bootstrap.py']:
            command('upload-'+name,'upload','-s',session,str(here/name),'/content/'+name)
        setup = run/'setup_remote.py'
        setup.write_text("import subprocess,sys,json\nfrom pathlib import Path\np=subprocess.run([sys.executable,'/content/bootstrap.py','--requirements','/content/requirements.txt'],capture_output=True,text=True)\nprint(p.stdout);print(p.stderr,file=sys.stderr)\nPath('/content/json-install.json').write_text(json.dumps({'returncode':p.returncode}))\nif p.returncode: raise RuntimeError('Dependency setup failed')\n")
        command('setup','exec','-s',session,'-f',str(setup),'--timeout','500')
        command('setup-download','download','-s',session,'/content/json-install.json',str(run/'install.json'))
        if json.loads((run/'install.json').read_text())['returncode']:
            raise RuntimeError('Remote setup failed despite transport success')
        sha = subprocess.check_output(['git','rev-parse','HEAD'],cwd=here,text=True).strip()
        hashes = {n:hashlib.sha256((here/n).read_bytes()).hexdigest() for n in ['benchmark.py','fixtures.json','requirements.txt','bootstrap.py']}
        state['source_commit'] = sha
        state['source_sha256'] = hashes
        execute = run/'execute_remote.py'
        execute.write_text("import subprocess,sys,json\nfrom pathlib import Path\np=subprocess.run(['/content/structured-json-env/bin/python','/content/benchmark.py','--output','/content/structured-json-output','--fixture','/content/fixtures.json','--git-commit',"+repr(sha)+"],capture_output=True,text=True)\nprint(p.stdout);print(p.stderr,file=sys.stderr)\nPath('/content/json-execute.json').write_text(json.dumps({'returncode':p.returncode}))\nif p.returncode: raise RuntimeError('Benchmark failed; preserve partial artifacts')\n")
        command('benchmark','exec','-s',session,'-f',str(execute),'--timeout',str(max(1,int(limits(elapsed=time.monotonic()-started,prior_seconds=prior_seconds,spent=prior_cu,rate=max_rate)['work_seconds']-45))))
        command('execute-download','download','-s',session,'/content/json-execute.json',str(run/'execute.json'))
        command('results-download','download','-s',session,'/content/structured-json-output/result.zip',str(run/'result.zip'))
        extract_results(run/'result.zip',run/'artifacts')
        report = json.loads((run/'artifacts/report.json').read_text())
        if json.loads((run/'execute.json').read_text())['returncode'] or report.get('status')!='completed':
            raise RuntimeError('Transport completed but benchmark did not')
        state['completed'] = True
    except BaseException as exc:
        state['error_type'],state['error'] = type(exc).__name__,str(exc)
        print('STOP:',type(exc).__name__,str(exc),flush=True)
    finally:
        # Bounded salvage before teardown. Never keep a GPU for analysis/publishing.
        if allocated and not (run/'result.zip').exists():
            try:
                command('salvage-jsonl','download','-s',session,'/content/structured-json-output/results.jsonl',str(run/'partial-results.jsonl'),cleanup=True,allowed_failure=True,timeout=15)
                command('salvage-zip','download','-s',session,'/content/structured-json-output/result.zip',str(run/'result.zip'),cleanup=True,allowed_failure=True,timeout=15)
            except Exception as exc:
                state['salvage_error'] = str(exc)
        try:
            code,_,_ = command('stop','stop','-s',session,cleanup=True,allowed_failure=True,timeout=30)
            state['stop_exit'] = code
            if code:
                code,_,_ = command('stop-retry','stop','-s',session,cleanup=True,allowed_failure=True,timeout=15)
                state['stop_retry_exit'] = code
        except Exception as exc:
            state['stop_error'] = str(exc)
        try:
            _,out,_ = command('sessions-after','sessions',cleanup=True,allowed_failure=False,timeout=15)
            state['owned_session_absent'] = ('No active sessions' in out) and session not in out
        except Exception as exc:
            state['readback_error'] = str(exc)
        try:
            _,out,_ = command('usage-after','usage',cleanup=True,timeout=15)
            balance,rate,assignments = parse_usage(out)
            state.update(balance_after=balance,rate_after=rate,assignments_after=assignments)
            observed_spent=max(observed_spent,balance0-balance)
        except Exception as exc:
            state['usage_after_error']=str(exc)
        state['finalized']=True
        state['ended_utc']=datetime.now(timezone.utc).isoformat()
        save()
        print(json.dumps(state,ensure_ascii=False,indent=2),flush=True)
        print('PRIVATE_RUN_DIR',run,flush=True)
    if not state['completed'] or not state.get('owned_session_absent'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()

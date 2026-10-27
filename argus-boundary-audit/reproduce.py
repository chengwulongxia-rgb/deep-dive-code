#!/usr/bin/env python3
"""Run exactly 18 pinned upstream Argus tests in a bounded Docker sandbox.

Host code is standard-library only. No upstream setup scripts are executed.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
URL = 'https://github.com/thomasunise/argus'
SHA = '8cf56b0fe837538b478812652bd46eff60e20f23'
BASE = 'python:3.13-slim@sha256:bb2988715db2cf7ace7b53f38f3cffbef7c7046a656bee66245eb0ed386e2e81'
NODES = json.loads((HERE / 'selection.json').read_text())['test_nodes']
JUNIT_PREFIX = 'ARGUS_JUNIT_BASE64:'
JUNIT_EXPORT = (
    'import base64,pathlib,subprocess,sys; '
    'code=subprocess.call(sys.argv[1:]); '
    'p=pathlib.Path("/tmp/junit.xml"); '
    'print("\\nARGUS_JUNIT_BASE64:"+base64.b64encode(p.read_bytes()).decode(),flush=True) if p.is_file() else None; '
    'sys.exit(code)'
)


def scratch_root() -> Path:
    root = Path(os.environ.get('ARGUS_SCRATCH', str(Path.home() / '.hermes/cache/scratch'))).expanduser().resolve()
    if root == Path('/tmp') or Path('/tmp') in root.parents or root == Path('/var/tmp') or Path('/var/tmp') in root.parents:
        raise ValueError('Host temporary files must use a scratch directory, not /tmp or /var/tmp')
    root.mkdir(parents=True, exist_ok=True)
    return root


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Recorder:
    def __init__(self, output: Path):
        self.output = output
        output.mkdir(parents=True, exist_ok=True)
        self.counter = 0

    def run(self, label, command, *, cwd=None, timeout=60, check=True):
        self.counter += 1
        command = [str(x) for x in command]
        start = time.monotonic()
        stamp = datetime.now(timezone.utc).isoformat()
        # Do not propagate host credentials, git overrides or Docker auth config.
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
               'HOME': str(scratch_root()), 'TMPDIR': str(scratch_root()),
               'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
               'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
               'GIT_TERMINAL_PROMPT': '0', 'PYTHONDONTWRITEBYTECODE': '1',
               'DOCKER_CONFIG': str(scratch_root() / 'argus-empty-docker-config')}
        out = self.output / (label + '.stdout.txt')
        err = self.output / (label + '.stderr.txt')
        interrupted = False
        with out.open('wb') as stdout, err.open('wb') as stderr:
            try:
                result = subprocess.run(command, cwd=cwd, env=env, stdout=stdout,
                                        stderr=stderr, timeout=timeout, check=False)
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = 124
            except KeyboardInterrupt:
                code = 130
                interrupted = True
            except OSError as exc:
                stderr.write(str(exc).encode())
                code = 127
        entry = {'command': command, 'cwd': str(cwd) if cwd else None,
                 'started_utc': stamp, 'timeout_seconds': timeout,
                 'seconds': time.monotonic() - start, 'exit_code': code,
                 'stdout': out.name, 'stderr': err.name, 'label': label}
        with (self.output / 'commands.jsonl').open('a') as log:
            log.write(json.dumps(entry, ensure_ascii=False) + '\n')
        if interrupted:
            raise KeyboardInterrupt
        if check and code:
            raise RuntimeError(f'{label}: exit {code}; see {err}')
        return code, out.read_text(errors='replace'), err.read_text(errors='replace')


def validate_source(source: Path, rec: Recorder):
    source = source.resolve(strict=True)
    _, toplevel, _ = rec.run('source-root', ['git', '-C', source, 'rev-parse', '--show-toplevel'])
    if Path(toplevel.strip()).resolve() != source:
        raise ValueError('Source must be the repository root, not a subdirectory')
    _, head, _ = rec.run('source-head', ['git', '-C', source, 'rev-parse', 'HEAD'])
    if head.strip() != SHA:
        raise ValueError(f'Source SHA mismatch: expected {SHA}, found {head.strip()}')
    _, status, _ = rec.run('source-status', ['git', '-C', source, 'status', '--porcelain=v1', '--untracked-files=all'])
    if status.strip():
        raise ValueError('Source is dirty (including untracked files); refusing to modify or use it')
    for parent, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = [d for d in dirs if d != '.git']
        for name in files + dirs:
            if name == '.env' or (name.startswith('.env.') and name not in {'.env.example', '.env.sample', '.env.template'}):
                raise ValueError(f'Refusing source containing .env material: {Path(parent) / name}')
    return source


def extract_archive(archive: Path, destination: Path):
    """Only regular files/directories; disallow links/devices/traversal, then data-filter."""
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tf:
        members = tf.getmembers()
        for member in members:
            p = PurePosixPath(member.name)
            if p.is_absolute() or '..' in p.parts or '.git' in p.parts or not (member.isfile() or member.isdir()):
                raise ValueError(f'Unsafe archive member: {member.name}')
            if p.name == '.env' or (p.name.startswith('.env.') and p.name not in {'.env.example', '.env.sample', '.env.template'}):
                raise ValueError('Archive contains .env material')
        tf.extractall(destination, members=members, filter='data')
    # Git modes remain intact; ensure non-root runtime can traverse the host temp root.
    destination.chmod(0o755)


def build_command(image: str, context: Path):
    # Build contacts only public PyPI; host networking avoids bridge DNS failures.
    # Runtime is independently forced to --network none below.
    return ['docker', 'build', '--network', 'host', '--progress=plain', '--tag', image, context]


def runtime_command(name: str, image: str, source: Path, command):
    if ',' in str(source) or '\n' in str(source):
        raise ValueError('Unsupported mount path')
    return ['docker', 'run', '--name', name, '--network', 'none', '--read-only',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--user', '65534:65534', '--pids-limit', '128', '--memory', '1g', '--cpus', '2',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m,mode=1777',
            '--mount', f'type=bind,src={source},dst=/src,readonly', '-w', '/src',
            '-e', 'HOME=/tmp', '-e', 'AI_PROVIDER=none', '-e', 'PYTHONDONTWRITEBYTECODE=1',
            image, *command]


def extract_junit(stdout: str, destination: Path):
    # tmpfs vanishes on container exit: export bytes while still running, not docker cp.
    reports = [line[len(JUNIT_PREFIX):] for line in stdout.splitlines() if line.startswith(JUNIT_PREFIX)]
    if len(reports) != 1:
        raise ValueError('Expected exactly one JUnit export from the runtime wrapper')
    destination.write_bytes(base64.b64decode(reports[0], validate=True))


def check_junit(path: Path):
    root = ET.parse(path).getroot()
    nodes = []
    for case in root.iter('testcase'):
        if any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped')):
            raise ValueError('JUnit contains a failure, error, or skipped test')
        nodes.append(case.attrib['classname'].replace('.', '/') + '.py::' + case.attrib['name'])
    if len(nodes) != 18 or len(set(nodes)) != 18 or set(nodes) != set(NODES):
        raise ValueError(f'JUnit selection mismatch: {nodes}')
    return nodes


def execute(source_arg: Path | None, output: Path) -> int:
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output directory must be new or empty; never overwrite old evidence')
    if len(NODES) != 18 or len(set(NODES)) != 18:
        raise ValueError('Selection must contain exactly 18 unique upstream nodeids')
    rec = Recorder(output)
    run_id = uuid.uuid4().hex
    image = f'argus-boundary-audit:{run_id}'
    names = []
    manifest = {'schema_version': 1, 'upstream_url': URL, 'source_sha': SHA,
                'runner_argv': sys.argv, 'runner_cwd': str(Path.cwd()),
                'base_image': BASE, 'run_id': run_id, 'image_tag': image,
                'test_nodes': NODES, 'test_count': len(NODES),
                'host': {'python': sys.version, 'platform': platform.platform()},
                'started_utc': datetime.now(timezone.utc).isoformat(),
                'success': False, 'cleanup_verified': False,
                'artifact_sha256': {name: digest(HERE / name) for name in
                                    ['reproduce.py', 'Dockerfile', 'requirements.lock', 'selection.json',
                                     'test_reproduce.py', 'reproduce.ipynb', 'README.md']}}
    build_attempted = False
    try:
        with tempfile.TemporaryDirectory(prefix='argus-boundary-', dir=scratch_root()) as temp:
            temp = Path(temp)
            # Parent directory must be traversable to UID 65534 for bind mounting.
            temp.chmod(0o755)
            rec.run('docker-version', ['docker', 'version'])
            if source_arg is None:
                source = temp / 'checkout'
                rec.run('clone-init', ['git', 'init', '-q', source])
                rec.run('clone-fetch', ['git', '-C', source, '-c', 'core.hooksPath=/dev/null',
                                      'fetch', '--depth=1', URL, SHA], timeout=180)
                rec.run('clone-checkout', ['git', '-C', source, '-c', 'core.hooksPath=/dev/null',
                                         'checkout', '--detach', SHA])
            else:
                source = source_arg
            source = validate_source(source, rec)
            manifest['source_path'] = str(source)
            _, tree, _ = rec.run('source-tree', ['git', '-C', source, 'rev-parse', 'HEAD^{tree}'])
            manifest['source_tree'] = tree.strip()
            archive = temp / 'upstream.tar'
            rec.run('source-archive', ['git', '-C', source, 'archive', '--format=tar', '-o', archive, SHA])
            manifest['source_archive_sha256'] = digest(archive)
            exported = temp / 'source'
            extract_archive(archive, exported)
            manifest['source_file_sha256'] = {str(p.relative_to(exported)): digest(p)
                                              for p in sorted(exported.rglob('*')) if p.is_file()}
            # Source, .git, and user config never enter build context.
            context = temp / 'build'
            context.mkdir()
            for name in ('Dockerfile', 'requirements.lock'):
                shutil.copyfile(HERE / name, context / name)
            build_attempted = True
            rec.run('docker-build', build_command(image, context), timeout=900)
            _, inspected, _ = rec.run('image-inspect', ['docker', 'image', 'inspect', image])
            manifest['image_id'] = json.loads(inspected)[0]['Id']
            manifest['image_config_user'] = json.loads(inspected)[0]['Config']['User']
            def runtime(label, command, timeout=180):
                name = f'argus-boundary-{run_id}-{label}'
                names.append(name)
                return rec.run(label, runtime_command(name, image, exported, command), timeout=timeout)
            env_code = ('import json,sys,platform,os; '
                        'print(json.dumps({"python":sys.version,"platform":platform.platform(),'
                        '"uid":os.getuid(),"gid":os.getgid(),"ai_provider":os.environ.get("AI_PROVIDER")},indent=2))')
            _, environment, _ = runtime('environment', ['python', '-c', env_code])
            manifest['runtime_environment'] = json.loads(environment)
            _, freeze, _ = runtime('pip-freeze', ['python', '-m', 'pip', 'freeze'])
            locked = {x.strip().lower().replace('_', '-') for x in (HERE / 'requirements.lock').read_text().splitlines() if x and not x.startswith('#')}
            actual = {x.strip().lower().replace('_', '-') for x in freeze.splitlines() if x.strip()}
            if locked != actual:
                raise ValueError(f'Runtime freeze differs from lock: {locked ^ actual}')
            options = ['python', '-m', 'pytest', '-p', 'no:cacheprovider', '--basetemp=/tmp/pytest', '--color=no']
            _, collected, _ = runtime('collect', [*options, '--collect-only', '-q', *NODES])
            collected_nodes = [line.strip() for line in collected.splitlines() if line.startswith('tests/') and '::' in line]
            if len(collected_nodes) != 18 or set(collected_nodes) != set(NODES):
                raise ValueError('Collection did not match exactly 18 selected nodeids')
            manifest['collected_nodeids'] = collected_nodes
            _, pytest_stdout, _ = runtime('pytest', ['python', '-c', JUNIT_EXPORT, *options,
                                                    '-vv', '--tb=long', '--junitxml=/tmp/junit.xml', *NODES])
            name = names[-1]
            extract_junit(pytest_stdout, output / 'junit.xml')
            manifest['junit_transport'] = 'base64 stdout export before tmpfs unmount; original bytes preserved'
            _, inspection, _ = rec.run('runtime-inspect', ['docker', 'inspect', name])
            manifest['runtime_container_id'] = json.loads(inspection)[0]['Id']
            manifest['passed_nodeids'] = check_junit(output / 'junit.xml')
            manifest['passed_count'] = len(manifest['passed_nodeids'])
            manifest['success'] = True
    except (Exception, KeyboardInterrupt) as exc:
        manifest['error'] = f'{type(exc).__name__}: {exc}'
        manifest['success'] = False
    finally:
        cleanup = []
        for i, name in enumerate(names):
            rec.run(f'cleanup-container-{i}', ['docker', 'rm', '-f', name], check=False)
            code, text, _ = rec.run(f'verify-container-{i}', ['docker', 'ps', '-a', '--filter', f'name=^/{name}$', '--format', '{{.Names}}'], check=False)
            cleanup.append({'container': name, 'absent': code == 0 and not text.strip()})
        if build_attempted:
            rec.run('cleanup-image', ['docker', 'image', 'rm', image], check=False)
            code, text, _ = rec.run('verify-image', ['docker', 'image', 'ls', '--filter', f'reference={image}', '--format', '{{.ID}}'], check=False)
            cleanup.append({'image': image, 'absent': code == 0 and not text.strip()})
        manifest['cleanup'] = cleanup
        manifest['cleanup_verified'] = all(x['absent'] for x in cleanup)
        manifest['success'] = manifest['success'] and manifest['cleanup_verified']
        manifest['ended_utc'] = datetime.now(timezone.utc).isoformat()
        manifest['evidence_sha256'] = {p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file() and p.name != 'manifest.json'}
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'success': manifest['success'], 'passed_count': manifest.get('passed_count', 0),
                      'cleanup_verified': manifest['cleanup_verified'], 'manifest': str(output / 'manifest.json')}, indent=2))
    return 0 if manifest['success'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Existing clean checkout at the fixed SHA; otherwise fetch into scratch')
    parser.add_argument('--output', type=Path, default=HERE / 'results' / ('run-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')))
    args = parser.parse_args()
    # SIGTERM, like Ctrl-C, must pass through finally and clean this run only.
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    return execute(args.source, args.output.resolve())


if __name__ == '__main__':
    sys.exit(main())

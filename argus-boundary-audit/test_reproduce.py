"""Runner-only stdlib tests; never substitute for upstream Argus tests."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import reproduce as r


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=r.scratch_root())
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_fixed_selection_has_18_unique_nodes(self):
        self.assertEqual(len(r.NODES), 18)
        self.assertEqual(len(set(r.NODES)), 18)
        self.assertTrue(all(n.startswith('tests/') and '::test_' in n for n in r.NODES))

    def test_runtime_is_isolated(self):
        cmd = r.runtime_command('audit-test', 'image-test', self.root, ['python', '-V'])
        for flag, value in [('--network', 'none'), ('--cap-drop', 'ALL'),
                            ('--user', '65534:65534'), ('--security-opt', 'no-new-privileges'),
                            ('--memory', '1g'), ('--cpus', '2'), ('--pids-limit', '128')]:
            self.assertEqual(cmd[cmd.index(flag) + 1], value)
        self.assertIn('--read-only', cmd)
        mounts = [cmd[i + 1] for i, x in enumerate(cmd) if x == '--mount']
        self.assertEqual(len(mounts), 1)
        self.assertIn('readonly', mounts[0])
        self.assertNotIn('/var/run/docker.sock', ' '.join(cmd))

    def archive(self, name, kind=tarfile.REGTYPE):
        output = self.root / 'test.tar'
        with tarfile.open(output, 'w') as tf:
            item = tarfile.TarInfo(name)
            item.type = kind
            if kind == tarfile.SYMTYPE:
                item.linkname = '/etc/passwd'
            tf.addfile(item, io.BytesIO(b''))
        return output

    def test_archive_rejects_traversal(self):
        with self.assertRaises(ValueError):
            r.extract_archive(self.archive('../escape'), self.root / 'extracted')
        self.assertFalse((self.root.parent / 'escape').exists())

    def test_archive_rejects_links(self):
        with self.assertRaises(ValueError):
            r.extract_archive(self.archive('link', tarfile.SYMTYPE), self.root / 'extracted')

    def test_archive_extracts_normal_file(self):
        r.extract_archive(self.archive('normal.txt'), self.root / 'extracted')
        self.assertTrue((self.root / 'extracted/normal.txt').is_file())

    def test_source_rejects_env_even_when_ignored(self):
        repo = self.make_repo()
        (repo / '.gitignore').write_text('.env\n')
        self.git(repo, 'add', '.gitignore')
        self.git(repo, 'commit', '-qm', 'ignore')
        (repo / '.env').write_text('not-a-real-secret')
        with patch.object(r, 'SHA', self.git(repo, 'rev-parse', 'HEAD').stdout.strip()):
            with self.assertRaisesRegex(ValueError, '.env'):
                r.validate_source(repo, r.Recorder(self.root / 'logs'))

    def git(self, repo, *args):
        return subprocess.run(['git', '-c', 'user.name=Runner test', '-c',
                               'user.email=runner@example.invalid', *args], cwd=repo,
                              capture_output=True, text=True, check=True, timeout=20)

    def make_repo(self):
        repo = self.root / 'repo'
        repo.mkdir()
        self.git(repo, 'init', '-q')
        (repo / 'file.txt').write_text('original')
        self.git(repo, 'add', 'file.txt')
        self.git(repo, 'commit', '-qm', 'initial')
        return repo

    def test_source_rejects_dirty_and_wrong_sha(self):
        repo = self.make_repo()
        with self.assertRaisesRegex(ValueError, 'SHA'):
            r.validate_source(repo, r.Recorder(self.root / 'logs1'))
        with patch.object(r, 'SHA', self.git(repo, 'rev-parse', 'HEAD').stdout.strip()):
            (repo / 'file.txt').write_text('dirty')
            with self.assertRaisesRegex(ValueError, 'dirty'):
                r.validate_source(repo, r.Recorder(self.root / 'logs2'))

    def test_source_rejects_subdirectory(self):
        repo = self.make_repo()
        nested = repo / 'nested'
        nested.mkdir()
        with patch.object(r, 'SHA', self.git(repo, 'rev-parse', 'HEAD').stdout.strip()):
            with self.assertRaisesRegex(ValueError, 'root'):
                r.validate_source(nested, r.Recorder(self.root / 'logs'))

    def test_build_network_is_explicit_and_not_runtime(self):
        command = r.build_command('test-image', self.root)
        self.assertEqual(command[command.index('--network') + 1], 'host')
        runtime = r.runtime_command('audit-test', 'test-image', self.root, ['python', '-V'])
        self.assertEqual(runtime[runtime.index('--network') + 1], 'none')

    def test_source_clean_accepted(self):
        repo = self.make_repo()
        with patch.object(r, 'SHA', self.git(repo, 'rev-parse', 'HEAD').stdout.strip()):
            r.validate_source(repo, r.Recorder(self.root / 'logs'))

    def test_recorder_keeps_nonzero_and_timeout_output(self):
        recorder = r.Recorder(self.root / 'logs')
        with self.assertRaises(RuntimeError):
            recorder.run('failure', [sys.executable, '-c',
                         'import sys; print("out"); print("err",file=sys.stderr); sys.exit(7)'])
        with self.assertRaises(RuntimeError):
            recorder.run('timeout', [sys.executable, '-c',
                         'import time; print("before",flush=True); time.sleep(5)'], timeout=.1)
        entries = [json.loads(x) for x in (self.root / 'logs/commands.jsonl').read_text().splitlines()]
        self.assertEqual(entries[0]['exit_code'], 7)
        self.assertEqual(entries[1]['exit_code'], 124)
        self.assertIn('before', (self.root / 'logs/timeout.stdout.txt').read_text())
        self.assertEqual((self.root / 'logs/failure.stderr.txt').read_text().strip(), 'err')

    def test_junit_export_roundtrip_and_rejects_missing(self):
        import base64
        report = self.root / 'report.xml'
        raw = b'<testsuites/>\n'
        text = 'actual pytest output\nARGUS_JUNIT_BASE64:' + base64.b64encode(raw).decode() + '\n'
        r.extract_junit(text, report)
        self.assertEqual(report.read_bytes(), raw)
        with self.assertRaises(ValueError):
            r.extract_junit('no exported report', report)

    def test_junit_requires_exact_selected_passes(self):
        xml = '<testsuites><testsuite>' + ''.join(
            '<testcase classname="' + n.split('::')[0][:-3].replace('/', '.') +
            '" name="' + n.split('::')[1] + '"/>' for n in r.NODES) + '</testsuite></testsuites>'
        report = self.root / 'junit.xml'
        report.write_text(xml)
        self.assertEqual(r.check_junit(report), r.NODES)
        report.write_text(xml.replace('/>', '><skipped/></testcase>', 1))
        with self.assertRaises(ValueError):
            r.check_junit(report)

    def test_notebook_is_local_and_compiles(self):
        nb = json.loads((r.HERE / 'reproduce.ipynb').read_text())
        self.assertEqual(nb['nbformat'], 4)
        for cell in nb['cells']:
            if cell['cell_type'] == 'code':
                self.assertEqual(cell['outputs'], [])
                compile(''.join(cell['source']), '<notebook>', 'exec')


if __name__ == '__main__':
    unittest.main(verbosity=2)

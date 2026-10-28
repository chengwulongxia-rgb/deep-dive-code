import importlib.util
import json
import pathlib
import tempfile
import unittest

class GenerateTests(unittest.TestCase):
    def test_import_is_stdlib_safe_and_failure_exports(self):
        self.assertIsNotNone(importlib.util.find_spec('generate'), 'generate module required')
        import generate
        self.assertEqual(generate.PARAMETERS['seed'], 42)
        self.assertEqual(len(generate.MODEL_REVISION), 40)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):
                generate.run(d, preflight=lambda: (_ for _ in ()).throw(RuntimeError('not L4')))
            self.assertEqual(json.loads((pathlib.Path(d)/'metrics.json').read_text())['status'], 'failed')
            self.assertTrue((pathlib.Path(d)/'result.zip').exists())
            self.assertTrue((pathlib.Path(d)/'manifest.json').exists())

class Response:
    def __init__(self, status, body=None, content=b''):
        self.status_code, self.body, self.content = status, body, content
    def json(self): return self.body

class FakeSession:
    def __init__(self):
        self.objects, self.uploads, self.reads = {}, [], []
        self.corrupt = False
        self.timeout_after_commit = False
    def post(self, url, params, data, headers, timeout):
        name = params['name']
        self.uploads.append(name)
        assert params['ifGenerationMatch'] == '0'
        if name in self.objects: return Response(412)
        generation = str(len(self.objects)+1)
        self.objects[name] = (generation, data)
        if self.timeout_after_commit:
            self.timeout_after_commit = False
            raise TimeoutError('ambiguous upload timeout')
        return Response(200, {'generation': generation})
    def get(self, url, params=None, timeout=None):
        from urllib.parse import unquote
        name = unquote(url.split('/o/')[1])
        if name not in self.objects: return Response(404)
        generation, data = self.objects[name]
        if not params or params.get('alt') != 'media': return Response(200, {'generation':generation})
        assert params['generation'] == generation
        self.reads.append((name,generation))
        return Response(200, content=b'bad' if self.corrupt else data)

class StorageTests(unittest.TestCase):
    def test_unsafe_prefixes_and_names_rejected(self):
        from gcs_store import GCSStore
        for prefix in ['', '../bad', '/absolute', 'runs//bad', 'runs/./x']:
            with self.assertRaises(ValueError): GCSStore('example-bucket', prefix, FakeSession())
        store = GCSStore('example-bucket','runs/x',FakeSession())
        with self.assertRaises(ValueError): store.put_verified('../escape', b'x')

    def test_timeout_recovers_exact_generation_without_duplicate_upload(self):
        from gcs_store import GCSStore
        s = FakeSession()
        s.timeout_after_commit = True
        r = GCSStore('example-bucket','runs/x',s).put_verified('a',b'abc')
        self.assertEqual(r['generation'],'1')
        self.assertEqual(len(s.uploads),1)

    def test_conflict_never_overwrites(self):
        from gcs_store import GCSStore
        s = FakeSession()
        store = GCSStore('example-bucket','runs/x',s)
        store.put_verified('a',b'abc')
        with self.assertRaises(RuntimeError): store.put_verified('a',b'abc')
        self.assertEqual(s.objects['runs/x/a'][1],b'abc')

    def test_checksum_failure_never_writes_success(self):
        from gcs_store import GCSStore
        s = FakeSession()
        s.corrupt = True
        with self.assertRaises(RuntimeError): GCSStore('example-bucket','runs/x',s).put_verified('a',b'abc')
        self.assertFalse(any(n.endswith('SUCCESS.json') for n in s.uploads))

    def test_failed_manifest_prevents_any_upload(self):
        from gcs_store import GCSStore
        s = FakeSession()
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d)
            for name in ['image.png','parameters.json','metrics.json','manifest.json']:
                (p/name).write_text('{"status":"failed"}')
            with self.assertRaises(ValueError): GCSStore('example-bucket','runs/x',s).publish(p)
        self.assertEqual(s.uploads,[])

    def test_put_and_publish_success_order(self):
        self.assertIsNotNone(importlib.util.find_spec('gcs_store'), 'storage module required')
        from gcs_store import GCSStore
        s = FakeSession()
        store = GCSStore('example-bucket', 'runs/test/', session=s)
        r = store.put_verified('probe', b'abc')
        self.assertEqual(r['generation'], '1')
        self.assertEqual(r['object'], 'runs/test/probe')
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d)
            import hashlib
            for name in ['image.png','parameters.json']: (p/name).write_bytes(b'payload')
            (p/'metrics.json').write_text('{"status":"success"}')
            entries = {f.name:{'sha256':hashlib.sha256(f.read_bytes()).hexdigest(), 'bytes':f.stat().st_size} for f in p.iterdir()}
            (p/'manifest.json').write_text(json.dumps({'status':'success','files':entries}))
            receipt = store.publish(p)
            self.assertEqual([n.rsplit('/',1)[1] for n in s.uploads][-2:], ['manifest.json','SUCCESS.json'])
            self.assertIn('SUCCESS.json', receipt['objects'])
            self.assertEqual(s.reads[-1][0], 'runs/test/SUCCESS.json')

class NotebookTests(unittest.TestCase):
    def test_notebook_embeds_sources_and_valid_python(self):
        p = pathlib.Path(__file__).parent
        self.assertTrue((p/'lifecycle.ipynb').exists(), 'self-contained notebook required')
        nb = json.loads((p/'lifecycle.ipynb').read_text())
        self.assertEqual(nb['nbformat'],4)
        source = '\n'.join(''.join(c['source']) for c in nb['cells'])
        import ast
        setup = ast.parse(''.join(nb['cells'][1]['source']))
        embedded = next(ast.literal_eval(n.value) for n in setup.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SOURCES' for t in n.targets))
        for name in ['generate.py','gcs_store.py','requirements.txt','bootstrap.py']:
            self.assertEqual(embedded[name],(p/name).read_text())
        code = [c for c in nb['cells'] if c['cell_type']=='code']
        for c in code:
            self.assertTrue(c['id'])
            self.assertEqual(c['outputs'],[])
            compile(''.join(c['source']),'<cell>','exec')
        self.assertIn('auth.authenticate_user()',source)
        self.assertNotIn('runtime.unassign',source)
        self.assertIn('auth.authenticate_user()', ''.join(nb['cells'][2]['source']))
        self.assertIn("WORK/'bootstrap.py'", ''.join(nb['cells'][3]['source']))

if __name__ == '__main__': unittest.main()

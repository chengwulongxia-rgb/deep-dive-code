"""Offline tests: execute only native pure Notebook cells; never credential/API IO."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

def namespace():
    path = ROOT / 'drcd_api.ipynb'
    ns = {}
    if path.exists():
        for cell in json.loads(path.read_text())['cells']:
            if 'api-pure' in cell.get('metadata', {}).get('tags', []):
                exec(''.join(cell['source']), ns)
    return ns

class BudgetTests(unittest.TestCase):
    def test_restart_preserves_settled_and_pending_fixed_cap(self):
        ns = namespace()
        self.assertIn('BudgetLedger', ns, 'native persistent budget ledger missing')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'budget.json'
            with ns['BudgetLedger'](path) as ledger:
                a = ledger.reserve('gpt-6.1-terra', 100, {'run_id': 'one'})
                ledger.settle(a, {'input_tokens': 100, 'output_tokens': 20,
                    'total_tokens': 120, 'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0},
                    'output_tokens_details': {'reasoning_tokens': 10}})
                b = ledger.reserve('gpt-6-luna', 100, {'run_id': 'one'})
                used = ledger.exposure()
            with ns['BudgetLedger'](path) as ledger:
                self.assertEqual(ledger.exposure(), used)
                self.assertEqual(ledger.data['cap_nano_usd'], 800_000_000)
                self.assertEqual(ledger.data['entries'][a]['actual_nano_usd'], 200_000)
                self.assertEqual(ledger.data['entries'][b]['state'], 'pending')
                with self.assertRaises(ns['APIStop']):
                    ledger.reserve('gpt-6-luna', 100, {'run_id': 'two'})

def usage(i=100, o=20):
    return {'input_tokens': i, 'output_tokens': o, 'total_tokens': i + o,
            'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0},
            'output_tokens_details': {'reasoning_tokens': 10}}

def response():
    return {'id': 'fixture_not_inference', 'model': 'gpt-6.1-terra', 'status': 'completed',
            'service_tier': 'default', 'usage': usage(),
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '甲'}]}]}

class RequestSafetyTests(unittest.TestCase):
    def test_exact_boundary_and_one_nano_short_gate_sender(self):
        ns = namespace()
        self.assertIn('paid_request', ns, 'reserve-before-send wrapper missing')
        for short, expected_calls in [(False, 1), (True, 0)]:
            with self.subTest(short=short), tempfile.TemporaryDirectory() as tmp:
                with ns['BudgetLedger'](Path(tmp) / 'budget.json') as ledger:
                    amount = ns['reservation']('gpt-6.1-terra', 100)
                    previous = 800_000_000 - amount + int(short)
                    ledger.data['entries']['prior_run'] = {'state': 'settled',
                        'reserve_nano_usd': previous, 'actual_nano_usd': previous}
                    ledger.save()
                    calls = []
                    def sender(endpoint, payload):
                        calls.append(endpoint)
                        return response()
                    invoke = lambda: ns['paid_request'](ledger, sender, {'model': 'gpt-6.1-terra'}, 100, {'run_id': 'new'})
                    if short:
                        with self.assertRaises(ns['APIStop']): invoke()
                    else:
                        result = invoke()
                        self.assertEqual(result['cost_nano_usd'], 200_000)
                    self.assertEqual(len(calls), expected_calls)

    def test_ambiguous_http_timeout_and_usage_keep_reserve_and_halt(self):
        ns = namespace()
        self.assertIn('paid_request', ns)
        invalid = []
        for field, value in [('input_tokens', -1), ('output_tokens', 501), ('input_tokens', True), ('total_tokens', 1)]:
            u = usage(); u[field] = value; invalid.append(u)
        for field in ['cached_tokens', 'cache_write_tokens']:
            u = usage(); u['input_tokens_details'][field] = 1; invalid.append(u)
        invalid += [None, {}, {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120}]
        cases = [TimeoutError(), RuntimeError('must_not_be_saved')] + invalid
        for case in cases:
            with self.subTest(case=type(case).__name__), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'budget.json'
                calls = []
                with ns['BudgetLedger'](path) as ledger:
                    def sender(endpoint, payload):
                        calls.append(1)
                        if isinstance(case, Exception): raise case
                        return dict(response(), usage=case)
                    with self.assertRaises(ns['APIStop']):
                        ns['paid_request'](ledger, sender, {'model': 'gpt-6.1-terra'}, 100, {'run_id': 'a'})
                    amount = ns['reservation']('gpt-6.1-terra', 100)
                    self.assertEqual(ledger.exposure(), amount)
                    self.assertTrue(ledger.data['halted'])
                with ns['BudgetLedger'](path) as ledger:
                    with self.assertRaises(ns['APIStop']):
                        ns['paid_request'](ledger, sender, {'model': 'gpt-6.1-terra'}, 100, {'run_id': 'b'})
                self.assertEqual(len(calls), 1)
                self.assertNotIn('must_not_be_saved', path.read_text())

    def test_counter_is_cached_and_separate_from_inference(self):
        ns = namespace()
        self.assertIn('input_count', ns)
        with tempfile.TemporaryDirectory() as tmp:
            with ns['BudgetLedger'](Path(tmp) / 'budget.json') as ledger:
                calls = []
                def counter(endpoint, payload):
                    calls.append((endpoint, payload))
                    return {'object': 'response.input_tokens', 'input_tokens': 100}
                payload = {'model': 'gpt-6.1-terra', 'input': [{'role': 'user', 'content': '原題'}]}
                self.assertEqual(ns['input_count'](ledger, counter, payload), 100)
                self.assertEqual(ns['input_count'](ledger, counter, payload), 100)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][0], '/responses/input_tokens')
                self.assertEqual(ledger.data['metadata_request_count'], 1)
                self.assertEqual(ledger.data['inference_request_count'], 0)
                with self.assertRaises(ns['APIStop']): ns['reservation']('gpt-6.1-terra', 8192)

    def test_pending_reservation_is_durable_before_sender(self):
        ns = namespace()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'budget.json'
            with ns['BudgetLedger'](path) as ledger:
                def sender(endpoint, payload):
                    durable = json.loads(path.read_text())
                    self.assertEqual(durable['inference_request_count'], 1)
                    self.assertEqual(len(durable['entries']), 1)
                    self.assertEqual(next(iter(durable['entries'].values()))['state'], 'pending')
                    return response()
                ns['paid_request'](ledger, sender, {'model': ns['MODELS'][0]}, 100, {'run_id': 'a'})

    def test_counter_error_halts_without_inference(self):
        ns = namespace()
        with tempfile.TemporaryDirectory() as tmp:
            with ns['BudgetLedger'](Path(tmp) / 'budget.json') as ledger:
                calls = []
                def sender(endpoint, payload):
                    calls.append(endpoint)
                    raise TimeoutError('not retained')
                with self.assertRaises(ns['APIStop']):
                    ns['input_count'](ledger, sender, {'model': ns['MODELS'][0], 'input': []})
                self.assertEqual(calls, ['/responses/input_tokens'])
                self.assertTrue(ledger.data['halted'])
                self.assertEqual(ledger.data['inference_request_count'], 0)

    def test_before_send_public_hook_can_fail_closed(self):
        ns = namespace()
        with tempfile.TemporaryDirectory() as tmp:
            with ns['BudgetLedger'](Path(tmp) / 'budget.json') as ledger:
                calls = []
                with self.assertRaises(ns['APIStop']):
                    ns['paid_request'](ledger, lambda *a: calls.append(1), {'model': ns['MODELS'][0]}, 100,
                        {'run_id': 'test'}, on_reserved=lambda *a: (_ for _ in ()).throw(OSError('disk')))
                self.assertEqual(calls, [])
                self.assertEqual(ledger.exposure(), ns['reservation'](ns['MODELS'][0], 100))

    def test_ninety_attempt_limit_is_shared_across_runs(self):
        ns = namespace()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'budget.json'
            with ns['BudgetLedger'](path) as ledger:
                ledger.data['inference_request_count'] = 90
                ledger.save()
            with ns['BudgetLedger'](path) as ledger:
                with self.assertRaises(ns['APIStop']): ledger.reserve(ns['MODELS'][0], 100, {'run_id': 'new'})

    def test_exclusive_lock_and_cap_tampering_rejected(self):
        ns = namespace()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'budget.json'
            with ns['BudgetLedger'](path) as ledger:
                with self.assertRaises(BlockingIOError):
                    with ns['BudgetLedger'](path): pass
            data = json.loads(path.read_text()); data['cap_nano_usd'] = 1_000_000_000
            path.write_text(json.dumps(data))
            with self.assertRaises(ns['APIStop']):
                with ns['BudgetLedger'](path): pass

class ProtocolTests(unittest.TestCase):
    def test_manifest_exact_hash_contexts_and_gold_isolation(self):
        ns = namespace()
        self.assertTrue('load_manifest' in ns, 'manifest/payload cells missing')
        manifest, raw = ns['load_manifest'](ROOT / 'results/drcd-cpu/sample-manifest.json')
        self.assertEqual(hashlib.sha256(raw).hexdigest(), '1821c4f1904a51b26a3b87baa2831140064b06f118307bc9882f469fb36d1cf3')
        self.assertEqual([len(manifest[k]) for k in ['dev', 'test', 'warmup']], [8, 24, 1])
        rows = sum((manifest[k] for k in ['dev', 'test', 'warmup']), [])
        self.assertEqual(len({r['context_sha256'] for r in rows}), 33)
        a = rows[0]; b = dict(a, references=['SENTINEL_GOLD'])
        for model in ns['MODELS']:
            payload = ns['payload_for'](a, model)
            self.assertEqual(payload, ns['payload_for'](b, model))
            self.assertNotIn('SENTINEL_GOLD', repr(payload))
            self.assertEqual(payload['input'][1]['content'], '段落：' + a['paragraph'] + '\n問題：' + a['question'])
            self.assertEqual(payload['reasoning'], {'effort': 'none'})
            self.assertEqual(payload['prompt_cache_options'], {'mode': 'explicit', 'ttl': '30m'})
            self.assertEqual(payload['max_output_tokens'], 500)
            self.assertEqual(payload['tools'], [])
            self.assertFalse(payload['store']); self.assertFalse(payload['stream'])
            self.assertNotIn('temperature', payload); self.assertNotIn('seed', payload)
        self.assertEqual(ns['small_ids'](rows, 0), set())

    def test_scoring_matches_cpu_and_failure_denominator(self):
        ns = namespace()
        self.assertTrue('score' in ns, 'native scoring missing')
        self.assertEqual(ns['score'](' 台灣，ABC。 ', ['台灣abc']), (1.0, 1.0))
        self.assertAlmostEqual(ns['score']('甲甲乙', ['甲乙乙'])[1], 2/3)
        self.assertEqual(ns['score']('甲', ['甲'], error='timeout'), (0.0, 0.0))
        self.assertEqual(ns['score']('', ['']), (0.0, 0.0))
        metrics = ns['aggregate']([{'em': 1., 'f1': 1., 'cost_nano_usd': 100, 'duration_seconds': 1, 'error': None}], 24)
        self.assertEqual(metrics['em'], 1/24)
        self.assertEqual(metrics['denominator'], 24)
        self.assertEqual(metrics['collected'], 1)

    def test_dev_selects_usd_not_time_and_all_luna_is_valid(self):
        ns = namespace()
        self.assertTrue('select_decision' in ns, 'dev selection missing')
        manifest, _ = ns['load_manifest'](ROOT / 'results/drcd-cpu/sample-manifest.json')
        records = []
        for row in manifest['dev']:
            for model in ns['MODELS']:
                records.append({'id': row['id'], 'phase': 'dev', 'scheme': 'dev', 'model': model,
                    'em': 1., 'f1': 1., 'duration_seconds': 1 if model == ns['MODELS'][0] else 1000,
                    'cost_nano_usd': 100 if model == ns['MODELS'][0] else 10, 'error': None})
        decision = ns['select_decision'](manifest, records)
        self.assertEqual(decision['small_share'], 1)
        self.assertEqual(decision['label'], 'all_luna')
        plan = ns['test_plan'](manifest, decision)
        self.assertEqual(len(plan), 72)
        for i in range(24):
            group = plan[3*i:3*i+3]
            self.assertEqual({v['scheme'] for v in group}, {'all_terra', 'all_luna', 'frozen_mix'})
            for task in group:
                expected = ns['MODELS'][0] if task['scheme'] == 'all_terra' else ns['MODELS'][1]
                self.assertEqual(task['model'], expected)
        for rec in records: rec['cost_nano_usd'] = 100
        tied = ns['select_decision'](manifest, records)
        self.assertEqual(tied['small_share'], 0)

    def test_replay_accounts_interrupted_inflight_without_private_ledger(self):
        ns = namespace()
        manifest, manifest_bytes = ns['load_manifest'](ROOT / 'results/drcd-cpu/sample-manifest.json')
        task = ns['initial_plan'](manifest)[0]
        row = manifest['warmup'][0]
        inflight = dict(task, run_id='offline_parser_fixture', order=0, answer='', error=None,
            payload=ns['payload_for'](row, task['model']), ledger_entry='pending_fixture',
            reserve_nano_usd=6_780_000, unknown_reserve_nano_usd=6_780_000, cost_nano_usd=None,
            exact_input_tokens=100, started_monotonic=0, duration_seconds=0, usage=None)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / 'sample-manifest.json').write_bytes(manifest_bytes)
            (out / 'raw-generations.jsonl').write_text('')
            (out / 'inflight.json').write_text(json.dumps(inflight))
            report = ns['replay_results'](out, ROOT / 'results/drcd-cpu/sample-manifest.json')
            self.assertEqual(report['status'], 'partial')
            self.assertEqual(report['inference_request_count'], 1)
            self.assertEqual(report['unknown_reserve_nano_usd'], 6_780_000)
            self.assertEqual(report['warmup']['failed_collected'], 1)

    def test_replay_without_results_never_reads_key_ledger_or_http(self):
        from unittest.mock import patch
        import urllib.request
        ns = namespace()
        self.assertTrue('replay_results' in ns, 'offline replay missing')
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(urllib.request, 'urlopen', side_effect=AssertionError('HTTP forbidden')):
                with patch.dict('os.environ', {'DRCD_API_KEY_FILE': '/must-not-read', 'DRCD_API_MAX_USD': '999'}):
                    report = ns['replay_results'](Path(tmp), ROOT / 'results/drcd-cpu/sample-manifest.json')
            self.assertEqual(report['status'], 'not_run')
            self.assertEqual(report['inference_request_count'], 0)
            self.assertEqual(list(Path(tmp).iterdir()), [])

class InfrastructureTests(unittest.TestCase):
    def test_authorization_defaults_and_no_key_read_during_replay(self):
        ns = namespace()
        self.assertTrue('authorize_fresh' in ns, 'explicit fresh authorization missing')
        from unittest.mock import patch
        for value in [None, '1', '1.00', '0.81', 'NaN', '0.79']:
            with self.subTest(value=value):
                env = {} if value is None else {'DRCD_API_MAX_USD': value}
                with patch.dict('os.environ', env, clear=True):
                    with self.assertRaises(ns['APIStop']): ns['authorize_fresh']('fresh')
        with patch.dict('os.environ', {'DRCD_API_MAX_USD': '0.80', 'DRCD_API_KEY_FILE': '/not-read'}, clear=True):
            self.assertEqual(ns['authorize_fresh']('fresh'), Path('/not-read'))
            with self.assertRaises(ns['APIStop']): ns['make_transport']('replay')

    def test_transport_sanitizes_output_and_error_without_secret(self):
        ns = namespace()
        self.assertTrue('safe_reply' in ns, 'response sanitization missing')
        secret = 'unit-test-placeholder-not-a-credential'
        raw = dict(response(), arbitrary_header={'Authorization': secret}, error={'message': secret})
        raw['output'][0]['content'][0]['text'] = 'echo ' + secret
        safe = ns['safe_reply'](raw, secret)
        self.assertNotIn(secret, repr(safe))
        self.assertNotIn('arbitrary_header', safe)
        self.assertNotIn('error', safe)
        self.assertEqual(safe['output'][0]['content'][0]['text'], 'echo [REDACTED]')

    def test_real_transport_http_error_is_sanitized_without_any_network(self):
        import ast
        import io
        import urllib.error
        nb = json.loads((ROOT / 'drcd_api.ipynb').read_text())
        source = ''.join(next(c for c in nb['cells'] if c['id'] == 'official-http')['source'])
        tree = ast.parse(source)
        outer = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'make_transport')
        sender_node = next(n for n in outer.body if isinstance(n, ast.FunctionDef) and n.name == 'sender')
        ns = namespace()
        secret = 'unit-placeholder-not-a-real-key'
        calls = []
        class OfflineOpener:
            def open(self, request, timeout):
                calls.append(request.full_url)
                raise urllib.error.HTTPError(request.full_url, 429, secret, {}, io.BytesIO(secret.encode()))
        ns.update(secret=secret, opener=OfflineOpener())
        exec(compile(ast.Module(body=[sender_node], type_ignores=[]), '<native-http-sender>', 'exec'), ns)
        with tempfile.TemporaryDirectory() as tmp:
            with ns['BudgetLedger'](Path(tmp) / 'budget.json') as ledger:
                with self.assertRaises(ns['APIStop']) as raised:
                    ns['paid_request'](ledger, ns['sender'], {'model': ns['MODELS'][0]}, 100, {'run_id': 'offline'})
                self.assertEqual(raised.exception.record['http_status'], 429)
                self.assertNotIn(secret, repr(raised.exception.record))
                self.assertEqual(ledger.exposure(), ns['reservation'](ns['MODELS'][0], 100))
        self.assertEqual(calls, ['https://api.openai.com/v1/responses'])

    def test_write_failure_never_invokes_sender(self):
        ns = namespace()
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            with ns['BudgetLedger'](Path(tmp) / 'budget.json') as ledger:
                called = []
                with patch.dict(ns, {'atomic_json': lambda *a, **k: (_ for _ in ()).throw(OSError('disk failure'))}):
                    with self.assertRaises(OSError):
                        ns['paid_request'](ledger, lambda *a: called.append(1), {'model': ns['MODELS'][0]}, 100, {'run_id': 'test'})
                self.assertEqual(called, [])

    def test_replay_audits_each_test_route_and_frozen_hash(self):
        ns = namespace()
        self.assertTrue('audit_records' in ns)
        manifest, manifest_bytes = ns['load_manifest'](ROOT / 'results/drcd-cpu/sample-manifest.json')
        by_id = {r['id']: r for k in ['warmup', 'dev', 'test'] for r in manifest[k]}
        # Parsing/routing fixture only: never saved as experimental API results.
        records = []
        def add(task):
            row = by_id[task['id']]
            answer = row['references'][0]
            em, f1 = ns['score'](answer, row['references'])
            records.append(dict(task, order=len(records), payload=ns['payload_for'](row, task['model']),
                answer=answer, error=None, em=em, f1=f1, exact_input_tokens=100, usage=usage(),
                cost_nano_usd=ns['usage_cost'](task['model'], usage(), 100), unknown_reserve_nano_usd=0,
                duration_seconds=0, started_monotonic=ns['time'].monotonic()))
        for task in ns['initial_plan'](manifest): add(task)
        decision = ns['select_decision'](manifest, records)
        for task in ns['test_plan'](manifest, decision): add(task)
        self.assertTrue(ns['audit_records'](manifest, records, decision))
        changed = copy.deepcopy(records); changed[-1]['model'] = 'wrong'
        with self.assertRaises(ns['APIStop']): ns['audit_records'](manifest, changed, decision)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / 'sample-manifest.json').write_bytes(manifest_bytes)
            data = ns['canonical'](decision) + b'\n'
            (out / 'decision.json').write_bytes(data)
            (out / 'decision-sha256.json').write_text(json.dumps({'sha256': hashlib.sha256(data).hexdigest()}))
            raw = out / 'raw-generations.jsonl'
            raw.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records))
            before = raw.read_bytes()
            report = ns['replay_results'](out, ROOT / 'results/drcd-cpu/sample-manifest.json')
            self.assertEqual(report['status'], 'complete')
            self.assertEqual(raw.read_bytes(), before)
            # A failed final attempt still yields 90 rows, but must remain partial.
            failed = copy.deepcopy(records)
            failed[-1].update(answer='', error='inference_failed_or_ambiguous', em=0.0, f1=0.0,
                cost_nano_usd=None, unknown_reserve_nano_usd=1_000_000)
            raw.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in failed))
            partial = ns['replay_results'](out, ROOT / 'results/drcd-cpu/sample-manifest.json')
            self.assertEqual(partial['status'], 'partial')
            self.assertEqual(partial['inference_request_count'], 90)
            (out / 'decision.json').write_text('{}')
            with self.assertRaises(ns['APIStop']): ns['replay_results'](out, ROOT / 'results/drcd-cpu/sample-manifest.json')

if __name__ == '__main__':
    unittest.main()

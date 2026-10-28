import copy
import json
import unittest


class EvaluationTests(unittest.TestCase):
    def test_schema_valid_does_not_mean_correct(self):
        from benchmark import evaluate
        gold = dict(buyer='王小明', vehicle_id='ABC-1234', amount_twd=120000,
                    purchase_date='2026-10-01', condition='used', accessories=[], paid=False)
        wrong = dict(gold, buyer='李小華')
        score = evaluate(json.dumps(wrong, ensure_ascii=False), gold)
        self.assertTrue(score['schema_valid'])
        self.assertEqual(score['field_correct'], 6)
        self.assertFalse(score['object_exact'])

    def test_rejects_duplicate_keys_nonfinite_and_fences(self):
        from benchmark import evaluate
        gold = dict(buyer=None, vehicle_id=None, amount_twd=None, purchase_date=None,
                    condition='unknown', accessories=[], paid=None)
        for raw in ['{"buyer":null,"buyer":"x"}', '{"amount_twd":NaN}', '```json\n{}\n```', '{"amount_twd":1e9999}', '[]']:
            score = evaluate(raw, gold)
            self.assertFalse(score['schema_valid'])
            if raw != '[]':
                self.assertFalse(score['json_valid'])
            self.assertEqual(score['field_correct'], 0)
        self.assertFalse(evaluate(json.dumps(dict(gold, amount_twd=True)), gold)['schema_valid'])

    def test_prompt_never_uses_gold(self):
        from benchmark import build_messages
        case = {'id':'test', 'text':'買方王小明', 'gold':{'secret':'DO_NOT_LEAK'}}
        first = build_messages(case)
        case['gold']={'secret':'OTHER_ANSWER'}
        self.assertEqual(first, build_messages(case))
        self.assertNotIn('DO_NOT_LEAK', json.dumps(first))

    def test_fixture_count_and_all_gold_validate(self):
        from pathlib import Path
        from benchmark import evaluate
        data=json.loads(Path(__file__).with_name('fixtures.json').read_text())['cases']
        self.assertEqual(len(data),24)
        self.assertEqual(len({c['id'] for c in data}),24)
        for case in data:
            self.assertTrue(evaluate(json.dumps(case['gold']),case['gold'])['object_exact'],case['id'])

    def test_b_reuses_a_and_never_retries_semantic_errors(self):
        from benchmark import run_case
        case={'id':'unit-test-only','text':'買方王小明','gold':dict(buyer='王小明',vehicle_id=None,amount_twd=None,purchase_date=None,condition='unknown',accessories=[],paid=None)}
        calls=[]
        wrong=dict(case['gold'],buyer='錯的人')
        def unit_generator(messages, constrained):
            calls.append((messages,constrained))
            return dict(raw=json.dumps(wrong),latency_s=1.0,peak_allocated_bytes=100,peak_reserved_bytes=200)
        records=run_case(case,unit_generator,['A','C'])
        self.assertEqual(len(calls),2)
        b=next(r for r in records if r['arm']=='B')
        self.assertEqual(b['retry_count'],0)
        self.assertEqual(b['latency_s'],1.0)
        self.assertTrue(b['score']['schema_valid'])
        self.assertEqual(b['score']['field_correct'],6)

    def test_b_retries_format_only_once_and_includes_full_cost(self):
        from benchmark import run_case
        case={'id':'unit-test-only','text':'買方王小明','gold':dict(buyer='王小明',vehicle_id=None,amount_twd=None,purchase_date=None,condition='unknown',accessories=[],paid=None)}
        calls=[]
        def unit_generator(messages, constrained):
            calls.append((messages,constrained))
            raw='not JSON' if len(calls)==1 else json.dumps(case['gold'])
            return dict(raw=raw,latency_s=2.0,peak_allocated_bytes=100,peak_reserved_bytes=200)
        records=run_case(case,unit_generator,['A','C'])
        b=next(r for r in records if r['arm']=='B')
        self.assertEqual(len(calls),3)
        self.assertEqual(b['retry_count'],1)
        self.assertEqual(b['latency_s'],4.0)
        self.assertEqual(calls[1][0][-2]['content'],'not JSON')
        self.assertNotIn('expected',calls[1][0][-1]['content'])

    def test_summary_keeps_fixed_field_denominator(self):
        from benchmark import summarize
        record=dict(arm='A',latency_s=2.0,peak_allocated_bytes=100,peak_reserved_bytes=200,retry_count=0,
                    score=dict(json_valid=True,schema_valid=True,field_correct=6,field_total=7,object_exact=False))
        summary=summarize([record])['A']
        self.assertEqual(summary['field_correct'],6)
        self.assertEqual(summary['field_total'],7)
        self.assertEqual(summary['schema_valid_but_wrong'],1)
        self.assertAlmostEqual(summary['field_em'],6/7)
        self.assertEqual(summary['cases'],1)

    def test_notebook_native_cells_preserve_original_scoring(self):
        from pathlib import Path
        here = Path(__file__).resolve().parent
        root = here.parent if here.name == 'legacy_cli' else here
        notebook = json.loads((root / 'experiment.ipynb').read_text())
        from typing import Any
        namespace: dict[str, Any] = {'json': json}
        for cell in notebook['cells']:
            tags = cell.get('metadata', {}).get('tags', [])
            if cell['cell_type'] == 'code' and any(tag in tags for tag in ['data-definition', 'cpu-definition']):
                exec(compile(''.join(cell['source']), '<native notebook cell>', 'exec'), namespace)
        self.assertEqual(namespace['CASES'], json.loads((here / 'fixtures.json').read_text())['cases'])
        evidence = root / 'results/l4-20261028T074106Z'
        rows = [json.loads(line) for line in (evidence / 'results.jsonl').read_text().splitlines()]
        cases = {case['id']: case for case in namespace['CASES']}
        for row in rows:
            self.assertEqual(namespace['evaluate'](row['attempts'][-1]['raw'], cases[row['case_id']]['gold']), row['score'])
        self.assertEqual(namespace['summarize'](rows), json.loads((evidence / 'report.json').read_text())['summary'])

if __name__ == '__main__':
    unittest.main()

"""Offline tests: AST-extract native pure cell; no torch/vLLM/downloads."""
import ast
import hashlib
import json
from pathlib import Path
import unittest
import numpy as np

NOTEBOOK = Path(__file__).with_name('weight_edit_colab.ipynb')

class NotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nb = json.loads(NOTEBOOK.read_text()) if NOTEBOOK.exists() else {'cells': []}
        cls.ns = {}
        for cell in cls.nb['cells']:
            if 'pure_helpers' in cell.get('metadata', {}).get('tags', []):
                tree = ast.parse(''.join(cell['source']))
                exec(compile(tree, '<native-pure-cell>', 'exec'), cls.ns)

    def test_balanced_boxes(self):
        self.assertIn('last_boxed', self.ns, 'native helper cell is missing')
        f = self.ns['last_boxed']
        self.assertEqual(f(r'x \boxed{\frac{1}{2}} y \boxed{3}'), '3')
        self.assertEqual(f(r'\boxed{\frac{1}{2}}'), r'\frac{1}{2}')
        self.assertEqual(f(r'\boxed{7} \boxed{unfinished'), '7')
        self.assertIsNone(f('answer 42'))

    def test_seed_selection_answer_independent(self):
        rows=[dict(unique_id=str(i),problem='p',answer=str(i)) for i in range(500)]
        selected=self.ns['select_questions'](rows)
        changed=[dict(r,answer='secret') for r in rows]
        self.assertEqual([r['unique_id'] for r in selected], [r['unique_id'] for r in self.ns['select_questions'](changed)])
        self.assertEqual(len(selected),16)
        self.assertEqual([int(r['unique_id']) for r in selected], [451,348,227,96,212,395,210,142,70,258,172,209,484,200,50,186])
        self.assertEqual(self.ns['question_seed']('a'),self.ns['question_seed']('a'))
        self.assertNotEqual(self.ns['question_seed']('a'),self.ns['question_seed']('b'))
        self.assertEqual(self.ns['build_prompt']('QUESTION'), 'QUESTION\nPlease reason step by step, and put your final answer within \\boxed{}.')

    def test_sparse_bits_and_errors(self):
        base=np.zeros((4,5),dtype=np.uint16)
        edited=self.ns['sparse_rebuild'](base,np.array([1,8]),np.array([16256,16384],dtype=np.uint16))
        self.assertEqual(int(edited.flat[1]),16256)
        self.assertEqual(np.count_nonzero(base),0)
        for indices in ([1,1],[-1,2],[0,20]):
            with self.assertRaises(ValueError):
                self.ns['sparse_rebuild'](base,np.array(indices),np.zeros(2,dtype=np.uint16))

    def test_bf16_round_even(self):
        bits=np.array([0,16256,16384,49024],dtype=np.uint16)
        np.testing.assert_array_equal(self.ns['bf16_bits'](self.ns['bf16_to_f32'](bits)),bits)
        with self.assertRaises(ValueError):
            self.ns['bf16_bits'](np.array([np.nan]))

    def test_control_norm_support_determinism(self):
        b=self.ns['bf16_bits'](np.ones((8,6),dtype=np.float32))
        e=b.copy(); e[:,[1,4]]=self.ns['bf16_bits'](np.arange(16,dtype=np.float32).reshape(8,2)/64+1)
        c,s=self.ns['random_control'](b,e,np.random.default_rng(20261104))
        c2,s2=self.ns['random_control'](b,e,np.random.default_rng(20261104))
        np.testing.assert_array_equal(c,c2)
        np.testing.assert_array_equal(c[:,[0,2,3,5]],b[:,[0,2,3,5]])
        self.assertAlmostEqual(s['author_norm'],s['requested_norm'])
        self.assertIn('rounding_error',s)

    def test_aggregate_pairing_and_completion(self):
        records=[]
        for a in ('base','author_p50c','random_control'):
            for b in (8192,32768):
                for i in range(16):
                    records.append(dict(arm=a,budget=b,problem_id=str(i),correct=(a!='base'),finish_reason='length',
                        eos_stop=False,thinking_closed=a!='base',boxed='2',token_ids=[1,2],repetition_4gram=0))
        result=self.ns['aggregate'](records)
        self.assertEqual(result['total'],96)
        self.assertEqual(len(result['groups']),6)
        self.assertEqual(sum(p['rescue'] for p in result['pairs']),64)
        self.assertTrue(self.ns['validate_complete'](records,[str(i) for i in range(16)]))
        with self.assertRaises(ValueError): self.ns['validate_complete'](records[:-1],[str(i) for i in range(16)])
        with self.assertRaises(ValueError): self.ns['aggregate'](records+[records[0]])

    def test_strict_grader_missing_last_and_timeout(self):
        import sys
        import types
        from unittest.mock import patch
        namespace=dict(self.ns)
        for c in self.nb['cells']:
            if c['cell_type']=='code':
                tree=ast.parse(''.join(c['source']))
                functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='grade_boxed']
                if functions:
                    exec(compile(ast.Module(body=functions,type_ignores=[]),'<grader-cell>','exec'),namespace)
        calls=[]
        module=types.SimpleNamespace(parse=lambda text,**kwargs: calls.append(text) or [text],
            verify=lambda target,prediction,**kwargs: True,LatexExtractionConfig=lambda: None)
        with patch.dict(sys.modules,{'math_verify':module}):
            self.assertFalse(namespace['grade_boxed']('answer 2','2')['correct'])
            self.assertEqual(calls,[])
            result=namespace['grade_boxed'](r'<think>\\boxed{1} then \\boxed{2}','2')
            self.assertTrue(result['correct'])
            self.assertEqual(result['boxed'],'2')
            def timeout(*args,**kwargs): raise TimeoutError('fixture')
            module.parse=timeout
            failed=namespace['grade_boxed'](r'\\boxed{2}','2')
            self.assertFalse(failed['correct'])
            self.assertEqual(failed['grade_error'],'TimeoutError')

    def test_real_math_verify_positive_negative_and_fraction(self):
        namespace=dict(self.ns)
        for c in self.nb['cells']:
            if c['cell_type']=='code':
                functions=[node for node in ast.parse(''.join(c['source'])).body if isinstance(node,ast.FunctionDef) and node.name=='grade_boxed']
                if functions:exec(compile(ast.Module(body=functions,type_ignores=[]),'<real-grader>','exec'),namespace)
        grade=namespace['grade_boxed']
        self.assertTrue(grade(chr(92)+'boxed{2}','2')['correct'])
        self.assertFalse(grade(chr(92)+'boxed{3}','2')['correct'])
        self.assertTrue(grade(chr(92)+'boxed{'+chr(92)+'frac{1}{2}}',chr(92)+'frac{2}{4}')['correct'])
        self.assertFalse(grade(chr(92)+'boxed{2} then '+chr(92)+'boxed{3}','2')['correct'])
        self.assertNotIn(chr(8),'\n'.join(''.join(c['source']) for c in self.nb['cells']))
        self.assertEqual(self.ns['build_prompt']('Q').count(chr(92)),1)

    def test_every_cell_compiles_native(self):
        for c in self.nb['cells']:
            if c['cell_type']=='code': ast.parse(''.join(c['source']))
        source='\n'.join(''.join(c['source']) for c in self.nb['cells'] if c['cell_type']=='code')
        self.assertNotIn('trust_remote_code=True',source)
        self.assertNotIn("['python', '-c'",source)
        self.assertIn('allow_pickle=False',source)
        self.assertIn('language_model_only=True',source)
        self.assertIn("(dest/'config.json').write_bytes(full_model_config.read_bytes())",source)
        self.assertIn("OUTPUT_DIR = Path('/content/weight-space-programming-output')",source)

    def test_saved_outputs_preserve_both_actual_runs(self):
        import gzip
        folder=NOTEBOOK.parent/'results/l4-20261104'
        def rows(name):return [json.loads(x) for x in gzip.decompress((folder/name).read_bytes()).decode().splitlines() if x.strip()]
        merged=rows('generations.jsonl.gz')
        originals=rows('original-80.jsonl.gz')+rows('completion-16.jsonl.gz')
        self.assertEqual(len(merged),96)
        self.assertEqual(len(originals),96)
        index={(x['arm'],x['budget'],x['problem_id']):x for x in merged}
        self.assertEqual(len(index),96)
        for original in originals:
            published=dict(index[(original['arm'],original['budget'],original['problem_id'])])
            published.pop('source_run')
            self.assertEqual(published,original)
        ids=json.loads((folder/'audit.json').read_text())['selection']['ordered_ids']
        self.assertTrue(self.ns['validate_complete'](merged,ids))

    def test_frozen_gpu_inference_unchanged_and_completion_scoped(self):
        archived=json.loads((NOTEBOOK.parent/'evidence/full-partial-authored.ipynb').read_text())
        for i in range(2,12):self.assertEqual(self.nb['cells'][i]['source'],archived['cells'][i]['source'])
        completion=json.loads((NOTEBOOK.parent/'weight_edit_completion.ipynb').read_text())
        tree=ast.parse(''.join(completion['cells'][1]['source']))
        values={t.id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
            for t in n.targets if isinstance(t,ast.Name) and t.id in ('ARMS','BUDGETS')}
        self.assertEqual(values,{'ARMS':('random_control',),'BUDGETS':(32768,)})
        self.assertIn('RUN_GPU = False',''.join(self.nb['cells'][1]['source']))

if __name__ == '__main__':
    unittest.main()

"""Offline native-cell tests. No model downloads, GPU, auth, or real generation.
Run: .venv/bin/python -m unittest -v test_qwen3_notebook.py
Synthetic IDs below are test fixtures only, never experimental evidence.
"""
import ast
import collections
import hashlib
import json
import math
import os
from pathlib import Path
import random
import tempfile
import unittest
from typing import TypedDict
from datetime import datetime, timezone
import zipfile

os.environ['USE_TF'] = '0'
os.environ['USE_FLAX'] = '0'
import torch
from transformers import SynthIDTextWatermarkingConfig
from lab import real_score as original_score
from real_lab import (sample_plan as original_plan, perturb as original_perturb,
                      make_processor as original_processor, summarize as original_summarize)

ROOT = Path(__file__).resolve().parent
NB = json.loads((ROOT/'qwen3_gpu.ipynb').read_text())
CELLS = {c['metadata']['tags'][0]:c['source'] for c in NB['cells'] if c['cell_type']=='code'}


def helpers():
    ns = dict(TypedDict=TypedDict, torch=torch, random=random, math=math,
              SynthIDTextWatermarkingConfig=SynthIDTextWatermarkingConfig,
              hashlib=hashlib, LENGTHS=[64,128], CALIBRATION_COUNT=24, EVALUATION_COUNT=12,
              CONDITIONS=['clean','truncate_half','delete_10pct','replace_10pct'],
              KEYS=[654,400,836,123,340,443,597,160])
    ns['WRONG_KEYS']=[k+10000 for k in ns['KEYS']]
    exec(CELLS['helpers'],ns)
    exec(CELLS['watermark'],ns)
    return ns


class NotebookTests(unittest.TestCase):
    def test_native_structure_and_clean_outputs(self):
        self.assertEqual(NB['nbformat'],4)
        for c in NB['cells']:
            if c['cell_type']=='code':
                self.assertEqual(c['outputs'],[])
                self.assertIsNone(c['execution_count'])
                tree=ast.parse(c['source'])
                for node in ast.walk(tree):
                    if isinstance(node,ast.ImportFrom):
                        self.assertNotIn(node.module,('main','lab','real_lab','audit','chart'))
                    if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
                        if node.func.attr in ('run','Popen','call','check_call','check_output'):
                            self.assertEqual(c['metadata']['tags'],['installation'])
                        self.assertNotEqual(node.func.attr,'apply_chat_template')
        for source in CELLS.values():
            self.assertNotIn('filterwarnings',source)
            self.assertNotIn('hf_',source)

    def test_loading_and_install_contract(self):
        source=CELLS['model']
        self.assertIn("token=os.environ['HF_TOKEN']",source)
        self.assertIn('trust_remote_code=False',source)
        self.assertIn('use_safetensors=True',source)
        self.assertIn("attn_implementation='eager'",source)
        self.assertIn('eos_token_id=EOS',source)
        self.assertIn("system_site_packages=True",CELLS['installation'])
        self.assertIn("--constraint",CELLS['installation'])
        self.assertIn("with_pip=False",CELLS['installation'])
        self.assertIn("BASE_MATPLOTLIB = im.version('matplotlib')",CELLS['installation'])
        self.assertIn("('matplotlib',BASE_MATPLOTLIB)",CELLS['installation'])
        self.assertIn("'--python', str(ENV/'bin/python')",CELLS['installation'])
        self.assertIn("install_env.pop('HF_TOKEN', None)",CELLS['installation'])
        self.assertIn("USE_TF",CELLS['configuration'])
        self.assertIn("USE_FLAX",CELLS['configuration'])
        self.assertIn("torch.cuda.synchronize()",CELLS['generation'])
        self.assertIn("log.flush()",CELLS['generation'])

    def test_exact_original_helpers(self):
        ns=helpers()
        for filename,names in [('lab.py',['calibrate','real_score']),
                               ('real_lab.py',['sample_plan','perturb','group_key'])]:
            original=ast.parse((ROOT/filename).read_text())
            native=ast.parse(CELLS['helpers'])
            for name in names:
                a=next(n for n in original.body if isinstance(n,ast.FunctionDef) and n.name==name)
                b=next(n for n in native.body if isinstance(n,ast.FunctionDef) and n.name==name)
                self.assertEqual(ast.dump(a),ast.dump(b),name)
        for length in [64,128]:
            for split,count in [('calibration',24),('evaluation',12)]:
                self.assertEqual(ns['sample_plan'](length,split,count),original_plan(length,split,count))
        for condition in ns['CONDITIONS']:
            ids=list(range(128))
            self.assertEqual(ns['perturb'](ids,condition,112345,151643),
                             original_perturb(ids,condition,112345,151643))

    def test_official_processor_and_original_score_parity(self):
        ns=helpers()
        for wrong in [False,True]:
            p=ns['make_processor'](wrong)
            old=original_processor(wrong)
            self.assertTrue(torch.equal(p.sampling_table,old.sampling_table))
            for ids in [[],[1,2,3,4],list(range(50)),[1,2,3,4,5]*15,
                        list(range(10))+[999]+list(range(11,40))]:
                self.assertEqual(ns['real_score'](ids,p,999),original_score(ids,old,999))

    def test_portable_config_survives_generation_config_deepcopy(self):
        from transformers import GenerationConfig
        import copy
        ns=helpers()
        cfg=GenerationConfig(do_sample=True,top_k=40,watermarking_config=ns['watermark_config']())
        p=copy.deepcopy(cfg).watermarking_config.construct_processor(200,'cpu')
        self.assertTrue(torch.equal(p.sampling_table,original_processor().sampling_table))
        self.assertEqual(p.device.type,'cpu')

    def test_model_defaults_cannot_override_original_sampling(self):
        from transformers import GenerationConfig
        from transformers.generation.utils import GenerationMixin
        self.assertIn('use_model_defaults=False',CELLS['generation'])
        model_defaults=GenerationConfig(do_sample=True,temperature=.6,top_p=.95,top_k=20,
                                        eos_token_id=[151645,151643],transformers_version='4.51.0')
        config=GenerationConfig(do_sample=True,temperature=1.,top_p=1.,top_k=40,
                                eos_token_id=151645,pad_token_id=151645)
        class ModelStub(GenerationMixin):
            generation_config=model_defaults
        prepared,_=GenerationMixin._prepare_generation_config(
            ModelStub(), config, use_model_defaults=False)
        self.assertEqual((prepared.temperature,prepared.top_p,prepared.top_k),(1.,1.,40))
        self.assertEqual(prepared.eos_token_id,151645)

    def test_full_synthetic_96_768_audit_chart_bundle(self):
        ns=helpers()
        ns.update(collections=collections, json=json, datetime=datetime, timezone=timezone,
                  Path=Path, zipfile=zipfile, MODE='replay',
                  MODEL_ID='Qwen/Qwen3-4B',REVISION='1cfa9a7208912126459214e8b04321603b3df60c')
        generations=[]; rows=[]
        for length in [64,128]:
            for split,count,origins in [('calibration',24,['plain']),('evaluation',12,['plain','watermarked'])]:
                for plan in ns['sample_plan'](length,split,count):
                    for origin in origins:
                        # Deliberately synthetic independent IDs, NOT model output.
                        rng=random.Random(plan['seed']+(origin=='watermarked'))
                        ids=[rng.randrange(100,9000) for _ in range(length)]
                        sid=f'{length}-{split}-{origin}-{plan["sample_index"]:02d}'
                        g=dict(source_id=sid,source_length=length,split=split,origin=origin,**plan,
                               token_ids=ids,prompt_token_ids=[1,2,3],text='synthetic fixture',generation_seconds=0.,
                               model_id=ns['MODEL_ID'],model_revision=ns['REVISION'],watermark_keys=ns['KEYS'])
                        generations.append(g)
                        for condition in ns['CONDITIONS']:
                            edited,edits=ns['perturb'](ids,condition,plan['seed']+900000,10000)
                            for key,p in ns['processors'].items():
                                score=ns['real_score'](edited,p,99999)
                                rows.append(dict(source_id=sid,source_length=length,split=split,origin=origin,**plan,
                                    condition=condition,perturbation_seed=plan['seed']+900000,
                                    edited_original_positions=edits,key_condition=key,token_ids=edited,
                                    text='synthetic fixture',actual_token_count=len(edited),roundtrip_equal=True,
                                    retokenized_token_ids=edited,generation_seconds=0.,**score,
                                    retokenized_score=score['score'],retokenized_effective_tokens=score['effective_tokens']))
        self.assertEqual(len(generations),96); self.assertEqual(len(rows),768)
        old_summary,old_thresholds=original_summarize(rows)
        roundtrip=[dict(origin=origin,condition=condition,
                        count=sum(r['origin']==origin and r['condition']==condition and r['key_condition']=='correct' for r in rows),
                        mismatches=0) for origin in ['plain','watermarked'] for condition in ns['CONDITIONS']]
        ns.update(generations=generations,rows=rows,VOCAB_SIZE=10000,EOS=99999,
                  params={'fixture_only':True},metadata={'fixture_only':True},
                  saved=dict(summary=old_summary,thresholds=old_thresholds,roundtrip=roundtrip,timing={'fixture_only':True}))
        def save_json(path,value):
            Path(path).write_text(json.dumps(value,allow_nan=False))
        ns['save_json']=save_json
        with tempfile.TemporaryDirectory() as d:
            ns['OUTPUT']=Path(d)
            Path(d,'generations.jsonl').write_text(''.join(json.dumps(g)+'\n' for g in generations))
            exec(CELLS['verification'],ns)
            self.assertEqual(ns['summary'],old_summary)
            self.assertEqual(ns['thresholds'],old_thresholds)
            exec(CELLS['chart'],ns)
            exec(CELLS['bundle'],ns)
            with zipfile.ZipFile(Path(d,'results.zip')) as z:
                self.assertEqual(set(z.namelist()),{'real.json','generations.jsonl','summary.png','provenance.json','audit.json'})
                self.assertIsNone(z.testzip())
            self.assertGreater(Path(d,'summary.png').stat().st_size,10000)
            # Reject mutations of metadata, masks, evidence and decisions.
            fn=ns['audit_measurements']
            for field,value in [('seed',1),('valid_mask',[]),('effective_tokens',0),('threshold',0.)]:
                original=rows[0][field]; rows[0][field]=value
                with self.assertRaises(AssertionError,msg=field):
                    fn(generations,rows,10000,99999)
                rows[0][field]=original


if __name__=='__main__':
    unittest.main()

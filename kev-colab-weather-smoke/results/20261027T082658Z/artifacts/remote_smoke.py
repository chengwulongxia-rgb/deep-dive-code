"""Official Kev CUDA smoke; import/build_cases are CPU-only. No allocation API."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import time
import traceback
import zipfile

UPSTREAM_SHA = '2074cc44256200bb37540103fa4572901faa10f3'
MODEL_SHA = 'bf75a6a8848ea6960ff2ed108d9ed44c2941174f'
MODEL_ID = 'jaredpalmer/kev-0.8b'
SOURCE_URL = 'https://www.cwa.gov.tw/V8/C/W/Town/Town.html?TID=1001405'
LABELS = {'user_original_zh': 'table_1'}
SEED = 20261027


def build_cases(dom):
    """Select candidates, not weather values. Uniform bounded excerpts, no semantic aliases."""
    if dom['url'] != SOURCE_URL:
        raise ValueError('Source URL differs from literal user URL')
    if [t['id'] for t in dom['tables']] != ['table_0', 'table_1', 'table_2']:
        raise ValueError('Expected exactly the three captured visible table candidates')
    candidates = []
    for table in dom['tables']:
        candidates.append({
            'id': table['id'], 'caption': table['caption'],
            'rows': [[{k: cell[k] for k in ('text', 'rowspan', 'colspan')}
                      for cell in row[:4]] for row in table['rows']],
            'text': table['text'][:650],
        })
    state = json.dumps({'title': dom['title'], 'candidates': candidates}, ensure_ascii=False, separators=(',', ':'))
    if len(state) > 6000:
        raise ValueError('State exceeds 6000 characters; do not silently truncate')
    def request(state, instruction, criteria):
        return {'state': state, 'questions': {'selection': {'type': 'choice', 'instructions': instruction, 'criteria': criteria}}}
    criteria = {t['id']: None for t in candidates}
    return [
        {'id': 'user_original_zh', 'group': 'user_original_zh', 'request': request(state, '鹿野鄉今晚的降雨機率', criteria)},
    ]


def summarize(cases):
    out = {}
    for group in ('user_original_zh',):
        rows = [c for c in cases if c['group'] == group]
        completed = [c for c in rows if c['status'] == 'completed']
        out[group] = {'status': 'completed' if len(completed) == len(rows) else 'not_completed',
                      'completed': len(completed), 'total': len(rows),
                      'correct': sum(c['correct'] for c in completed)}
    return out


def main():
    started = time.perf_counter()
    input_path = Path(os.environ.get('KEV_SMOKE_INPUT', '/content/cwa_dom.json'))
    output = Path('/content/kev-smoke-result.json')
    archive = Path('/content/kev-smoke-artifacts.zip')
    server = None
    torch = None
    result = {'status': 'not_run', 'inference_status': 'not_run', 'seed': SEED,
              'upstream_expected_sha': UPSTREAM_SHA, 'model_id': MODEL_ID,
              'model_revision': MODEL_SHA, 'model_revision_lookup': 'HF API revision/v1.0',
              'cases': [], 'limitations': ['Candidate selection only; no weather-number extraction.',
              'One captured DOM, not arbitrary DOM resilience.', 'English-trained model; Chinese is an out-of-distribution probe.',
              'Inference completion is not semantic correctness.']}
    try:
        raw = input_path.read_bytes()
        result['source_input_utf8'] = raw.decode('utf-8')
        result['source_input_sha256'] = hashlib.sha256(raw).hexdigest()
        dom = json.loads(raw)
        cases = build_cases(dom)
        result['cases'] = [{**c, 'expected': LABELS[c['id']], 'status': 'not_run'} for c in cases]
        actual_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        result['upstream_actual_sha'] = actual_sha
        if actual_sha != UPSTREAM_SHA:
            raise RuntimeError('Run from the pinned upstream checkout')
        import torch as torch_module
        torch = torch_module
        result['environment'] = {'python': platform.python_version(), 'platform': platform.platform(),
                                 'torch': torch.__version__, 'cuda_runtime': torch.version.cuda,
                                 'versions': {name: importlib.metadata.version(name) for name in
                                              ('transformers', 'huggingface-hub', 'pydantic', 'fastapi', 'peft')}}
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA required; CPU fallback prohibited')
        name = torch.cuda.get_device_name(0)
        result['environment'].update(gpu=name, gpu_count=torch.cuda.device_count(),
            nvidia_smi=subprocess.check_output(['nvidia-smi'], text=True))
        if 'L4' not in name.split():
            raise RuntimeError(f'L4 required, got {name!r}')
        random.seed(SEED)
        import numpy as np
        np.random.seed(SEED)
        torch.manual_seed(SEED)
        torch.cuda.manual_seed_all(SEED)
        torch.cuda.reset_peak_memory_stats()
        # Explicitly disable ambient preprocessing/truncation before importing Server.
        os.environ['KEV_DATE_FACTS'] = '0'
        os.environ['KEV_TRUNCATE_STATES'] = '0'
        from kev.checkpoint import Checkpoint, LoadOptions
        from kev.api import SystemOneRequest
        from kev.serve import Server
        ck = Checkpoint(f'{MODEL_ID}@{MODEL_SHA}')
        tok, model = ck.load('cuda', LoadOptions(dtype=torch.bfloat16, backend='torch', fused=False, cuda_graphs=False))
        result['checkpoint_metadata'] = vars(ck.meta)
        server = Server(ck, tok, model, 'cuda')
        for case in result['cases']:
            case_start = time.perf_counter()
            case['status'] = 'running'
            try:
                response = server.answer(SystemOneRequest.model_validate(case['request']))
                case['raw_response'] = response
                answer = response['answers']['selection']
                case['choice'] = answer['choice']
                case['probabilities'] = answer['probabilities']
                case['reported_latency_ms'] = response['latency_ms']
                if answer['choice'] not in case['request']['questions']['selection']['criteria']:
                    raise ValueError('Model returned an invalid choice')
                case['correct'] = answer['choice'] == case['expected']
                case['status'] = 'completed'
            except BaseException:
                case['status'] = 'error'
                case['error'] = traceback.format_exc()
                raise
            finally:
                case['wall_elapsed_seconds'] = time.perf_counter() - case_start
        result['inference_status'] = 'completed'
        result['status'] = 'completed'  # Deliberately NOT a semantic pass flag.
    except BaseException:
        result['status'] = 'error'
        result['inference_status'] = 'error'
        result['error'] = traceback.format_exc()
        raise
    finally:
        try:
            if server is not None:
                server.close()
        except BaseException:
            result['close_error'] = traceback.format_exc()
            result['status'] = 'error'
            raise
        finally:
            if torch is not None and torch.cuda.is_available():
                result['peak_memory_bytes'] = {'allocated': torch.cuda.max_memory_allocated(),
                                               'reserved': torch.cuda.max_memory_reserved()}
            result['elapsed_seconds'] = time.perf_counter() - started
            result['summary'] = summarize(result['cases'])
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
                z.write(output, output.name)
                if input_path.exists():
                    z.write(input_path, 'cwa_dom.json')
                z.write(Path(__file__).resolve(), 'remote_smoke.py')
            print(json.dumps({'status': result['status'], 'summary': result['summary'], 'result': str(output), 'archive': str(archive)}))


if __name__ == '__main__':
    main()

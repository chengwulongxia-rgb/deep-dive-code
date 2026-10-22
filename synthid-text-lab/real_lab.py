"""Official Transformers 4.57.1 SynthID processor; no Bayesian detector training."""
import random
from typing import TypedDict, cast

class SamplePlan(TypedDict):
    prompt: str
    seed: int
    sample_index: int

CAL_TOPICS = ['a coastal lighthouse', 'a mountain observatory', 'a quiet library', 'an ancient bridge',
              'a garden in spring', 'a railway station', 'an ocean expedition', 'a pottery workshop',
              'a solar panel', 'a rainy afternoon', 'a desert caravan', 'a village bakery',
              'a river ecosystem', 'a museum collection', 'a forest trail', 'a night sky',
              'a bicycle journey', 'a wind farm', 'a small theater', 'a winter cabin',
              'a coral reef', 'an apple orchard', 'a clock repair shop', 'a ferry crossing']
EVAL_TOPICS = ['a community radio show', 'a robot learning chess', 'a city rooftop', 'a glass sculpture',
               'a migratory bird', 'a jazz rehearsal', 'a forgotten recipe', 'a volcanic island',
               'a newspaper archive', 'a public swimming pool', 'a music classroom', 'a satellite launch']
CONDITIONS = ['clean', 'truncate_half', 'delete_10pct', 'replace_10pct']


def sample_plan(length: int, split: str, count: int) -> list[SamplePlan]:
    if split not in ('calibration', 'evaluation') or count < 1:
        raise ValueError('invalid split/count')
    topics = CAL_TOPICS if split == 'calibration' else EVAL_TOPICS
    if count > len(topics):
        raise ValueError(f'maximum {len(topics)} distinct prompts for {split}')
    base = (100000 if split == 'calibration' else 200000) + length * 100
    return [SamplePlan(prompt=f'Write a short English story about {topic}. The story begins:',
                 seed=base + i, sample_index=i) for i, topic in enumerate(topics[:count])]


def perturb(tokens, condition, seed, vocab_size):
    out = list(tokens)
    rng = random.Random(seed)
    edits = []
    if condition == 'truncate_half':
        return out[:len(out)//2], list(range(len(out)//2, len(out)))
    if condition not in CONDITIONS:
        raise ValueError(condition)
    if condition in ('delete_10pct', 'replace_10pct'):
        edits = sorted(rng.sample(range(len(out)), len(out)//10))
        if condition == 'delete_10pct':
            edited = set(edits)
            out = [t for i, t in enumerate(out) if i not in edited]
        else:
            for i in edits:
                replacement = rng.randrange(vocab_size - 2)
                out[i] = replacement + (replacement >= out[i])
    return out, edits


KEYS = [654, 400, 836, 123, 340, 443, 597, 160]
WRONG_KEYS = [key + 10000 for key in KEYS]
MODEL_ID = 'distilbert/distilgpt2'
REVISION = '2290a62682d06624634c1f46a6ad5be0f47f38aa'


def watermark_config(wrong=False):
    from transformers import SynthIDTextWatermarkingConfig
    return SynthIDTextWatermarkingConfig(ngram_len=5, keys=WRONG_KEYS if wrong else KEYS,
        sampling_table_seed=0, sampling_table_size=65536, context_history_size=1024,
        skip_first_ngram_calls=True)


def group_key(row):
    return f"{row['source_length']}:{row['condition']}:{row['key_condition']}"


def summarize(rows):
    from lab import calibrate
    groups = {}
    for row in rows:
        groups.setdefault(group_key(row), []).append(row)
    thresholds, summary = {}, []
    for key, group in sorted(groups.items()):
        cal = [r for r in group if r['split'] == 'calibration']
        threshold = calibrate(cal)
        thresholds[key] = threshold
        info = {k: group[0][k] for k in ['source_length', 'condition', 'key_condition']}
        info.update(threshold=threshold, calibration_count=len(cal),
                    calibration_detected=sum(r['score'] > threshold for r in cal))
        for origin in ['plain', 'watermarked']:
            ev = [r for r in group if r['split']=='evaluation' and r['origin']==origin]
            info[f'{origin}_count'] = len(ev)
            info[f'{origin}_detected'] = sum(r['score'] is not None and r['score'] > threshold for r in ev)
            info[f'{origin}_unscorable'] = sum(r['score'] is None for r in ev)
            info[f'{origin}_mean_effective_tokens'] = sum(r['effective_tokens'] for r in ev)/len(ev) if ev else None
        summary.append(info)
    return summary, thresholds


def run_real(args):
    import collections
    import importlib.metadata
    import json
    import os
    import platform
    import time
    from datetime import datetime, timezone
    import torch
    import torch.version
    from transformers import AutoModelForCausalLM, AutoTokenizer, GPT2LMHeadModel, set_seed
    from lab import real_score
    from main import save_json
    if not 1 <= args.threads <= 4:
        raise ValueError('threads must be between 1 and 4')
    if len(set(args.lengths)) != len(args.lengths) or any(n < 10 or n > 512 for n in args.lengths):
        raise ValueError('distinct lengths in [10,512] required')
    # Validate split plans before downloading anything.
    for length in args.lengths:
        sample_plan(length, 'calibration', args.calibration_count)
        sample_plan(length, 'evaluation', args.evaluation_count)
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    # Explicit token=False: no credentials needed or sent for this public model.
    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=REVISION, token=False, trust_remote_code=False)
    model = cast(GPT2LMHeadModel, AutoModelForCausalLM.from_pretrained(
        MODEL_ID, revision=REVISION, token=False, trust_remote_code=False,
        use_safetensors=True, attn_implementation='eager'))
    torch.nn.Module.to(model, torch.device('cpu'))
    model.eval()
    load_seconds = time.perf_counter() - started
    processors = {'correct': make_processor(), 'wrong': make_processor(True)}
    params = dict(model_id=MODEL_ID, model_revision=REVISION, lengths=args.lengths,
                  calibration_count=args.calibration_count, evaluation_count_per_origin=args.evaluation_count,
                  watermark_config=watermark_config().to_dict(), wrong_keys=WRONG_KEYS, threads=args.threads,
                  detector='Mean g-values over official EOS/repeated-context mask; NOT Bayesian probability',
                  threshold_method='maximum plain calibration score + 1e-12, separately by source_length/condition/key',
                  generation=dict(do_sample=True, temperature=1.0, top_k=40, top_p=1.0,
                                  num_beams=1, use_cache=True, min_new_tokens='source_length', max_new_tokens='source_length',
                                  pad_token_id=tokenizer.eos_token_id),
                  perturbation='token-ID edits only: floor(length/10) deletions/replacements; truncate to first half',
                  prompt_policy='24 calibration topics disjoint from 12 evaluation topics; paired plain/wm evaluation seeds',
                  scoring_input='generated token IDs only (prompt excluded); roundtrip diagnostics recorded separately')
    metadata = dict(timestamp_utc=datetime.now(timezone.utc).isoformat(), python=platform.python_version(),
                    platform=platform.platform(), machine=platform.machine(), cpu=platform.processor(),
                    cpu_count=os.cpu_count(), torch_threads=torch.get_num_threads(),
                    torch_interop_threads=torch.get_num_interop_threads(), torch_cuda=torch.version.cuda,
                    deterministic_algorithms=torch.are_deterministic_algorithms_enabled(),
                    versions={p: importlib.metadata.version(p) for p in ['torch','transformers','tokenizers','huggingface-hub','numpy','matplotlib']})
    rows, generations = [], []
    checkpoint = args.output/'generations.jsonl'
    generation_start = time.perf_counter()
    # One call per sample so every actual sequence has an explicit independent seed.
    with checkpoint.open('w') as log:
        for length in args.lengths:
            for split, count, origins in [('calibration', args.calibration_count, ['plain']),
                                           ('evaluation', args.evaluation_count, ['plain','watermarked'])]:
                for plan in sample_plan(length, split, count):
                    inputs = tokenizer(plan['prompt'], return_tensors='pt')
                    for origin in origins:
                        set_seed(plan['seed'])
                        t0 = time.perf_counter()
                        with torch.inference_mode():
                            sequence = model.generate(**inputs, max_new_tokens=length, min_new_tokens=length,
                                do_sample=True, temperature=1.0, top_k=40, top_p=1.0, num_beams=1,
                                use_cache=True, pad_token_id=tokenizer.eos_token_id,
                                watermarking_config=watermark_config() if origin=='watermarked' else None)
                        ids = sequence[0, inputs['input_ids'].shape[1]:].tolist()
                        elapsed = time.perf_counter()-t0
                        if len(ids) != length:
                            raise RuntimeError(f'expected {length} tokens, got {len(ids)}')
                        source_id = f'{length}-{split}-{origin}-{plan["sample_index"]:02d}'
                        generation = dict(source_id=source_id, source_length=length, split=split, origin=origin,
                                          **plan, prompt_token_ids=inputs['input_ids'][0].tolist(),
                                          token_ids=ids, text=tokenizer.decode(ids, clean_up_tokenization_spaces=False),
                                          generation_seconds=elapsed)
                        generations.append(generation)
                        log.write(json.dumps(generation, allow_nan=False)+'\n')
                        log.flush()
                        for condition in CONDITIONS:
                            edit_seed = plan['seed'] + 900000
                            edited, edits = perturb(ids, condition, edit_seed, tokenizer.vocab_size)
                            text = tokenizer.decode(edited, clean_up_tokenization_spaces=False)
                            reencoded = tokenizer.encode(text, add_special_tokens=False)
                            for key_name, processor in processors.items():
                                row = dict(source_id=source_id, source_length=length, split=split, origin=origin,
                                           **plan, condition=condition, perturbation_seed=edit_seed,
                                           edited_original_positions=edits, key_condition=key_name,
                                           token_ids=edited, text=text, actual_token_count=len(edited),
                                           roundtrip_equal=(edited==reencoded), retokenized_token_ids=reencoded,
                                           generation_seconds=elapsed, **real_score(edited, processor, tokenizer.eos_token_id))
                                rt = real_score(reencoded, processor, tokenizer.eos_token_id)
                                row['retokenized_score'] = rt['score']
                                row['retokenized_effective_tokens'] = rt['effective_tokens']
                                rows.append(row)
                        print(f'{source_id}: {length} new tokens in {elapsed:.3f}s', flush=True)
    summary, thresholds = summarize(rows)
    for row in rows:
        row['threshold'] = thresholds[group_key(row)]
        row['detected'] = row['score'] is not None and row['score'] > row['threshold']
    roundtrip = []
    for origin in ['plain','watermarked']:
        for condition in CONDITIONS:
            subset = [r for r in rows if r['origin']==origin and r['condition']==condition and r['key_condition']=='correct']
            roundtrip.append(dict(origin=origin, condition=condition, count=len(subset),
                                  mismatches=sum(not r['roundtrip_equal'] for r in subset)))
    result = dict(kind='real', parameters=params, environment=metadata,
                  timing=dict(model_load_seconds=load_seconds, generation_and_scoring_seconds=time.perf_counter()-generation_start,
                              sum_generate_seconds=sum(g['generation_seconds'] for g in generations),
                              total_seconds=time.perf_counter()-started),
                  counts=dict(generations=len(generations), score_rows=len(rows),
                              generation_groups=dict(collections.Counter(f'{g["source_length"]}:{g["split"]}:{g["origin"]}' for g in generations))),
                  thresholds=thresholds, summary=summary, roundtrip=roundtrip, rows=rows)
    save_json(args.output/'real.json', result)
    from chart import make_chart
    make_chart(result, args.output/'summary.png')
    print(json.dumps({'counts': result['counts'], 'timing': result['timing'], 'summary': summary,
                      'roundtrip': roundtrip}, indent=2), flush=True)


def make_processor(wrong=False):
    import torch
    from transformers import SynthIDTextWatermarkLogitsProcessor
    return SynthIDTextWatermarkLogitsProcessor(**watermark_config(wrong).to_dict(), device=torch.device('cpu'))

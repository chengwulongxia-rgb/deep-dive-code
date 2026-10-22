"""Audit saved measurements without downloading anything; --replay uses cached model."""
import argparse
import collections
import json
from pathlib import Path
from typing import Any, cast
from lab import real_score, toy_generate
from real_lab import CONDITIONS, MODEL_ID, REVISION, group_key, make_processor, perturb, sample_plan, summarize


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def audit(directory, replay=False):
    data = json.loads((directory/'real.json').read_text())
    generations = [json.loads(line) for line in (directory/'generations.jsonl').read_text().splitlines()]
    rows = data['rows']
    by_id = {g['source_id']:g for g in generations}
    check(len(by_id)==len(generations)==data['counts']['generations'], 'generation count/IDs')
    groups = dict(collections.Counter(f'{g["source_length"]}:{g["split"]}:{g["origin"]}' for g in generations))
    check(groups==data['counts']['generation_groups'], 'declared group counts')
    check(len(rows)==len(generations)*8==data['counts']['score_rows'], 'derived row count')
    combos = collections.Counter((r['source_id'],r['condition'],r['key_condition']) for r in rows)
    check(len(combos)==len(rows) and set(combos.values())=={1}, 'duplicate conditions')
    processors = {'correct':make_processor(), 'wrong':make_processor(True)}
    for length in data['parameters']['lengths']:
        for split in ['calibration','evaluation']:
            subset = [g for g in generations if g['source_length']==length and g['split']==split]
            count = data['parameters']['calibration_count' if split=='calibration' else 'evaluation_count_per_origin']
            expected = sample_plan(length, split, count)
            for origin in (['plain'] if split=='calibration' else ['plain','watermarked']):
                subset_origin = sorted((g for g in subset if g['origin']==origin), key=lambda g:g['sample_index'])
                check(len(subset_origin)==count, 'generation split count')
                for g, plan in zip(subset_origin, expected):
                    check(all(g[k]==v for k,v in plan.items()), 'prompt/seed drift')
                    check(len(g['token_ids'])==length, 'new-token count')
        cal = [g for g in generations if g['split']=='calibration']
        ev = [g for g in generations if g['split']=='evaluation']
        check(not ({g['prompt'] for g in cal} & {g['prompt'] for g in ev}), 'prompt leakage')
        check(not ({g['seed'] for g in cal} & {g['seed'] for g in ev}), 'seed leakage')
    for row in rows:
        source = by_id[row['source_id']]
        edited, edits = perturb(source['token_ids'],row['condition'],row['perturbation_seed'],50257)
        check(edited==row['token_ids'] and edits==row['edited_original_positions'], 'edit mismatch')
        score = real_score(edited, processors[row['key_condition']],50256)
        check(all(row[k]==v for k,v in score.items()), 'score/g-values/mask mismatch')
        check(len(edited)==row['actual_token_count'], 'actual length mismatch')
        rt = real_score(row['retokenized_token_ids'],processors[row['key_condition']],50256)
        check(row['retokenized_score']==rt['score'] and row['retokenized_effective_tokens']==rt['effective_tokens'], 'retokenized score')
        check(row['roundtrip_equal']==(edited==row['retokenized_token_ids']), 'roundtrip flag')
        check(row['detected']==(row['score'] is not None and row['score']>row['threshold']), 'decision')
    summary, thresholds = summarize(rows)
    check(summary==data['summary'] and thresholds==data['thresholds'], 'summary/calibration mismatch')
    check(all(r['threshold']==thresholds[group_key(r)] for r in rows), 'threshold mismatch')
    for group in data['roundtrip']:
        subset = [r for r in rows if r['origin']==group['origin'] and r['condition']==group['condition'] and r['key_condition']=='correct']
        check(len(subset)==group['count'] and sum(not r['roundtrip_equal'] for r in subset)==group['mismatches'], 'roundtrip count')
    toy = json.loads((directory/'toy.json').read_text())
    check(toy['trace']['final_token']==toy_generate(1,toy['trace']['seed'],toy['trace']['key'],watermarked=True)[0], 'toy trace not aligned')
    report: dict[str, Any] = dict(generations_verified=len(generations), score_rows_recomputed=len(rows),
                  thresholds_recomputed=len(thresholds), prompt_seed_leakage=False, replay=[])
    if replay:
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM, GPT2LMHeadModel, set_seed
        from real_lab import watermark_config
        torch.set_num_threads(data['parameters']['threads'])
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID,revision=REVISION,token=False,
                                                  trust_remote_code=False,local_files_only=True)
        model = cast(GPT2LMHeadModel, AutoModelForCausalLM.from_pretrained(
            MODEL_ID, revision=REVISION, token=False, trust_remote_code=False,
            use_safetensors=True, attn_implementation='eager', local_files_only=True))
        torch.nn.Module.to(model, torch.device('cpu'))
        model.eval()
        for row in rows:
            rt = tokenizer.encode(tokenizer.decode(row['token_ids'],clean_up_tokenization_spaces=False),add_special_tokens=False)
            check(rt==row['retokenized_token_ids'], 'actual tokenizer roundtrip mismatch')
        for origin in ['plain','watermarked']:
            g = next(g for g in generations if g['split']=='evaluation' and g['origin']==origin)
            ids = tokenizer(g['prompt'],return_tensors='pt')
            for attempt in range(2):
                set_seed(g['seed'])
                with torch.inference_mode():
                    output = model.generate(**ids,max_new_tokens=g['source_length'],min_new_tokens=g['source_length'],
                        do_sample=True,temperature=1.0,top_k=40,top_p=1.0,num_beams=1,use_cache=True,pad_token_id=50256,
                        watermarking_config=watermark_config() if origin=='watermarked' else None)
                check(output[0,ids['input_ids'].shape[1]:].tolist()==g['token_ids'], 'generation replay mismatch')
            report['replay'].append(dict(source_id=g['source_id'],repetitions=2,exact_token_match=True))
        report['actual_tokenizer_roundtrips_verified'] = len(rows)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,default=Path('results'))
    parser.add_argument('--replay',action='store_true',help='Replay 2 saved sources twice using local cached model only')
    args = parser.parse_args()
    print(json.dumps(audit(args.results,args.replay),indent=2))

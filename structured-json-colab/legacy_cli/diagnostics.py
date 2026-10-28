"""Post-hoc, offline diagnostic; never changes primary results or reruns a model."""
import copy
import json
from pathlib import Path
import re
from benchmark import evaluate, summarize


def unwrap_one_fence(raw):
    match=re.fullmatch(r'```(?:json)?[ \t]*\r?\n(.*?)\r?\n```[ \t]*',raw.strip(),flags=re.DOTALL)
    return match.group(1) if match else raw


def diagnose(directory):
    directory=Path(directory)
    rows=[json.loads(s) for s in (directory/'results.jsonl').read_text().splitlines()]
    cases={c['id']:c for c in json.loads((directory/'inputs.json').read_text())['cases']}
    rescored=[]
    changes={arm:0 for arm in ['A','B','C']}
    details=[]
    for row in rows:
        original=row['attempts'][-1]['raw']
        processed=unwrap_one_fence(original)
        changes[row['arm']]+=processed!=original
        replacement=copy.deepcopy(row)
        replacement['score']=evaluate(processed,cases[row['case_id']]['gold'])
        rescored.append(replacement)
        if not replacement['score']['object_exact']:
            details.append({'case_id':row['case_id'],'arm':row['arm'],
                            'schema_valid':replacement['score']['schema_valid'],
                            'errors':replacement['score']['errors'],
                            'wrong_fields':[k for k,v in replacement['score']['field_matches'].items() if not v],
                            'gold':cases[row['case_id']]['gold'],'parsed':replacement['score']['parsed']})
    result={'posthoc':True,'method':'Remove exactly one complete json/unlabelled Markdown code fence; no extraction from prose, no JSON repair, no model calls.',
            'primary_metrics_unchanged':True,'wrappers_removed':changes,
            'summary':summarize(rescored),'remaining_failures':details,
            'warning':'Diagnostic only, introduced after inspecting raw outputs. Not a preregistered fourth model arm. Latency/VRAM copied from original generation, not a new measurement.'}
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    args=parser.parse_args()
    result=diagnose(args.directory)
    (Path(args.directory)/'posthoc-fence-diagnostic.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='remaining_failures'},ensure_ascii=False,indent=2))

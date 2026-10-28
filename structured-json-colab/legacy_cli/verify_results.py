"""Independently re-score downloaded raw outputs without a model/GPU."""
import hashlib
import json
import math
from pathlib import Path
from benchmark import SCHEMA, build_messages, evaluate, summarize

HERE=Path(__file__).resolve().parent


def verify(directory):
    directory=Path(directory)
    report=json.loads((directory/'report.json').read_text())
    rows=[json.loads(line) for line in (directory/'results.jsonl').read_text().splitlines() if line.strip()]
    fixture_bytes=(directory/'inputs.json').read_bytes()
    if report.get('status')!='completed' or report.get('records_written')!=72 or len(rows)!=72:
        raise ValueError('Require exactly 72 completed arm results')
    if report['fixture_sha256']!=hashlib.sha256(fixture_bytes).hexdigest():
        raise ValueError('Downloaded fixture hash mismatch')
    if fixture_bytes!=(HERE/'fixtures.json').read_bytes():
        raise ValueError('Fixture changed since experiment definition')
    if report['worker_sha256']!=hashlib.sha256((HERE/'benchmark.py').read_bytes()).hexdigest():
        raise ValueError('Worker source differs from executed worker')
    if report['schema']!=SCHEMA or report['model_revision']!='989aa7980e4cf806f80c7fef2b1adb7bc71aa306':
        raise ValueError('Wrong schema or model revision')
    cases={c['id']:c for c in json.loads(fixture_bytes)['cases']}
    mapping={(r['case_id'],r['arm']):r for r in rows}
    expected={(case,arm) for case in cases for arm in ['A','B','C']}
    if len(cases)!=24 or set(mapping)!=expected:
        raise ValueError('Duplicate/missing case-arm results')
    for (ident,arm),row in mapping.items():
        score=evaluate(row['attempts'][-1]['raw'],cases[ident]['gold'])
        if score!=row['score']:
            raise ValueError('Stored score disagrees with raw output: '+ident+' '+arm)
        if any(not math.isfinite(a['latency_s']) or a['latency_s']<0 for a in row['attempts']):
            raise ValueError('Invalid latency')
        if row['latency_s']!=sum(a['latency_s'] for a in row['attempts']):
            raise ValueError('Attempt cost omitted')
        if arm=='B':
            a=mapping[ident,'A']
            if row['attempts'][0]!=a['attempts'][0]:
                raise ValueError('B did not reuse exact A output')
            retries=int(not a['score']['schema_valid'])
            if row['retry_count']!=retries or len(row['attempts'])!=1+retries:
                raise ValueError('B retried semantic errors or exceeded retry budget')
        else:
            if len(row['attempts'])!=1:
                raise ValueError('A/C must be a single attempt')
        prompt_hash=hashlib.sha256(json.dumps(build_messages(cases[ident]),ensure_ascii=False).encode()).hexdigest()
        if row['attempts'][0]['messages_sha256']!=prompt_hash:
            raise ValueError('Common prompt changed or gold leaked')
    summary=summarize(rows)
    if summary!=report['summary'] or any(s['field_total']!=168 for s in summary.values()):
        raise ValueError('Summary or field denominator mismatch')
    return {'verified':True,'records':len(rows),'cases':len(cases),'fields_per_arm':168,
            'raw_outputs_rescored':True,'shared_A_B_verified':True,'common_prompts_verified':True,
            'fixture_sha256':report['fixture_sha256'],'worker_sha256':report['worker_sha256'],
            'artifact_sha256':{name:hashlib.sha256((directory/name).read_bytes()).hexdigest()
                               for name in ['inputs.json','results.jsonl','report.json']},'summary':summary}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    args=parser.parse_args()
    result=verify(args.directory)
    (Path(args.directory)/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))

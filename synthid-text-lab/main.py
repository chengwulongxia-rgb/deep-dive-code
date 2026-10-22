"""CPU watermark lab. Default path is stdlib-only; heavy imports are lazy."""
import argparse
import json
import random
import time
from pathlib import Path
from typing import Any
from lab import toy_bit, toy_generate, toy_detect


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def toy_trace(seed=42, key=123, depth=4):
    rng = random.Random(seed)
    candidates = [rng.randrange(256) for _ in range(2 ** depth)]
    trace: dict[str, Any] = dict(seed=seed, key=key, context=[], vocabulary_size=256, depth=depth,
                 original_token_probability=1/256, original_candidates=candidates[:], rounds=[])
    for layer in range(depth):
        pairs, winners = [], []
        for a, b in zip(candidates[::2], candidates[1::2]):
            bits = [toy_bit((), a, key, layer), toy_bit((), b, key, layer)]
            winner = a if bits[0] > bits[1] else b if bits[1] > bits[0] else rng.choice([a, b])
            pairs.append(dict(tokens=[a, b], g_bits=bits, winner=winner))
            winners.append(winner)
        trace['rounds'].append(dict(layer=layer, pairs=pairs, winners=winners))
        candidates = winners
    trace['final_token'] = candidates[0]
    return trace


def run_toy(output, seed):
    rows = []
    for fixed in [False, True]:
        for origin in ['plain', 'watermarked']:
            tokens = toy_generate(256, seed, 123, watermarked=origin=='watermarked', fixed=fixed)
            for key in [123, 456]:
                rows.append(dict(origin=origin, condition='fixed_low_entropy' if fixed else 'uniform_256',
                                 seed=seed, key=key, token_ids=tokens, **toy_detect(tokens, key)))
    data: dict[str, Any] = dict(kind='toy', disclaimer='Teaching analogy only; NOT full SynthID and NOT a Claude detector.',
                parameters=dict(length=256, depth=4, key=123, wrong_key=456), rows=rows, trace=toy_trace(seed))
    save_json(output/'toy.json', data)
    print(json.dumps({'toy_scores': [{k:v for k,v in r.items() if k!='token_ids'} for r in rows],
                      'trace_final_token': data['trace']['final_token']}, indent=2))
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real', action='store_true', help='Download pinned distilgpt2 and run CPU generation')
    parser.add_argument('--chart', type=Path, nargs='?', const=Path('results/summary.png'), help='Redraw existing JSON; no model imports/download')
    parser.add_argument('--input', type=Path, help='Existing JSON for --chart (defaults to OUTPUT/real.json)')
    parser.add_argument('--output', type=Path, default=Path('results'))
    parser.add_argument('--seed', type=int, default=42, help='Toy seed; real uses documented split/length-derived seeds')
    parser.add_argument('--calibration-count', type=int, default=24)
    parser.add_argument('--evaluation-count', type=int, default=12, help='Count PER origin PER length')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--lengths', type=int, nargs='+', default=[64, 128])
    args = parser.parse_args()
    if args.chart:
        from chart import make_chart
        make_chart(json.loads((args.input or args.output/'real.json').read_text()), args.chart)
        print(f'Chart: {args.chart}')
        return
    args.output.mkdir(parents=True, exist_ok=True)
    if args.real:
        from real_lab import run_real
        run_real(args)
    else:
        run_toy(args.output, args.seed)


if __name__ == '__main__':
    main()

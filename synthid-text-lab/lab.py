"""Stdlib-only teaching analogy; NOT a complete SynthID implementation."""
import hashlib
import math
import random


def calibrate(rows):
    if not rows or any(r['split'] != 'calibration' or r['origin'] != 'plain' for r in rows):
        raise ValueError('thresholds require nonempty calibration plain rows only')
    if any(r['score'] is None or not math.isfinite(r['score']) for r in rows):
        raise ValueError('cannot calibrate empty or nonfinite scores')
    return max(r['score'] for r in rows) + 1e-12


def real_score(tokens, processor, eos_token_id):
    # Mirrors official detector masks, but uses a simple mean, NOT a trained posterior.
    if len(tokens) < processor.ngram_len:
        return {'score': None, 'effective_tokens': 0, 'valid_mask': [], 'g_values': []}
    import torch
    ids = torch.tensor([tokens], dtype=torch.long)
    g = processor.compute_g_values(ids)
    mask = processor.compute_context_repetition_mask(ids)
    mask &= processor.compute_eos_token_mask(ids, eos_token_id)[:, processor.ngram_len - 1:]
    count = int(mask.sum().item())
    return {'score': float(g[mask].float().mean().item()) if count else None,
            'effective_tokens': count, 'valid_mask': mask[0].tolist(), 'g_values': g[0].tolist()}


def toy_bit(context, token, key, layer):
    payload = f'{key}:{layer}:{context}:{token}'.encode()
    return hashlib.sha256(payload).digest()[0] & 1


def toy_generate(length, seed, key, watermarked=False, fixed=False, depth=4):
    rng = random.Random(seed)
    result = []
    for _ in range(length):
        context = tuple(result[-3:])
        candidates = [7 if fixed else rng.randrange(256) for _ in range(2 ** depth if watermarked else 1)]
        for layer in range(depth if watermarked else 0):
            winners = []
            for a, b in zip(candidates[::2], candidates[1::2]):
                ga, gb = toy_bit(context, a, key, layer), toy_bit(context, b, key, layer)
                winners.append(a if ga > gb else b if gb > ga else rng.choice([a, b]))
            candidates = winners
        result.append(candidates[0])
    return result


def toy_detect(tokens, key, threshold=0.65, minimum_effective_tokens=32):
    result = toy_score(tokens, key)
    result['threshold'] = threshold
    result['minimum_effective_tokens'] = minimum_effective_tokens
    result['detected'] = (result['score'] > threshold) if result['effective_tokens'] >= minimum_effective_tokens else None
    return result


def toy_score(tokens, key, depth=4):
    # Ignore insufficient context and repeated contexts: repetitions aren't new evidence.
    seen, bits = set(), []
    for i in range(3, len(tokens)):
        context = tuple(tokens[i-3:i])
        if context in seen:
            continue
        seen.add(context)
        bits.extend(toy_bit(context, tokens[i], key, d) for d in range(depth))
    return {'score': sum(bits) / len(bits) if bits else None, 'effective_tokens': len(bits) // depth}

"""Recompute one frozen benchmark-cost example; never calls a model API.
Usage: python audit_cost.py [local-cost-data.json]
Without a path, read only the original public calculator HTML.
"""
import hashlib
import json
import math
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

URL = 'https://jeff-kline.github.io/posts/same-ai-results-for-less/index.html'
EXPECTED = '39c67d819e8f69f9904db23afd257ff74fe0377151c8a4abaa430a31ab56c95e'


class EmbeddedData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('id') == 'task-data':
            self.active = True

    def handle_endtag(self, tag):
        if tag == 'script':
            self.active = False

    def handle_data(self, text):
        if self.active:
            self.parts.append(text)


def audit(raw):
    if hashlib.sha256(raw).hexdigest() != EXPECTED:
        raise ValueError('Snapshot changed; do not report this as the frozen example.')
    data = json.loads(raw)
    profile = next(p for p in data['profiles'] if p['id'] == 'analytics')
    rows = {r['id']: r for r in profile['rows']}
    target = rows['gpt-6-1-terra-low']
    peers = target['peers']
    assert math.isclose(sum(peers.values()), 1.0, abs_tol=1e-12)
    assert all(w >= 0 for w in peers.values())
    scores = [sum(rows[k]['scores'][j] * w for k, w in peers.items()) for j in range(2)]
    cost = sum(rows[k]['cost'] * w for k, w in peers.items())
    assert all(s + 1e-12 >= t for s, t in zip(scores, target['scores']))
    assert math.isclose(cost, target['reference_cost'], abs_tol=1e-12)
    eligible = [r for r in rows.values() if all(s + 1e-12 >= t for s, t in zip(r['scores'], target['scores']))]
    single = min(eligible, key=lambda r: r['cost'])
    relaxed = min((r for r in rows.values() if r['scores'][0] + 1e-12 >= target['scores'][0]), key=lambda r: r['cost'])
    u = target['certificate']['dual_u']
    v = target['certificate']['dual_intercept']
    assert all(x >= -1e-12 for x in u)
    assert all(r['cost'] + 1e-10 >= sum(a * b for a, b in zip(u, r['scores'])) + v for r in rows.values())
    assert math.isclose(cost, sum(a * b for a, b in zip(u, target['scores'])) + v, abs_tol=1e-10)
    return {
        'snapshot': data['snapshot'], 'calculation_date': data['derived_date'],
        'configurations_checked': len(rows), 'target_scores': target['scores'],
        'baseline_usd_per_1000': target['cost'] * 1000,
        'blend_scores': scores, 'blend_usd_per_1000': cost * 1000,
        'saving_pct': (1 - cost / target['cost']) * 100,
        'cheapest_eligible_single': single['id'],
        'relaxed_single': relaxed['id'], 'relaxed_scores': relaxed['scores'],
        'relaxed_usd_per_1000': relaxed['cost'] * 1000,
        'relaxed_passes_both': all(s + 1e-12 >= t for s, t in zip(relaxed['scores'], target['scores'])),
        'dual_certificate_verified': True, 'model_api_calls': 0,
    }


if __name__ == '__main__':
    if len(sys.argv) > 1:
        raw = Path(sys.argv[1]).read_bytes()
    else:
        request = urllib.request.Request(URL, headers={'User-Agent': 'benchmark-cost-audit/1.0'})
        with urllib.request.urlopen(request, timeout=30) as response:
            html = response.read().decode('utf-8')
        parser = EmbeddedData()
        parser.feed(html)
        raw = ''.join(parser.parts).encode('utf-8')
    print(json.dumps(audit(raw), indent=2))

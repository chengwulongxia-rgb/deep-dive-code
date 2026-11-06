"""Test notebook-native pure cells without executing network/model cells."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

def notebook_namespace():
    nb = json.loads((ROOT / 'drcd_cpu.ipynb').read_text())
    ns = {}
    for cell in nb['cells']:
        if 'pure' in cell.get('metadata', {}).get('tags', []):
            exec(''.join(cell['source']), ns)
    return ns

class ScoringTests(unittest.TestCase):
    def test_normalized_em_and_character_multiset(self):
        ns = notebook_namespace()
        self.assertIn('score', ns, 'notebook scoring cell not implemented')
        score = ns['score']
        self.assertEqual(score(' 台灣，ABC。 ', ['台灣abc']), (1.0, 1.0))
        self.assertEqual(score('甲', ['乙']), (0.0, 0.0))
        self.assertEqual(score('答案乙', ['答案甲', '答案乙']), (1.0, 1.0))
        self.assertAlmostEqual(score('甲甲乙', ['甲乙乙'])[1], 2 / 3)
        self.assertEqual(score('', ['']), (0.0, 0.0))
        self.assertEqual(score('甲', ['甲'], error='timeout'), (0.0, 0.0))

class DesignTests(unittest.TestCase):
    def test_gold_never_affects_messages_or_routing(self):
        ns = notebook_namespace()
        self.assertIn('messages', ns)
        a = dict(id='x', paragraph='完整繁體段落', question='原題？', references=['秘密'])
        b = dict(a, references=['完全不同'])
        self.assertEqual(ns['messages'](a), ns['messages'](b))
        self.assertEqual(ns['small_ids']([a], 1), ns['small_ids']([b], 1))
        self.assertNotIn('秘密', repr(ns['messages'](a)))
        rows = [dict(id=str(i), references=['不可讀']) for i in range(8)]
        for share in [0, .25, .5, .75, 1]:
            self.assertEqual(len(ns['small_ids'](rows, share)), int(8 * share))
        self.assertEqual(ns['small_ids'](rows, .5), ns['small_ids'](rows[::-1], .5))

class ArtifactTests(unittest.TestCase):
    def test_frozen_manifest_context_disjoint(self):
        path = ROOT / 'results/drcd-cpu/sample-manifest.json'
        if not path.exists():
            self.skipTest('fresh run has not yet produced a manifest')
        import hashlib
        manifest = json.loads(path.read_text())
        self.assertEqual([len(manifest[k]) for k in ['dev', 'test', 'warmup']], [8, 24, 1])
        rows = manifest['dev'] + manifest['test'] + manifest['warmup']
        self.assertEqual(len({r['id'] for r in rows}), 33)
        self.assertEqual(len({r['context_sha256'] for r in rows}), 33)
        for row in rows:
            self.assertEqual(hashlib.sha256(row['paragraph'].encode()).hexdigest(), row['context_sha256'])

    def test_frozen_decision_precedes_true_test_dispatch(self):
        out = ROOT / 'results/drcd-cpu'
        if not (out / 'decision.json').exists() or not (out / 'summary.json').exists():
            self.skipTest('fresh inference has not yet finished')
        import hashlib
        d = json.loads((out / 'decision.json').read_text())
        proof = json.loads((out / 'decision-sha256.json').read_text())
        self.assertEqual(hashlib.sha256((out / 'decision.json').read_bytes()).hexdigest(), proof['sha256'])
        raw = [json.loads(s) for s in (out / 'raw-generations.jsonl').read_text().splitlines()]
        self.assertEqual(len(raw), 90)
        self.assertEqual([r['order'] for r in raw], list(range(90)))
        self.assertEqual(proof['first_test_order'], 18)
        for r in raw[18:]:
            self.assertEqual(r['phase'], 'test')
            self.assertGreaterEqual(r['started_monotonic'], d['frozen_at_monotonic'])
            if r['scheme'] == 'frozen_mix':
                self.assertEqual(r['model'], d['test_routes'][r['id']])
        for scheme in ['all_small', 'all_large', 'frozen_mix']:
            self.assertEqual(len([r for r in raw if r['scheme'] == scheme]), 24)
        self.assertTrue(all(v['stopped_verified'] and v['port_closed_verified'] for v in
                            json.loads((out / 'lifecycle.json').read_text()).values()))

if __name__ == '__main__':
    unittest.main()

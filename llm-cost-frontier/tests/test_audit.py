import json
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import audit_cost


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (ROOT / 'data/cost-data.json').read_bytes()
        cls.actual = audit_cost.audit(cls.raw)
        cls.original = json.loads((ROOT / 'results/cost-audit.json').read_text())

    def test_frozen_snapshot_and_scope(self):
        self.assertEqual(self.actual['snapshot'], '2026-10-26')
        self.assertEqual(self.actual['configurations_checked'], 45)
        self.assertTrue(self.actual['dual_certificate_verified'])

    def test_original_results_preserved(self):
        for new, old in [('baseline_usd_per_1000', 'baseline_cost_per_1000'),
                         ('blend_usd_per_1000', 'blend_cost_per_1000'),
                         ('saving_pct', 'savings_pct')]:
            self.assertTrue(math.isclose(self.actual[new], self.original[old], abs_tol=1e-12))
        self.assertEqual(self.actual['blend_scores'], self.original['blend_scores'])
        self.assertEqual(self.actual['target_scores'], self.original['target']['scores'])
        self.assertEqual(self.actual['cheapest_eligible_single'], self.original['best_single']['id'])

    def test_relaxed_constraint_is_not_full_success(self):
        self.assertEqual(self.actual['relaxed_single'], 'gpt-6-luna')
        self.assertFalse(self.actual['relaxed_passes_both'])
        self.assertLess(self.actual['relaxed_scores'][1], self.actual['target_scores'][1])

    def test_changed_snapshot_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Snapshot changed'):
            audit_cost.audit(self.raw + b'\n')

    def test_offline_audit_does_not_use_http(self):
        with patch.object(audit_cost.urllib.request, 'urlopen', side_effect=AssertionError('HTTP forbidden')):
            self.assertEqual(audit_cost.audit(self.raw), self.actual)


if __name__ == '__main__':
    unittest.main()

import importlib.util
import unittest


class ToyTests(unittest.TestCase):
    def test_deterministic_tournament(self):
        self.assertIsNotNone(importlib.util.find_spec('lab'), 'toy implementation is missing')
        from lab import toy_generate, toy_score
        a = toy_generate(256, seed=42, key=123, watermarked=True)
        self.assertEqual(a, toy_generate(256, seed=42, key=123, watermarked=True))
        self.assertGreater(toy_score(a, 123)['score'], toy_score(a, 456)['score'] + 0.15)

    def test_fixed_low_entropy_has_no_choice_and_little_evidence(self):
        from lab import toy_generate, toy_score
        plain = toy_generate(128, 5, 123, fixed=True)
        marked = toy_generate(128, 5, 123, watermarked=True, fixed=True)
        self.assertEqual(plain, marked)
        self.assertEqual(toy_score(marked, 123)['effective_tokens'], 1)
        self.assertIsNone(toy_score([], 123)['score'])
        import lab
        self.assertTrue(hasattr(lab, 'toy_detect'), 'toy decision rule missing')
        self.assertIsNone(lab.toy_detect(marked, 123)['detected'])
        uniform = toy_generate(256, 42, 123, watermarked=True)
        self.assertTrue(lab.toy_detect(uniform, 123)['detected'])
        self.assertFalse(lab.toy_detect(uniform, 456)['detected'])


class CalibrationTests(unittest.TestCase):
    def test_threshold_uses_calibration_plain_only(self):
        import lab
        self.assertTrue(hasattr(lab, 'calibrate'), 'calibration feature missing')
        rows = [dict(split='calibration', origin='plain', score=s) for s in [0.4, 0.6]]
        self.assertGreater(lab.calibrate(rows), 0.6)
        for invalid in [[], [dict(split='evaluation', origin='plain', score=0.9)],
                        [dict(split='calibration', origin='watermarked', score=0.9)],
                        [dict(split='calibration', origin='plain', score=None)]]:
            with self.assertRaises(ValueError):
                lab.calibrate(invalid)


class RealHelpersTests(unittest.TestCase):
    def test_official_masks_and_empty_scores(self):
        import lab
        self.assertTrue(hasattr(lab, 'real_score'), 'official processor scorer missing')
        from real_lab import make_processor
        processor = make_processor()
        from lab import real_score
        self.assertEqual(real_score([], processor, 50256)['effective_tokens'], 0)
        self.assertIsNone(real_score([1, 2], processor, 50256)['score'])
        self.assertEqual(real_score([7] * 20, processor, 50256)['effective_tokens'], 1)
        # First four positions cannot form a full ngram. EOS and all following excluded.
        scored = real_score([1, 2, 3, 4, 5, 50256, 6, 7], processor, 50256)
        self.assertEqual(scored['valid_mask'], [True, False, False, False])
        self.assertEqual(scored['effective_tokens'], 1)
        self.assertEqual(scored, real_score([1, 2, 3, 4, 5, 50256, 6, 7], processor, 50256))

    def test_disjoint_plan_and_deterministic_edits(self):
        import real_lab
        self.assertTrue(hasattr(real_lab, 'sample_plan'), 'sample plan missing')
        from real_lab import sample_plan, perturb
        cal, ev = sample_plan(64, 'calibration', 24), sample_plan(64, 'evaluation', 12)
        self.assertFalse(set(p['prompt'] for p in cal) & set(p['prompt'] for p in ev))
        self.assertFalse(set(p['seed'] for p in cal) & set(p['seed'] for p in ev))
        self.assertFalse(set(p['seed'] for p in cal) & set(p['seed'] for p in sample_plan(128, 'calibration', 24)))
        tokens = list(range(128))
        for condition, size in [('clean', 128), ('truncate_half', 64), ('delete_10pct', 116), ('replace_10pct', 128)]:
            a, edits = perturb(tokens, condition, 42, 50257)
            self.assertEqual(a, perturb(tokens, condition, 42, 50257)[0])
            self.assertEqual(len(a), size)
            if condition == 'replace_10pct':
                self.assertEqual(sum(a != b for a, b in zip(a, tokens)), 12)
        self.assertEqual(tokens, list(range(128)))

    def test_real_summary_calibrates_each_length_edit_and_key(self):
        import real_lab
        self.assertTrue(hasattr(real_lab, 'summarize'), 'real experiment summary missing')
        self.assertTrue(hasattr(real_lab, 'run_real'), 'real generation runner missing')
        rows = []
        for length in [64, 128]:
            for key in ['correct', 'wrong']:
                for condition in ['clean', 'truncate_half']:
                    for split, origin, score in [('calibration', 'plain', 0.6), ('evaluation', 'plain', 0.7), ('evaluation', 'watermarked', 0.8)]:
                        rows.append(dict(source_length=length, key_condition=key, condition=condition,
                                         split=split, origin=origin, score=score, effective_tokens=10))
        summary, thresholds = real_lab.summarize(rows)
        self.assertEqual(len(summary), 8)
        for row in summary:
            self.assertEqual(row['plain_detected'], 1)
            self.assertEqual(row['watermarked_detected'], 1)
            self.assertEqual(row['calibration_detected'], 0)
        self.assertTrue(all(0.6 < threshold < 0.61 for threshold in thresholds.values()))


class CLITests(unittest.TestCase):
    def test_saved_artifacts_audit_without_model(self):
        import pathlib
        import subprocess
        import sys
        self.assertTrue(pathlib.Path('audit.py').is_file(), 'artifact audit missing')
        if pathlib.Path('results/real.json').exists():
            checked = subprocess.run([sys.executable, 'audit.py', '--results', 'results'], check=True, capture_output=True, text=True)
            import json
            expected_count = json.loads(pathlib.Path('results/real.json').read_text())['counts']['score_rows']
            self.assertIn(str(expected_count), checked.stdout)

    def test_real_chart_shows_false_positives_as_bars(self):
        import json
        import pathlib
        import tempfile
        from unittest.mock import patch
        import matplotlib
        matplotlib.use('Agg')
        from matplotlib.axes import Axes
        from chart import make_chart
        data = json.loads(pathlib.Path('results/real.json').read_text())
        heights = []
        original = Axes.bar
        def record(ax, x, height, *args, **kwargs):
            heights.append((float(height), kwargs.get('label')))
            return original(ax, x, height, *args, **kwargs)
        with tempfile.TemporaryDirectory(dir='.') as temp:
            with patch.object(Axes, 'bar', record):
                make_chart(data, pathlib.Path(temp) / 'metrics.png')
        self.assertEqual(len(heights), 16)
        self.assertEqual(sum(label == 'Plain false positives' for _, label in heights), 2)
        self.assertIn((3 / 12, 'Plain false positives'), heights)
        self.assertEqual(sum(value == 1.0 for value, _ in heights), 8)

    def test_toy_json_trace_and_chart_offline(self):
        import json
        import os
        import pathlib
        import subprocess
        import sys
        import tempfile
        self.assertTrue(pathlib.Path('main.py').is_file(), 'CLI feature missing')
        with tempfile.TemporaryDirectory(dir='.') as temp:
            env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
            out = pathlib.Path(temp)
            subprocess.run([sys.executable, 'main.py', '--output', str(out)], env=env, check=True, capture_output=True)
            data = json.loads((out/'toy.json').read_text())
            self.assertTrue(data['trace']['rounds'])
            self.assertEqual(data['trace']['final_token'], data['trace']['rounds'][-1]['winners'][0])
            subprocess.run([sys.executable, 'main.py', '--chart', str(out/'plot.png'), '--input', str(out/'toy.json')], env=env, check=True, capture_output=True)
            self.assertGreater((out/'plot.png').stat().st_size, 1000)


if __name__ == '__main__':
    unittest.main()

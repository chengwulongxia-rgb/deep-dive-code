import math
import unittest

class BudgetTests(unittest.TestCase):
    def test_budget_reserves_teardown_and_counts_prior_attempts(self):
        from run_colab import limits
        result = limits(elapsed=100, prior_seconds=200, spent=0.5, rate=6)
        self.assertEqual(result['work_seconds'], 780)
        self.assertAlmostEqual(result['cu_remaining'], 4.5)
        self.assertTrue(result['can_work'])

    def test_refuses_invalid_or_exhausted_budgets(self):
        from run_colab import limits
        for key in ['elapsed', 'prior_seconds', 'spent', 'rate']:
            for value in [-1, math.nan, math.inf]:
                args = dict(elapsed=0, prior_seconds=0, spent=0, rate=6)
                args[key] = value
                with self.assertRaises(ValueError):
                    limits(**args)
        self.assertFalse(limits(elapsed=1080, prior_seconds=0, spent=0, rate=6)['can_work'])
        self.assertFalse(limits(elapsed=0, prior_seconds=0, spent=4.8, rate=6)['can_work'])

    def test_parse_usage_fails_closed(self):
        from run_colab import parse_usage
        self.assertEqual(parse_usage('Current balance: 396.30 compute units\nUsage rate: 4.82/hr\nActive assignments: 1'), (396.3, 4.82, 1))
        for text in ['', 'Current balance: nan compute units', 'Current balance: 0 compute units\nUsage rate: -1/hr\nActive assignments: 1']:
            with self.assertRaises(ValueError):
                parse_usage(text)

    def test_extract_rejects_traversal_and_symlinks(self):
        import tempfile
        from pathlib import Path
        import zipfile
        from run_colab import extract_results
        for name in ['../escape', '/absolute']:
            with tempfile.TemporaryDirectory() as td:
                archive = Path(td)/'result.zip'
                with zipfile.ZipFile(archive, 'w') as z:
                    z.writestr(name, 'x')
                with self.assertRaises(ValueError):
                    extract_results(archive, Path(td)/'out')
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td)/'result.zip'
            info = zipfile.ZipInfo('link'); info.external_attr = 0o120777 << 16
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr(info,'../escape')
            with self.assertRaises(ValueError):
                extract_results(archive,Path(td)/'out')

    def test_prior_budget_rejects_invalid_individual_attempts(self):
        from run_colab import prior_budget
        self.assertEqual(prior_budget([{'elapsed_seconds':10,'conservative_cu':0.1},{'elapsed_seconds':20,'conservative_cu':0.2}]),(30,0.30000000000000004))
        with self.assertRaises(ValueError):
            prior_budget([{'elapsed_seconds':-10,'conservative_cu':0.1},{'elapsed_seconds':20,'conservative_cu':0.2}])
        with self.assertRaises(KeyError):
            prior_budget([{'elapsed_seconds':10}])

if __name__ == '__main__':
    unittest.main()

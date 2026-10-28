import io
import math
from pathlib import Path
import tempfile
import unittest
import zipfile


class RunnerTests(unittest.TestCase):
    def test_failed_generation_artifacts_are_downloaded_before_raise(self):
        import run_colab as runner
        source = Path(runner.__file__).read_text()
        self.assertLess(source.index("command('download-results'"), source.index("raise RuntimeError('Remote generation failed"))

    def test_transfer_commands_use_positional_paths(self):
        import ast
        import run_colab as runner
        tree = ast.parse(Path(runner.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'command':
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and node.args[1].value in ('upload', 'download'):
                    literals = [a.value for a in node.args if isinstance(a, ast.Constant)]
                    self.assertNotIn('-o', literals)
                    self.assertNotIn('-d', literals)

    def test_budget_expiry_cannot_be_swallowed_by_http_timeout_retries(self):
        import run_colab as runner
        self.assertTrue(hasattr(runner, 'BudgetExpired'))
        self.assertTrue(issubclass(runner.BudgetExpired, BaseException))
        self.assertFalse(issubclass(runner.BudgetExpired, Exception))

    def test_budget_reserves_cleanup_and_counts_failures(self):
        import run_colab as runner
        self.assertEqual(runner.remaining_seconds([{'elapsed_seconds': 70}, {'elapsed_seconds': 30}]), 980)
        with self.assertRaises(ValueError):
            runner.remaining_seconds([{'elapsed_seconds': 1100}])
        for bad in [-1, math.inf, math.nan]:
            with self.assertRaises(ValueError):
                runner.remaining_seconds([{'elapsed_seconds': bad}])

    def test_zip_slip_is_rejected(self):
        import run_colab as runner
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / 'result.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('../escape.txt', b'bad')
            with self.assertRaises(ValueError):
                runner.extract_artifacts(archive, Path(td) / 'artifacts')
            self.assertFalse((Path(td) / 'escape.txt').exists())

    def test_valid_archive(self):
        import run_colab as runner
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / 'result.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('parameters.json', b'{}')
            runner.extract_artifacts(archive, Path(td) / 'artifacts')
            self.assertEqual((Path(td) / 'artifacts' / 'parameters.json').read_bytes(), b'{}')

if __name__ == '__main__':
    unittest.main()

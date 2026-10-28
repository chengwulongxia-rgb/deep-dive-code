"""Checks for the notebook-first entry; never allocates a GPU."""
import ast
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent


class NativeNotebookTests(unittest.TestCase):
    def test_experiment_is_native_cells_not_external_script_wrapper(self):
        notebook = json.loads((HERE / 'experiment.ipynb').read_text())
        cells = [cell for cell in notebook['cells'] if cell['cell_type'] == 'code']
        self.assertGreaterEqual(len(cells), 14)
        combined = '\n'.join(''.join(cell['source']) for cell in cells)
        for forbidden in ['benchmark.py', 'bootstrap.py', 'build_notebook.py', '%run ', 'exec(', 'import benchmark']:
            self.assertNotIn(forbidden, combined)
        definitions = set()
        for cell in cells:
            tree = ast.parse(''.join(cell['source']))
            definitions.update(node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ['write_text', 'write_bytes']:
                    self.assertNotIn('.py', ast.unparse(node.func.value))
        self.assertTrue({'build_messages', 'evaluate', 'run_case', 'summarize', 'generate', 'unwrap_one_fence'} <= definitions)


if __name__ == '__main__':
    unittest.main()

import ast
from pathlib import Path
import unittest

class BootstrapTests(unittest.TestCase):
    def test_isolated_install_preserves_colab_packages(self):
        path = Path(__file__).parent / 'bootstrap.py'
        self.assertTrue(path.exists(), 'isolated bootstrap is required')
        source = path.read_text()
        ast.parse(source)
        self.assertIn('--system-site-packages', source)
        self.assertIn('sha256', source)
        self.assertIn('uv', source)
        self.assertIn('--excludes', source)
        self.assertIn("exclude.write_text", source)
        self.assertIn("env.pop('UV_SYSTEM_PYTHON'", source)
        self.assertNotIn("[sys.executable, '-m', 'pip'", source)

    def test_supported_transformers_and_pytorch_only_backend(self):
        root = Path(__file__).parent
        self.assertIn('transformers==4.55.4', (root/'requirements.txt').read_text())
        source = (root/'generate.py').read_text()
        self.assertIn("os.environ['USE_TF'] = '0'", source)
        self.assertNotIn('filterwarnings', source)

if __name__ == '__main__':
    unittest.main()

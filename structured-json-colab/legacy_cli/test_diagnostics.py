import unittest

class DiagnosticTests(unittest.TestCase):
    def test_removes_only_one_complete_markdown_json_fence(self):
        from diagnostics import unwrap_one_fence
        self.assertEqual(unwrap_one_fence('```json\n{"x":1}\n```'),'{"x":1}')
        self.assertEqual(unwrap_one_fence('```\n{"x":1}\n```'),'{"x":1}')
        for raw in ['説明\n```json\n{}\n```','```json\n{}','{}','```python\n{}\n```']:
            self.assertEqual(unwrap_one_fence(raw),raw)

if __name__=='__main__':
    unittest.main()

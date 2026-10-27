import ast
import json
from pathlib import Path
import unittest

HERE = Path(__file__).parent

class SmokeTests(unittest.TestCase):
    def test_requests(self):
        import remote_smoke as smoke
        dom = json.loads((HERE / 'cwa_dom.json').read_text())
        cases = smoke.build_cases(dom)
        self.assertEqual(len(cases), 1)
        self.assertEqual(smoke.LABELS, {'user_original_zh': 'table_1'})
        self.assertEqual(cases[0]['request']['questions']['selection']['instructions'], '鹿野鄉今晚的降雨機率')
        self.assertTrue(all(value is None for value in cases[0]['request']['questions']['selection']['criteria'].values()))
        self.assertEqual([t['id'] for t in dom['tables']], ['table_0', 'table_1', 'table_2'])
        self.assertEqual(dom['tables'][1]['caption'], '逐三小時天氣預報資料')
        self.assertEqual(dom['tables'][2]['caption'], '沿海逐三小時預報')
        for case in cases:
            payload = case['request']
            self.assertEqual(set(payload), {'state', 'questions'})
            self.assertLessEqual(len(payload['state']), 6000)
            self.assertFalse(any(word in json.dumps(payload) for word in ['expected', 'correct_choice', 'LABELS']))
            choices = payload['questions']['selection']['criteria']
            self.assertIn(smoke.LABELS[case['id']], choices)
            self.assertEqual(set(choices), {'table_0', 'table_1', 'table_2'})
            state = json.loads(payload['state'])
            forecast = state['candidates'][1]
            self.assertIn('降雨機率', [row[0]['text'] for row in forecast['rows'] if row])
        # Changing evaluation labels cannot alter a request sent to the model.
        old = smoke.LABELS.copy()
        try:
            smoke.LABELS.update({k: 'SENTINEL_SECRET_LABEL' for k in old})
            self.assertEqual(cases, smoke.build_cases(dom))
        finally:
            smoke.LABELS.clear(); smoke.LABELS.update(old)

    def test_notebook_clean(self):
        nb = json.loads((HERE / 'smoke.ipynb').read_text())
        self.assertEqual(nb['nbformat'], 4)
        for cell in nb['cells']:
            if cell['cell_type'] == 'code':
                self.assertEqual(cell['outputs'], [])
                self.assertIsNone(cell['execution_count'])
                ast.parse(''.join(cell['source']))
        text = json.dumps(nb, ensure_ascii=False)
        self.assertIn('鹿野鄉今晚的降雨機率', text)
        self.assertNotIn('REPO_REVISION', text)
        self.assertNotIn('REPO_OWNER', text)
        written = {}
        for cell in nb['cells']:
            if cell['cell_type'] != 'code':
                continue
            for node in ast.walk(ast.parse(''.join(cell['source']))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'write_text':
                    target = node.func.value
                    if isinstance(target, ast.Call) and target.args and isinstance(target.args[0], ast.Constant):
                        written[target.args[0].value] = ast.literal_eval(node.args[0])
        self.assertEqual(written['/content/remote_smoke.py'], (HERE / 'remote_smoke.py').read_text())
        self.assertEqual(written['/content/cwa_dom.json'], (HERE / 'cwa_dom.json').read_text())

if __name__ == '__main__':
    unittest.main()

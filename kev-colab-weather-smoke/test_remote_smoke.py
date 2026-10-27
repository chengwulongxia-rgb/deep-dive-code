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

if __name__ == '__main__':
    unittest.main()

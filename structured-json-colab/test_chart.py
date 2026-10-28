import json
from pathlib import Path
import tempfile
import unittest


class ChartTests(unittest.TestCase):
    def test_refuses_incomplete_experiment(self):
        from chart import plot
        with tempfile.TemporaryDirectory() as td:
            report=Path(td)/'report.json'
            report.write_text(json.dumps({'status':'failed','summary':{}}))
            with self.assertRaises(ValueError):
                plot(report,Path(td)/'chart.png')
            self.assertFalse((Path(td)/'chart.png').exists())

if __name__=='__main__':
    unittest.main()

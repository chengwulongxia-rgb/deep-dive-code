import json
from pathlib import Path
import tempfile
import unittest


class EvidenceTests(unittest.TestCase):
    def test_completed_flag_alone_cannot_pass_verification(self):
        from verify_results import verify
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)
            (d/'report.json').write_text(json.dumps({'status':'completed'}))
            (d/'results.jsonl').write_text('')
            (d/'inputs.json').write_text(Path('fixtures.json').read_text())
            with self.assertRaises(ValueError):
                verify(d)

if __name__=='__main__':
    unittest.main()

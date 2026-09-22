from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from kev_gate import KevClient, SupportCase, decide_support_case


class FakeKevHandler(BaseHTTPRequestHandler):
    answer_probability = 0.95
    body: dict[str, object] | None = None

    def do_POST(self) -> None:  # noqa: N802
        type(self).body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        payload = {
            "answers": {
                "department": {
                    "choice": "billing",
                    "probabilities": {"billing": 0.91, "shipping": 0.06, "returns": 0.03},
                },
                "refund_authorization": {"probability": type(self).answer_probability},
            }
        }
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        return


class KevGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeKevHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = KevClient(f"http://127.0.0.1:{self.server.server_port}")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def test_low_value_high_confidence_refund_is_auto_authorized(self) -> None:
        FakeKevHandler.answer_probability = 0.95
        decision = decide_support_case(
            self.client,
            SupportCase("I was charged twice for my order.", refund_amount_usd=120),
        )
        self.assertEqual(decision.department, "billing")
        self.assertEqual(decision.refund_action, "auto_authorize")
        self.assertEqual(FakeKevHandler.body["model"], "kev-latest")
        self.assertIn("department", FakeKevHandler.body["questions"])

    def test_large_refund_is_escalated_even_when_kev_is_confident(self) -> None:
        FakeKevHandler.answer_probability = 0.99
        decision = decide_support_case(
            self.client,
            SupportCase("I was charged twice for my order.", refund_amount_usd=375),
        )
        self.assertEqual(decision.refund_action, "escalate_to_human")


if __name__ == "__main__":
    unittest.main()

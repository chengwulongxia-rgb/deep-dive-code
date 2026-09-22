from __future__ import annotations

import unittest

from adk_dispatch import route_support_request
from kev_gate import SupportCase


class RoutedFixture:
    def __init__(self, *, choice: str, confidence: float) -> None:
        self.choice = choice
        self.confidence = confidence

    def decide(self, *, state: object, questions: dict[str, object]) -> dict[str, object]:
        return {
            "support_route": {
                "choice": self.choice,
                "probabilities": {
                    "billing": self.confidence if self.choice == "billing" else 0.01,
                    "shipping": self.confidence if self.choice == "shipping" else 0.01,
                    "returns": self.confidence if self.choice == "returns" else 0.01,
                    "supervisor": self.confidence if self.choice == "supervisor" else 0.01,
                },
            }
        }


class AdkDispatchTests(unittest.TestCase):
    def test_high_confidence_billing_route_exposes_only_billing_tools(self) -> None:
        dispatch = route_support_request(
            RoutedFixture(choice="billing", confidence=0.94),
            SupportCase("My card was charged twice.", refund_amount_usd=40),
        )
        self.assertEqual(dispatch.agent_name, "billing_agent")
        self.assertEqual(dispatch.tools, ("lookup_invoice", "lookup_payment", "create_refund_draft"))
        self.assertFalse(dispatch.used_supervisor)

    def test_low_confidence_route_falls_back_to_full_supervisor(self) -> None:
        dispatch = route_support_request(
            RoutedFixture(choice="shipping", confidence=0.62),
            SupportCase("Where is my parcel?", refund_amount_usd=0),
        )
        self.assertEqual(dispatch.agent_name, "supervisor_agent")
        self.assertTrue(dispatch.used_supervisor)
        self.assertGreater(len(dispatch.tools), 3)


if __name__ == "__main__":
    unittest.main()

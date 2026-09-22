from __future__ import annotations

import unittest

from adk_agent_factory import build_support_agents


class AdkAgentFactoryTests(unittest.TestCase):
    def test_billing_agent_has_only_its_specialist_tools(self) -> None:
        agents = build_support_agents(model="gemini-2.5-flash")
        self.assertEqual(agents["billing_agent"].name, "billing_agent")
        self.assertEqual(
            {tool.__name__ for tool in agents["billing_agent"].tools},
            {"lookup_invoice", "lookup_payment", "create_refund_draft"},
        )
        self.assertGreater(len(agents["supervisor_agent"].tools), 3)


if __name__ == "__main__":
    unittest.main()

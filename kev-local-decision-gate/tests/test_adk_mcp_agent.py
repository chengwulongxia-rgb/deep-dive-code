from __future__ import annotations

import unittest

from adk_dispatch import AdkDispatch
from adk_mcp_agent import build_selected_mcp_agent


class AdkMcpAgentTests(unittest.TestCase):
    def test_selected_agent_filters_mcp_tools_to_the_kev_route(self) -> None:
        dispatch = AdkDispatch(
            agent_name="billing_agent",
            tools=("lookup_invoice", "lookup_payment", "create_refund_draft"),
            route_confidence=0.94,
            used_supervisor=False,
        )
        agent, toolset = build_selected_mcp_agent(
            dispatch,
            mcp_url="http://127.0.0.1:9999/mcp",
            model="gemini-2.5-flash",
        )
        self.assertEqual(agent.name, "billing_agent")
        self.assertEqual(toolset.tool_filter, list(dispatch.tools))
        self.assertEqual(agent.tools, [toolset])


if __name__ == "__main__":
    unittest.main()

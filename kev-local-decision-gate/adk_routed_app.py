"""Run one routed Google ADK turn after Kev has narrowed the tool schema.

Requires GOOGLE_API_KEY plus a reachable local Kev server. This entrypoint is
separate from main.py so the offline implementation remains runnable without
cloud credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from adk_dispatch import route_support_request
from adk_mcp_agent import build_selected_mcp_agent
from kev_gate import KevClient, SupportCase


async def run_turn(*, kev_url: str, mcp_url: str, ticket: str, amount: int) -> None:
    dispatch = route_support_request(KevClient(kev_url), SupportCase(ticket, amount))
    agent, toolset = build_selected_mcp_agent(dispatch, mcp_url=mcp_url)
    session_service = InMemorySessionService()
    session_id = uuid.uuid4().hex
    await session_service.create_session(
        app_name="kev_adk_support",
        user_id="local_demo",
        session_id=session_id,
    )
    runner = Runner(
        agent=agent,
        app_name="kev_adk_support",
        session_service=session_service,
    )
    print(f"kev_route={dispatch.agent_name} confidence={dispatch.route_confidence:.0%}")
    print(f"adk_mcp_tool_filter={', '.join(dispatch.tools)}")
    try:
        async for event in runner.run_async(
            user_id="local_demo",
            session_id=session_id,
            new_message=types.Content(role="user", parts=[types.Part(text=ticket)]),
        ):
            if event.is_final_response() and event.content and event.content.parts:
                print("agent_response=" + "".join(part.text or "" for part in event.content.parts))
    finally:
        await toolset.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kev-url", required=True)
    parser.add_argument("--mcp-url", required=True, help="Streamable HTTP endpoint for the existing tool MCP server")
    parser.add_argument("--ticket", default="I was charged twice for my order.")
    parser.add_argument("--amount", type=int, default=40)
    args = parser.parse_args()
    if not os.environ.get("GOOGLE_API_KEY"):
        parser.error("GOOGLE_API_KEY is required for the ADK/Gemini agent turn")
    asyncio.run(
        run_turn(kev_url=args.kev_url, mcp_url=args.mcp_url, ticket=args.ticket, amount=args.amount)
    )


if __name__ == "__main__":
    main()

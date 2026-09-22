"""Official ADK McpToolset integration for a Kev-selected tool subset."""

from __future__ import annotations

from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

from adk_dispatch import AdkDispatch


def build_selected_mcp_agent(
    dispatch: AdkDispatch,
    *,
    mcp_url: str,
    model: str = "gemini-2.5-flash",
    headers: dict[str, Any] | None = None,
) -> tuple[LlmAgent, McpToolset]:
    """Build one ADK agent exposing only Kev's selected MCP tool names.

    The caller owns the returned toolset lifecycle and should await close() after
    the ADK Runner turn. This lazy factory avoids opening MCP sessions for routes
    Kev did not select.
    """
    toolset = McpToolset(
        connection_params=StreamableHTTPConnectionParams(url=mcp_url, headers=headers),
        tool_filter=list(dispatch.tools),
    )
    agent = LlmAgent(
        name=dispatch.agent_name,
        model=model,
        instruction=(
            "Use only the MCP tools available to you. Do not invent tool results. "
            "If the request cannot be completed from this tool subset, explain that "
            "it requires supervisor escalation."
        ),
        tools=[toolset],
    )
    return agent, toolset

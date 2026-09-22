"""Kev pre-dispatch for an ADK multi-agent support application.

This runs before any LlmAgent invocation. It is intentionally not an ADK callback:
a callback runs after the broad agent and its tool schemas have already entered
the request, which cannot reduce that request's planning cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from kev_gate import SupportCase


class RoutingClient(Protocol):
    def decide(self, *, state: object, questions: dict[str, object]) -> dict[str, object]: ...


SUPERVISOR_TOOLS = (
    "lookup_invoice",
    "lookup_payment",
    "create_refund_draft",
    "lookup_tracking",
    "contact_carrier",
    "start_return",
    "lookup_return_policy",
    "request_human_review",
)
ROUTE_TOOLS = {
    "billing": ("lookup_invoice", "lookup_payment", "create_refund_draft"),
    "shipping": ("lookup_tracking", "contact_carrier"),
    "returns": ("start_return", "lookup_return_policy"),
}


@dataclass(frozen=True)
class AdkDispatch:
    agent_name: str
    tools: tuple[str, ...]
    route_confidence: float
    used_supervisor: bool


def route_support_request(client: RoutingClient, case: SupportCase) -> AdkDispatch:
    """Choose a narrow ADK agent, or deliberately fall back to broad planning."""
    answers = client.decide(
        state={"ticket": case.ticket, "refund_amount_usd": case.refund_amount_usd},
        questions={
            "support_route": {
                "type": "choice",
                "instructions": "Which support workflow should own this request?",
                "criteria": {
                    "billing": "payments, charges, invoices, duplicate charges",
                    "shipping": "delivery delay, tracking, carrier status",
                    "returns": "return, exchange, refund policy",
                    "supervisor": "ambiguous, multi-domain, or high-risk request",
                },
            }
        },
    )
    try:
        route = str(answers["support_route"]["choice"])
        confidence = float(answers["support_route"]["probabilities"][route])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Kev route response does not match the expected schema") from exc

    # The 0.85 threshold must later be calibrated from route outcomes.
    if route not in ROUTE_TOOLS or confidence < 0.85:
        return AdkDispatch("supervisor_agent", SUPERVISOR_TOOLS, confidence, True)
    return AdkDispatch(f"{route}_agent", ROUTE_TOOLS[route], confidence, False)

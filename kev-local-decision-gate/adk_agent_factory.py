"""Concrete Google ADK specialist agents for Kev pre-dispatch.

This module builds real ADK LlmAgent objects. A caller should first use
adk_dispatch.route_support_request(), then run only the selected agent.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent


def lookup_invoice(invoice_id: str) -> dict[str, str]:
    """Read a billing invoice by ID. This example returns a deterministic stub."""
    return {"invoice_id": invoice_id, "status": "found"}


def lookup_payment(payment_id: str) -> dict[str, str]:
    """Read a payment by ID. This example returns a deterministic stub."""
    return {"payment_id": payment_id, "status": "found"}


def create_refund_draft(payment_id: str, amount_usd: int) -> dict[str, object]:
    """Create a reversible refund draft; a separate policy must approve it."""
    return {"payment_id": payment_id, "amount_usd": amount_usd, "status": "draft_only"}


def lookup_tracking(order_id: str) -> dict[str, str]:
    """Look up carrier tracking for an order."""
    return {"order_id": order_id, "status": "in_transit"}


def contact_carrier(order_id: str) -> dict[str, str]:
    """Open a carrier-support ticket for an order."""
    return {"order_id": order_id, "status": "carrier_ticket_opened"}


def start_return(order_id: str) -> dict[str, str]:
    """Start a reversible product-return workflow."""
    return {"order_id": order_id, "status": "return_started"}


def lookup_return_policy(product_id: str) -> dict[str, str]:
    """Read the return policy applicable to a product."""
    return {"product_id": product_id, "policy": "30_day_return_window"}


def request_human_review(reason: str) -> dict[str, str]:
    """Escalate an ambiguous or high-risk case to a human queue."""
    return {"status": "queued_for_human", "reason": reason}


def build_support_agents(*, model: str = "gemini-2.5-flash") -> dict[str, LlmAgent]:
    """Create route-specific agents plus one intentionally broad fallback."""
    shared = "Use only your available tools. Never claim a tool result you did not receive."
    return {
        "billing_agent": LlmAgent(
            name="billing_agent", model=model, instruction=shared,
            tools=[lookup_invoice, lookup_payment, create_refund_draft],
        ),
        "shipping_agent": LlmAgent(
            name="shipping_agent", model=model, instruction=shared,
            tools=[lookup_tracking, contact_carrier],
        ),
        "returns_agent": LlmAgent(
            name="returns_agent", model=model, instruction=shared,
            tools=[start_return, lookup_return_policy],
        ),
        "supervisor_agent": LlmAgent(
            name="supervisor_agent", model=model,
            instruction=shared + " Escalate uncertain or irreversible requests.",
            tools=[
                lookup_invoice, lookup_payment, create_refund_draft,
                lookup_tracking, contact_carrier, start_return,
                lookup_return_policy, request_human_review,
            ],
        ),
    }

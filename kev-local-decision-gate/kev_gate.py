"""Kev System One client plus deterministic authorization policy.

Kev supplies semantic probabilities. This module deliberately keeps the
irreversible-action policy in ordinary, auditable Python code.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class KevError(RuntimeError):
    """The Kev endpoint was unavailable or did not honor the response contract."""


class DecisionClient(Protocol):
    def decide(self, *, state: object, questions: dict[str, object]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SupportCase:
    ticket: str
    refund_amount_usd: int


@dataclass(frozen=True)
class SupportDecision:
    department: str
    department_confidence: float
    refund_probability: float
    refund_action: str


class KevClient:
    """Dependency-free client for Kev's TypeSafe-compatible endpoint."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 15.0) -> None:
        self._endpoint = f"{base_url.rstrip('/')}/v1/systemone"
        self._timeout_seconds = timeout_seconds

    def decide(self, *, state: object, questions: dict[str, object]) -> dict[str, Any]:
        request = Request(
            self._endpoint,
            data=json.dumps({"model": "kev-latest", "state": state, "questions": questions}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                response_data = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise KevError(f"Kev request failed: {exc}") from exc
        if not isinstance(response_data, dict) or not isinstance(response_data.get("answers"), dict):
            raise KevError("Kev response must contain an 'answers' object")
        return response_data["answers"]


class FixtureKevClient:
    """Offline fixture for teaching and testing the safety policy, not a model."""

    def decide(self, *, state: object, questions: dict[str, object]) -> dict[str, Any]:
        return {
            "department": {
                "choice": "billing",
                "probabilities": {"billing": 0.91, "shipping": 0.06, "returns": 0.03},
            },
            "refund_authorization": {"probability": 0.73},
        }


def support_questions() -> dict[str, object]:
    return {
        "department": {
            "type": "choice",
            "instructions": "Which team owns this support request?",
            "criteria": {
                "billing": "charges, invoices, payments, duplicate charges",
                "shipping": "delivery delay, tracking, carrier issue",
                "returns": "return, exchange, refund for a product",
            },
        },
        "refund_authorization": {
            "type": "noul",
            "instructions": "May the agent authorize a refund without human review?",
            "criteria": {
                "true": "The evidence is clear and the amount is at most 200 USD.",
                "false": "Evidence is incomplete or the amount exceeds 200 USD.",
            },
        },
    }


def decide_support_case(client: DecisionClient, case: SupportCase) -> SupportDecision:
    """Use Kev for interpretation, then use fixed policy to authorize or escalate."""
    answers = client.decide(
        state={"ticket": case.ticket, "refund_amount_usd": case.refund_amount_usd},
        questions=support_questions(),
    )
    try:
        department = answers["department"]
        authorization = answers["refund_authorization"]
        choice = str(department["choice"])
        confidence = float(department["probabilities"][choice])
        refund_probability = float(authorization["probability"])
    except (KeyError, TypeError, ValueError) as exc:
        raise KevError("Kev response does not match the expected support schema") from exc

    auto_authorize = (
        case.refund_amount_usd <= 200
        and confidence >= 0.85
        and refund_probability >= 0.90
    )
    return SupportDecision(
        department=choice,
        department_confidence=confidence,
        refund_probability=refund_probability,
        refund_action="auto_authorize" if auto_authorize else "escalate_to_human",
    )

"""Run an offline safety demonstration or call a self-hosted Kev endpoint."""

from __future__ import annotations

import argparse
from pathlib import Path

from kev_gate import FixtureKevClient, KevClient, SupportCase, decide_support_case


def make_chart(output: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output.parent.mkdir(parents=True, exist_ok=True)
    amounts = [0, 50, 100, 150, 200, 250, 300, 350, 400]
    confidence = [0.73] * len(amounts)
    colors = ["#ef8354" if amount <= 200 else "#d9534f" for amount in amounts]
    plt.rcParams.update({"figure.facecolor": "#151a28", "axes.facecolor": "#151a28", "text.color": "#f3f4f6", "axes.labelcolor": "#f3f4f6", "xtick.color": "#f3f4f6", "ytick.color": "#f3f4f6"})
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.bar([str(amount) for amount in amounts], confidence, color=colors)
    ax.axhline(0.90, color="#70d6ff", linestyle="--", label="Kev confidence gate: 0.90")
    ax.axvline(4.5, color="#ffd166", linestyle="--", label="Refund cap: $200")
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("Refund amount (USD)")
    ax.set_ylabel("Kev refund-authorization probability")
    ax.set_title("A model probability is necessary, never sufficient")
    ax.legend(frameon=False)
    fig.text(0.5, 0.01, "Offline fixture probability 0.73. Real production thresholds require calibration on your own labeled outcomes.", ha="center", color="#aab2c0", fontsize=9)
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    fig.savefig(output, dpi=150, facecolor="#151a28")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kev-url", help="Self-hosted Kev server, e.g. http://localhost:8009")
    parser.add_argument("--ticket", default="I was charged twice for my order.")
    parser.add_argument("--amount", type=int, default=375, help="Refund amount in USD")
    parser.add_argument("--chart", type=Path, help="Write an offline decision-boundary chart and exit")
    args = parser.parse_args()

    if args.chart:
        make_chart(args.chart)
        print(f"Wrote {args.chart}")
        return

    client = KevClient(args.kev_url) if args.kev_url else FixtureKevClient()
    decision = decide_support_case(client, SupportCase(args.ticket, args.amount))
    print(f"department={decision.department} ({decision.department_confidence:.0%})")
    print(f"refund_probability={decision.refund_probability:.0%}")
    print(f"action={decision.refund_action}")
    if not args.kev_url:
        print("source=offline fixture (pass --kev-url to call a self-hosted Kev server)")


if __name__ == "__main__":
    main()

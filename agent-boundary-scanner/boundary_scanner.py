"""Static checks for files that let untrusted project content cross trust boundaries."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path


SEVERITIES = ("critical", "high", "medium", "low")


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    path: str
    evidence: str
    message: str


def scan_path(root: Path) -> list[Finding]:
    """Scan a repository directory without running any project code."""
    findings: list[Finding] = []
    findings.extend(_scan_package_json(root))
    findings.extend(_scan_yardopts(root))
    findings.extend(_scan_workflows(root))
    return sorted(findings, key=lambda item: (SEVERITIES.index(item.severity), item.path))


def summarize(findings: list[Finding]) -> dict[str, int]:
    counts = {severity: 0 for severity in SEVERITIES}
    for finding in findings:
        counts[finding.severity] += 1
    return counts


def _scan_package_json(root: Path) -> list[Finding]:
    package_file = root / "package.json"
    if not package_file.is_file():
        return []

    try:
        data = json.loads(package_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    scripts = data.get("scripts", {})
    if not isinstance(scripts, dict):
        return []

    lifecycle = ("preinstall", "install", "postinstall", "prepublish", "prepare")
    findings = []
    for name in lifecycle:
        command = scripts.get(name)
        if isinstance(command, str):
            findings.append(
                Finding(
                    rule_id="package-lifecycle-script",
                    severity="high",
                    path="package.json",
                    evidence=f"{name}: {command}",
                    message="Package lifecycle scripts can execute project-controlled code during installation.",
                )
            )
    return findings


def _scan_yardopts(root: Path) -> list[Finding]:
    options = root / ".yardopts"
    if not options.is_file():
        return []

    findings = []
    for line in options.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith("--load"):
            findings.append(
                Finding(
                    rule_id="yardopts-load",
                    severity="high",
                    path=".yardopts",
                    evidence=line.strip(),
                    message="YARD can load project-controlled Ruby during documentation generation.",
                )
            )
    return findings


def _scan_workflows(root: Path) -> list[Finding]:
    workflows = root / ".github" / "workflows"
    if not workflows.is_dir():
        return []

    findings = []
    for workflow in sorted((*workflows.glob("*.yml"), *workflows.glob("*.yaml"))):
        text = workflow.read_text(encoding="utf-8", errors="replace")
        if (
            "pull_request_target" in text
            and "actions/checkout" in text
            and "github.event.pull_request.head.sha" in text
        ):
            findings.append(
                Finding(
                    rule_id="privileged-pr-head-checkout",
                    severity="critical",
                    path=workflow.relative_to(root).as_posix(),
                    evidence="pull_request_target + checkout of github.event.pull_request.head.sha",
                    message="A privileged pull-request workflow checks out contributor-controlled code.",
                )
            )
    return findings


def make_chart(summary: dict[str, int], output_path: Path) -> None:
    """Render a local PNG severity summary without sending scan data anywhere."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    levels = ["critical", "high", "medium", "low"]
    values = [summary[level] for level in levels]
    colors = ["#fb7185", "#f59e0b", "#38bdf8", "#94a3b8"]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")
    bars = ax.bar(levels, values, color=colors, width=0.62)
    ax.set_title("Agent Boundary Scanner: findings by severity", color="#e6edf3", pad=16)
    ax.set_ylabel("Finding count", color="#c9d1d9")
    ax.grid(axis="y", color="#30363d", alpha=0.7)
    ax.tick_params(colors="#c9d1d9")
    for spine in ax.spines.values():
        spine.set_color("#30363d")
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.04, str(value), ha="center", color="#e6edf3")
    fig.text(0.5, 0.01, "Static local scan; a finding requires review, not automatic attribution.", ha="center", color="#8b949e", fontsize=9)
    fig.tight_layout(rect=[0, 0.05, 1, 1])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, facecolor="#0d1117")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find static trust-boundary risks without executing project code."
    )
    parser.add_argument("path", type=Path, help="Project directory to scan")
    parser.add_argument("--json", action="store_true", help="Emit a JSON report")
    parser.add_argument("--chart", type=Path, metavar="PNG", help="Write a PNG severity chart")
    args = parser.parse_args()

    findings = scan_path(args.path)
    report = {"summary": summarize(findings), "findings": [asdict(item) for item in findings]}
    if args.chart:
        make_chart(report["summary"], args.chart)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("Trust-boundary scan")
        print(" ".join(f"{level}={count}" for level, count in report["summary"].items()))
        for item in findings:
            print(f"[{item.severity.upper()}] {item.path}: {item.message} ({item.evidence})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

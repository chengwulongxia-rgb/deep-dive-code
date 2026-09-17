from pathlib import Path
import json
import subprocess
import sys

from boundary_scanner import scan_path, summarize


ROOT = Path(__file__).parents[1]


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_flags_package_lifecycle_script_as_untrusted_code_execution(tmp_path: Path) -> None:
    write(
        tmp_path / "package.json",
        '{"scripts": {"preinstall": "node scripts/setup.js", "test": "pytest"}}',
    )

    findings = scan_path(tmp_path)

    finding = next(item for item in findings if item.rule_id == "package-lifecycle-script")
    assert finding.severity == "high"
    assert finding.path == "package.json"
    assert "preinstall" in finding.evidence


def test_flags_yardopts_as_doc_builder_execution_boundary(tmp_path: Path) -> None:
    write(tmp_path / ".yardopts", "--load hack.rb\n")

    findings = scan_path(tmp_path)

    finding = next(item for item in findings if item.rule_id == "yardopts-load")
    assert finding.severity == "high"
    assert "hack.rb" in finding.evidence


def test_flags_privileged_pull_request_workflow_that_checks_out_head(tmp_path: Path) -> None:
    write(
        tmp_path / ".github" / "workflows" / "publish.yml",
        """name: publish
on: pull_request_target
jobs:
  build:
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}
      - run: ./build-docs.sh
""",
    )

    findings = scan_path(tmp_path)

    finding = next(item for item in findings if item.rule_id == "privileged-pr-head-checkout")
    assert finding.severity == "critical"
    assert finding.path == ".github/workflows/publish.yml"


def test_summary_counts_findings_by_severity(tmp_path: Path) -> None:
    write(tmp_path / ".yardopts", "--load probe.rb\n")
    write(tmp_path / "package.json", '{"scripts": {"postinstall": "node build.js"}}')

    summary = summarize(scan_path(tmp_path))

    assert summary == {"critical": 0, "high": 2, "medium": 0, "low": 0}


def test_ignores_regular_project_files(tmp_path: Path) -> None:
    write(tmp_path / "README.md", "# Safe project\n")
    write(tmp_path / "package.json", '{"scripts": {"test": "pytest"}}')

    assert scan_path(tmp_path) == []


def test_cli_emits_machine_readable_findings_for_fixture() -> None:
    result = subprocess.run(
        [sys.executable, "boundary_scanner.py", "fixtures/risky-package", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    report = json.loads(result.stdout)
    assert report["summary"] == {"critical": 1, "high": 2, "medium": 0, "low": 0}
    assert {item["rule_id"] for item in report["findings"]} == {
        "package-lifecycle-script",
        "yardopts-load",
        "privileged-pr-head-checkout",
    }


def test_cli_writes_a_png_chart_for_the_fixture(tmp_path: Path) -> None:
    chart = tmp_path / "risk-summary.png"
    subprocess.run(
        [
            sys.executable,
            "boundary_scanner.py",
            "fixtures/risky-package",
            "--chart",
            str(chart),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert chart.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_cli_creates_the_parent_directory_for_a_chart(tmp_path: Path) -> None:
    chart = tmp_path / "nested" / "risk-summary.png"
    subprocess.run(
        [sys.executable, "boundary_scanner.py", "fixtures/risky-package", "--chart", str(chart)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert chart.is_file()

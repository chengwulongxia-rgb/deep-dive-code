"""Run the actual, pinned KillSwitch interpreter in isolated Docker containers."""

import argparse
import json
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UPSTREAM_COMMIT = "44eabb04db0e114883da2a60e87d2d53b576b212"
IMAGE = "chengwu-killswitch:44eabb0"
CASES = ("print-seven.ks", "wrong-order.ks")


def run_command(name: str, filename: str) -> list[str]:
    return [
        "docker", "run", "--rm", "--name", name,
        "--network=none", "--read-only", "--user=65534:65534",
        "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=64", "--memory=256m", "--cpus=1",
        "--mount", f"type=bind,src={ROOT / 'examples'},dst=/examples,readonly",
        IMAGE, "run", f"/examples/{filename}",
    ]


def matches_expectation(filename: str, code: int, stdout: str, stderr: str) -> bool:
    if filename == "print-seven.ks":
        return code == 0 and stdout.strip() == "7" and not stderr.strip()
    if filename == "wrong-order.ks":
        return code == 1 and "Need value on stack for `visibly`" in stdout + stderr
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true", help="Use the existing pinned interpreter image")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/results.json", help="Write actual subprocess outputs as JSON")
    args = parser.parse_args()
    if shutil.which("docker") is None:
        parser.exit(2, "Docker is required; no simulated interpreter fallback is used.\n")
    try:
        if not args.skip_build:
            subprocess.run(["docker", "build", "-t", IMAGE, str(ROOT)], check=True, timeout=900)
        image_id = subprocess.run(
            ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"],
            capture_output=True, text=True, check=True, timeout=15,
        ).stdout.strip()
        results = []
        for filename in CASES:
            name = "killswitch-demo-" + uuid.uuid4().hex[:12]
            finished = False
            try:
                process = subprocess.run(
                    run_command(name, filename), capture_output=True,
                    text=True, check=False, timeout=30,
                )
                finished = True
            finally:
                if not finished:
                    try:
                        cleanup = subprocess.run(
                            ["docker", "rm", "-f", name], capture_output=True,
                            text=True, check=False, timeout=15,
                        )
                        if cleanup.returncode != 0:
                            print(f"Container cleanup failed for {name}: {cleanup.stderr}", file=sys.stderr)
                    except (OSError, subprocess.SubprocessError) as cleanup_error:
                        print(f"Container cleanup failed for {name}: {cleanup_error}", file=sys.stderr)
            if process.returncode in (125, 126, 127):
                raise RuntimeError(f"Docker could not launch {filename}: {process.stderr or process.stdout}")
            matched = matches_expectation(filename, process.returncode, process.stdout, process.stderr)
            results.append({
                "file": filename, "exit_code": process.returncode,
                "stdout": process.stdout, "stderr": process.stderr,
                "expectation_met": matched,
            })
            print(f"{'PASS' if matched else 'FAIL'} {filename}: exit={process.returncode}")
            print((process.stdout + process.stderr).rstrip())
        report = {
            "upstream_commit": UPSTREAM_COMMIT,
            "image_id": image_id,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "scope": "Two interpreter cases, not an LLM evaluation or full KillSwitch-Bench reproduction",
            "results": results,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        passed = sum(item["expectation_met"] for item in results)
        print(f"{passed}/{len(results)} expectations met. Actual outputs: {args.output}")
        return 0 if passed == len(results) else 1
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Execution failed (not a language result): {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

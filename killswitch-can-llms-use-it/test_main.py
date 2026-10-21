import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent


class CliTests(unittest.TestCase):
    def test_help_describes_real_interpreter_reproduction(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "main.py"), "--help"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--skip-build", result.stdout)


class ResultTests(unittest.TestCase):
    def test_success_requires_zero_exit_and_exact_seven(self):
        import main
        self.assertTrue(main.matches_expectation("print-seven.ks", 0, "7", ""))
        self.assertFalse(main.matches_expectation("print-seven.ks", 1, "7", ""))
        self.assertFalse(main.matches_expectation("print-seven.ks", 0, "8", ""))

    def test_wrong_order_requires_specific_stack_error_not_just_any_failure(self):
        import main
        self.assertTrue(main.matches_expectation("wrong-order.ks", 1, "Error: Need value on stack for `visibly`\n", ""))
        self.assertFalse(main.matches_expectation("wrong-order.ks", 125, "", "Docker daemon unavailable"))
        self.assertFalse(main.matches_expectation("wrong-order.ks", 0, "Need value on stack for visibly", ""))

    def test_runtime_is_networkless_readonly_and_nonprivileged(self):
        import main
        command = main.run_command("test-killswitch", "print-seven.ks")
        for flag in ["--read-only", "--network=none", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user=65534:65534"]:
            self.assertIn(flag, command)
        self.assertIn("--pids-limit=64", command)
        self.assertTrue(any("dst=/examples,readonly" in part for part in command))
        self.assertNotIn("--privileged", command)
        self.assertEqual(command[-2:], ["run", "/examples/print-seven.ks"])


class RuntimeFailureTests(unittest.TestCase):
    def test_docker_startup_error_is_not_a_language_result(self):
        import main
        inspect = subprocess.CompletedProcess([], 0, stdout="sha256:test\n", stderr="")
        failure = subprocess.CompletedProcess([], 125, stdout="", stderr="Docker daemon unavailable")
        with patch.object(sys, "argv", ["main.py", "--skip-build"]), patch.object(main.shutil, "which", return_value="docker"), patch.object(main.subprocess, "run", side_effect=[inspect, failure, failure]):
            self.assertEqual(main.main(), 2)

    def test_keyboard_interrupt_removes_named_container(self):
        import main
        inspect = subprocess.CompletedProcess([], 0, stdout="sha256:test\n", stderr="")
        cleaned = subprocess.CompletedProcess([], 0, stdout="removed", stderr="")
        with patch.object(sys, "argv", ["main.py", "--skip-build"]), patch.object(main.shutil, "which", return_value="docker"), patch.object(main.subprocess, "run", side_effect=[inspect, KeyboardInterrupt(), cleaned]) as run:
            with self.assertRaises(KeyboardInterrupt):
                main.main()
            cleanup = run.call_args_list[-1].args[0]
            self.assertEqual(cleanup[:3], ["docker", "rm", "-f"])
            self.assertTrue(cleanup[3].startswith("killswitch-demo-"))


if __name__ == "__main__":
    unittest.main()

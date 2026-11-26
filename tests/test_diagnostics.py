"""
tests.test_diagnostics
======================
Cross-platform unit & subprocess integration tests for src.core.diagnostics.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.core.diagnostics import RateLimiter, _TeeTextStream, read_log_tail


class TestDiagnostics(unittest.TestCase):
    def test_rate_limiter_suppresses_and_counts(self):
        limiter = RateLimiter()
        allowed1, sup1 = limiter.check("k1", interval=0.15)
        self.assertTrue(allowed1)
        self.assertEqual(sup1, 0)

        allowed2, sup2 = limiter.check("k1", interval=0.15)
        self.assertFalse(allowed2)
        self.assertEqual(sup2, 1)

        allowed3, sup3 = limiter.check("k1", interval=0.15)
        self.assertFalse(allowed3)
        self.assertEqual(sup3, 2)

        time.sleep(0.18)
        allowed4, sup4 = limiter.check("k1", interval=0.15)
        self.assertTrue(allowed4)
        self.assertEqual(sup4, 2)

    def test_read_log_tail_missing_and_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.log"
            self.assertIn("file not found", read_log_tail(missing))

            sample = Path(tmp) / "sample.log"
            sample.write_text("\n".join(f"line-{i}" for i in range(50)) + "\n", encoding="utf-8")
            tail = read_log_tail(sample, max_lines=5)
            self.assertEqual(tail.splitlines(), ["line-45", "line-46", "line-47", "line-48", "line-49"])

    def test_tee_stream_captures_lines(self):
        import io
        orig = io.StringIO()
        log_buf = io.StringIO()
        tee = _TeeTextStream(orig, log_buf, threading.Lock(), "STDOUT")
        tee.write("hello ")
        tee.write("world\nnext line")
        tee.flush()
        self.assertEqual(orig.getvalue(), "hello world\nnext line")
        logged = log_buf.getvalue()
        self.assertIn("[STDOUT  ]", logged)
        self.assertIn("hello world", logged)
        self.assertIn("next line", logged)

    def test_primary_and_cli_session_logs_and_crash_capture(self):
        repo_root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            env["DESKTOPSUITE_LOG_DIR"] = tmp

            # 1. Primary session writes DesktopSuite_latest.log + history, captures stdout & uncaught thread + main exception
            primary_code = (
                f"import logging, sys, threading; sys.path.insert(0, {str(repo_root)!r})\n"
                "from src.core.diagnostics import init_diagnostics, log_environment_snapshot, log_win32_window_tree\n"
                "p = init_diagnostics('primary')\n"
                "logging.getLogger('Test').info('primary_started')\n"
                "logging.getLogger('Test').debug('debug_detail_captured')\n"
                "log_environment_snapshot()\n"
                "log_win32_window_tree('test_probe')\n"
                "t = threading.Thread(target=lambda: 1 / 0, name='bg-crash')\n"
                "t.start(); t.join()\n"
                "print('stdout_marker_line')\n"
                "raise RuntimeError('boom_for_test')\n"
            )
            res = subprocess.run(
                [sys.executable, "-c", primary_code],
                cwd=str(repo_root),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(res.returncode, 0)

            latest = Path(tmp) / "DesktopSuite_latest.log"
            self.assertTrue(
                latest.is_file(),
                f"DesktopSuite_latest.log should exist (stdout={res.stdout!r}, stderr={res.stderr!r})",
            )
            content = latest.read_text(encoding="utf-8")
            self.assertIn("primary_started", content)
            self.assertIn("debug_detail_captured", content)
            self.assertIn("System & Environment Snapshot", content)
            self.assertIn("Uncaught thread exception in 'bg-crash' (ZeroDivisionError)", content)
            self.assertIn("stdout_marker_line", content)
            self.assertIn("Uncaught main-thread exception (RuntimeError): boom_for_test", content)
            self.assertTrue(list((Path(tmp) / "history").glob("DesktopSuite_*.log")))

            # 2. Secondary/CLI launch must NOT truncate DesktopSuite_latest.log
            cli_code = (
                f"import logging, sys; sys.path.insert(0, {str(repo_root)!r})\n"
                "from src.core.diagnostics import init_diagnostics\n"
                "init_diagnostics('cli')\n"
                "logging.getLogger('CLI').info('cli_action_marker')\n"
            )
            res_cli = subprocess.run(
                [sys.executable, "-c", cli_code],
                cwd=str(repo_root),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res_cli.returncode, 0, msg=f"stderr={res_cli.stderr!r}")
            self.assertIn("primary_started", latest.read_text(encoding="utf-8"))
            cli_log = Path(tmp) / "DesktopSuite_cli.log"
            self.assertTrue(cli_log.is_file())
            self.assertIn("cli_action_marker", cli_log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

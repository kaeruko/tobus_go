import ctypes
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "explore_cms_publish_test_target",
    Path(__file__).resolve().parents[2] / "scripts" / "explore_cms.py",
)
cms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cms)


def _process_running(pid: int) -> bool:
    if os.name == "nt":
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x00100000, False, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # An orphaned child can briefly be a zombie after its parent is killed.
    stat_path = Path(f"/proc/{pid}/stat")
    if stat_path.exists():
        return stat_path.read_text().split(") ", 1)[1].split()[0] != "Z"
    return True


def _cleanup_process(pid: int) -> None:
    if not _process_running(pid):
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    else:
        import signal

        os.kill(pid, signal.SIGKILL)


class CmsPublishProcessTest(unittest.TestCase):
    def _write_publisher(self, root: Path, code: str) -> Path:
        publisher = root / "fake_publisher.py"
        publisher.write_text(code, encoding="utf-8")
        return publisher

    def test_progress_is_delivered_before_the_publisher_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            finished = root / "finished"
            publisher = self._write_publisher(
                root,
                "import json, sys, time\n"
                "from pathlib import Path\n"
                "assert '--progress-json' in sys.argv\n"
                "sys.stdout.reconfigure(encoding='utf-8')\n"
                "print('EXPLORE_PROGRESS ' + json.dumps({'stage': 'validate', "
                "'message': '検証中'}, ensure_ascii=False), flush=True)\n"
                "time.sleep(0.5)\n"
                f"Path({str(finished)!r}).write_text('finished')\n"
                "print('公開完了', flush=True)\n",
            )
            received = []

            def on_progress(event):
                if event.get("message") == "検証中":
                    received.append((dict(event), finished.exists()))

            with patch.object(cms, "PUBLISH_SCRIPT", publisher):
                result = cms.publish(on_progress, timeout=5)

            self.assertEqual(result.returncode, 0)
            self.assertEqual(len(received), 1)
            self.assertFalse(received[0][1], "progress was buffered until completion")
            self.assertEqual(received[0][0]["message"], "検証中")
            self.assertGreaterEqual(received[0][0]["elapsed_seconds"], 0)
            self.assertIn("公開完了", result.stdout)
            self.assertNotIn("EXPLORE_PROGRESS", result.stdout)
            self.assertEqual(result.stderr, "")

    def test_nonzero_exit_preserves_unicode_stdout_and_stderr(self):
        with tempfile.TemporaryDirectory() as directory:
            publisher = self._write_publisher(
                Path(directory),
                "import sys\n"
                "sys.stdout.reconfigure(encoding='utf-8')\n"
                "sys.stderr.reconfigure(encoding='utf-8')\n"
                "print('画像を検証しました', flush=True)\n"
                "print('認証エラー: 有効期限が切れています', file=sys.stderr, flush=True)\n"
                "sys.exit(7)\n",
            )
            with patch.object(cms, "PUBLISH_SCRIPT", publisher):
                result = cms.publish(timeout=5)
            self.assertEqual(result.returncode, 7)
            self.assertIn("画像を検証しました", result.stdout)
            self.assertIn("認証エラー: 有効期限が切れています", result.stdout)
            self.assertEqual(result.stderr, "")

    def test_silent_publisher_provides_heartbeat_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            publisher = self._write_publisher(
                Path(directory), "import time\ntime.sleep(1.3)\n"
            )
            received = []
            start = time.monotonic()
            with patch.object(cms, "PUBLISH_SCRIPT", publisher):
                result = cms.publish(
                    lambda event: received.append((time.monotonic(), dict(event))),
                    timeout=5,
                )
            end = time.monotonic()

            self.assertEqual(result.returncode, 0)
            self.assertTrue(received, "a silent publisher left the UI without progress")
            self.assertTrue(all("elapsed_seconds" in event for _, event in received))
            checkpoints = [start, *(stamp for stamp, _ in received), end]
            self.assertLess(
                max(right - left for left, right in zip(checkpoints, checkpoints[1:])),
                1.15,
                "heartbeat progress paused for more than one second",
            )

    def test_silent_timeout_is_bounded_and_ends_parent_and_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pid_file = root / "processes.json"
            publisher = self._write_publisher(
                root,
                "import json, os, subprocess, sys, time\n"
                "from pathlib import Path\n"
                "child = subprocess.Popen([sys.executable, '-c', "
                "'import time; time.sleep(60)'])\n"
                f"Path({str(pid_file)!r}).write_text(json.dumps([os.getpid(), child.pid]))\n"
                "time.sleep(60)\n",
            )
            start = time.monotonic()
            pids = []
            try:
                with patch.object(cms, "PUBLISH_SCRIPT", publisher):
                    with self.assertRaises(subprocess.TimeoutExpired) as raised:
                        cms.publish(timeout=0.8)
                self.assertLess(time.monotonic() - start, 4)
                self.assertTrue(pid_file.exists(), "fake publisher did not start before timeout")
                pids = json.loads(pid_file.read_text())
                self.assertEqual(raised.exception.output, "")
                deadline = time.monotonic() + 1
                while any(_process_running(pid) for pid in pids) and time.monotonic() < deadline:
                    time.sleep(0.025)
                self.assertFalse(
                    any(_process_running(pid) for pid in pids),
                    "a publishing subprocess survived the timeout",
                )
            finally:
                if not pids and pid_file.exists():
                    pids = json.loads(pid_file.read_text())
                for pid in reversed(pids):
                    _cleanup_process(pid)

    def test_continuous_ordinary_logs_do_not_suppress_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory:
            publisher = self._write_publisher(
                Path(directory),
                "import time\n"
                "for number in range(26):\n"
                "    print('diagnostic line', flush=True)\n"
                "    time.sleep(0.05)\n",
            )
            received = []
            start = time.monotonic()
            with patch.object(cms, "PUBLISH_SCRIPT", publisher):
                result = cms.publish(
                    lambda event: received.append(time.monotonic()), timeout=5
                )
            end = time.monotonic()

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.count("diagnostic line"), 26)
            checkpoints = [start, *received, end]
            self.assertLess(
                max(right - left for left, right in zip(checkpoints, checkpoints[1:])),
                1.15,
                "ordinary logs prevented heartbeat progress",
            )

    def test_timeout_preserves_output_for_diagnosis(self):
        with tempfile.TemporaryDirectory() as directory:
            publisher = self._write_publisher(
                Path(directory),
                "import sys, time\n"
                "sys.stdout.reconfigure(encoding='utf-8')\n"
                "print('S3への接続待ち', flush=True)\n"
                "time.sleep(60)\n",
            )
            with patch.object(cms, "PUBLISH_SCRIPT", publisher):
                with self.assertRaises(subprocess.TimeoutExpired) as raised:
                    cms.publish(timeout=0.8)
            self.assertIn("S3への接続待ち", raised.exception.output)


class CmsPublishUiTest(unittest.TestCase):
    def _run_publish(self, publisher):
        from streamlit.testing.v1 import AppTest

        with patch.dict(sys.modules, {"explore_cms_publish_test_target": cms}), patch.object(
            cms, "publish", side_effect=publisher
        ):
            app = AppTest.from_string(
                "import explore_cms_publish_test_target as cms\ncms.render_publish()"
            ).run()
            return app

    def test_success_shows_confirmation_and_captured_output(self):
        def publisher(on_progress=None, **kwargs):
            on_progress({"stage": "images", "current": 1, "total": 2, "skipped": 3, "elapsed_seconds": 5})
            return subprocess.CompletedProcess([], 0, "uploaded 3 images", "")

        app = self._run_publish(publisher)
        self.assertFalse(app.exception)
        self.assertTrue(any("公開しました" in message.value for message in app.success))
        self.assertTrue(any("uploaded 3 images" in code.value for code in app.code))

    def test_failure_shows_captured_error_without_raw_exception(self):
        def publisher(on_progress=None, **kwargs):
            return subprocess.CompletedProcess([], 7, "認証エラー", "")

        app = self._run_publish(publisher)
        self.assertFalse(app.exception)
        self.assertTrue(any("公開に失敗" in message.value for message in app.error))
        self.assertTrue(any("認証エラー" in code.value for code in app.code))

    def test_timeout_shows_actionable_error_without_raw_exception(self):
        def publisher(on_progress=None, **kwargs):
            raise subprocess.TimeoutExpired(["fake_publisher"], 900, output="S3への接続待ち")

        app = self._run_publish(publisher)
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertTrue(any("時間がかかりすぎた" in message.value for message in app.error))
        self.assertTrue(any("S3への接続待ち" in code.value for code in app.code))


if __name__ == "__main__":
    unittest.main()

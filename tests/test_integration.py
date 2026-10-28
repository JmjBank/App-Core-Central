"""End-to-end tests: real processes, real files, no network, no Oracle/Elasticsearch."""
import datetime
import os
import shutil
import subprocess
import sys
import unittest

from truecorp_core.logging import get_logger, setup_logging, shutdown_logging
from truecorp_core.logging.rotation import load_state, save_state
from tests.support import TempTestCase, read_gz, read_text

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(args, cwd=None, env=None):
    full_env = dict(os.environ)
    full_env.pop("PYTHONPATH", None)
    full_env.update(env or {})
    proc = subprocess.Popen([sys.executable] + args, cwd=cwd, env=full_env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    out, err = proc.communicate()
    return proc.returncode, out, err


class ExampleAppTests(TempTestCase):
    def test_cron_example_repeated_execution(self):
        log_path = self.path("logs", "cancel_5534.log")
        state_path = self.path("logs", ".logging_state", "cancel_5534.rotation.json")
        anchors = []
        for _ in range(3):
            code, out, err = run([os.path.join(REPO, "examples", "example_cron.py"), "--base-dir", self.tmp])
            self.assertEqual(code, 1, err)  # the example deliberately fails one tracking id
            anchors.append(load_state(state_path)[:2])
        text = read_text(log_path)
        self.assertEqual(text.count("Application started"), 3)
        self.assertEqual(text.count("Application finished"), 3)
        self.assertEqual(text.count("event=IOM_GET_FAILED"), 3)
        self.assertEqual(text.count("error_type=TimeoutError"), 3)
        self.assertIn("tracking_id=XYZ456", text)
        self.assertNotIn("not-for-the-log", text)  # password= inside the exception message was redacted
        self.assertEqual(len(set(anchors)), 1)  # restarts did not reset the rotation cycle
        self.assertEqual(os.listdir(self.path("logs", "archive")), [])
        self.assertIn("order failed", err)  # console (WARNING+) goes to stderr, as configured

    def test_daemon_example(self):
        code, out, err = run([os.path.join(REPO, "examples", "example_app.py"), "--base-dir", self.tmp,
                              "--iterations", "3", "--interval", "0"])
        self.assertEqual(code, 0, err)
        text = read_text(self.path("logs", "cancel_5534.log"))
        self.assertIn("Daemon started", text)
        self.assertIn("batch_id=B3", text)
        self.assertIn("Daemon stopped after 3 batches", text)

    def test_portable_deployment_layout_needs_only_pythonpath(self):
        """Simulates the FTP/SFTP layout: APP/lib/truecorp_core, run from an unrelated CWD, no install."""
        app = self.path("APP_CANCEL_5534")
        os.makedirs(os.path.join(app, "lib"))
        shutil.copytree(os.path.join(REPO, "truecorp_core"), os.path.join(app, "lib", "truecorp_core"))
        main = os.path.join(app, "main.py")
        with open(main, "w") as fh:
            fh.write("from truecorp_core.logging import setup_logging, get_logger, set_run_context\n"
                     "setup_logging({'directory': './logs', 'filename': 'x.log'})\n"  # base dir = script dir
                     "set_run_context('R1')\n"
                     "get_logger('APP').info('portable ok')\n")
        elsewhere = self.path("some_other_cwd")
        os.makedirs(elsewhere)
        code, out, err = run([main], cwd=elsewhere, env={"PYTHONPATH": os.path.join(app, "lib")})
        self.assertEqual(code, 0, err)
        self.assertIn("portable ok", read_text(os.path.join(app, "logs", "x.log")))
        self.assertEqual(os.listdir(elsewhere), [])  # nothing was written relative to the CWD

    def test_preflight_is_read_only_and_passes(self):
        logs = self.path("logs")
        os.makedirs(logs)
        before = sorted(os.listdir(self.tmp)), sorted(os.listdir(logs))
        code, out, err = run([os.path.join(REPO, "tools", "preflight.py"), "--lib", REPO, "--log-dir", logs])
        self.assertEqual(code, 0, out + err)
        self.assertIn("truecorp_core 0.1.0 importable", out)
        self.assertEqual((sorted(os.listdir(self.tmp)), sorted(os.listdir(logs))), before)
        code, out, _ = run([os.path.join(REPO, "tools", "preflight.py"), "--log-dir", self.path("missing")])
        self.assertEqual(code, 1)


class RestartAfterRotationTests(TempTestCase):
    CFG = {"directory": "logs", "filename": "job.log", "rotation": {"mode": "DAILY"}}

    def test_restart_after_rotation(self):
        setup_logging(self.CFG, base_dir=self.tmp)
        get_logger("JOB").info("first run")
        shutdown_logging()
        state = self.path("logs", ".logging_state", "job.rotation.json")
        anchor, start, _ = load_state(state)
        eight_days_ago = datetime.date.today() - datetime.timedelta(days=8)
        save_state(state, eight_days_ago, eight_days_ago)  # pretend the job last rotated 8 days ago

        setup_logging(self.CFG, base_dir=self.tmp)  # cron starts again: due, so rotate at startup
        get_logger("JOB").info("second run")
        shutdown_logging()
        archives = os.listdir(self.path("logs", "archive"))
        self.assertEqual(len(archives), 1)
        self.assertIn("first run", read_gz(self.path("logs", "archive", archives[0])))
        self.assertNotIn("first run", read_text(self.path("logs", "job.log")))

        setup_logging(self.CFG, base_dir=self.tmp)  # third start, same day: nothing more to rotate
        get_logger("JOB").info("third run")
        shutdown_logging()
        self.assertEqual(len(os.listdir(self.path("logs", "archive"))), 1)
        text = read_text(self.path("logs", "job.log"))
        self.assertIn("second run", text)
        self.assertIn("third run", text)


WRITER = """
import sys
from truecorp_core.logging import setup_logging, get_logger, set_run_context, shutdown_logging
base, worker, count = sys.argv[1], sys.argv[2], int(sys.argv[3])
setup_logging({"directory": "logs", "filename": "shared.log", "rotation": {"mode": "DAILY"}}, base_dir=base)
set_run_context("W" + worker)
log = get_logger("CONC")
for i in range(count):
    log.info("worker=%s seq=%d payload=%s", worker, i, "x" * 200)
shutdown_logging()
"""


class ConcurrencyTests(TempTestCase):
    def spawn(self, workers, count):
        script = self.path("writer.py")
        with open(script, "w") as fh:
            fh.write(WRITER)
        env = dict(os.environ, PYTHONPATH=REPO)
        procs = [subprocess.Popen([sys.executable, script, self.tmp, str(w), str(count)], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
                 for w in range(workers)]
        for proc in procs:
            _, err = proc.communicate()
            self.assertEqual(proc.returncode, 0, err)

    def all_text(self):
        logs = self.path("logs")
        text = read_text(os.path.join(logs, "shared.log"))
        for name in sorted(os.listdir(os.path.join(logs, "archive"))):
            text += read_gz(os.path.join(logs, "archive", name))
        return text

    def test_simultaneous_processes_append_without_loss_or_interleaving(self):
        self.spawn(workers=4, count=300)
        lines = read_text(self.path("logs", "shared.log")).splitlines()
        self.assertEqual(len(lines), 1200)
        for line in lines:  # every line is whole: no torn or interleaved writes
            self.assertRegex(line, r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \[INFO\] \[CONC\] \[W\d\] worker=\d seq=\d+ payload=x{200}$")

    def test_simultaneous_start_with_rotation_due_rotates_exactly_once(self):
        os.makedirs(self.path("logs", ".logging_state"))
        os.makedirs(self.path("logs", "archive"))
        with open(self.path("logs", "shared.log"), "w") as fh:
            fh.write("OLD LINE\n")
        old = datetime.date.today() - datetime.timedelta(days=3)
        save_state(self.path("logs", ".logging_state", "shared.rotation.json"), old, old)
        self.spawn(workers=4, count=25)
        archives = os.listdir(self.path("logs", "archive"))
        self.assertEqual(len(archives), 1, archives)  # one winner, no duplicate/empty archives
        text = self.all_text()
        self.assertEqual(text.count("OLD LINE"), 1)
        self.assertIn("OLD LINE", read_gz(self.path("logs", "archive", archives[0])))
        self.assertEqual(text.count("payload="), 100)  # all 4 x 25 records survived


if __name__ == "__main__":
    unittest.main()

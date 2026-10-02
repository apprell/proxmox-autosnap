import contextlib
import importlib.util
import io
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'proxmox-autosnap.py'


def load_module():
    spec = importlib.util.spec_from_file_location('autosnap', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunningTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.module = load_module()
        self.module.__file__ = str(Path(self.directory.name) / SCRIPT.name)
        self.lock = Path(self.directory.name) / f'{self.module.NODE_NAME}.running.pid'

    def test_existing_pid_is_informational(self):
        for content in ('999999999', str(os.getpid()), '', 'invalid PID'):
            with self.subTest(content=content):
                self.lock.write_text(content)
                inode = self.lock.stat().st_ino
                result = self.module.running(lambda value: value)(42)
                self.assertEqual(result, 42)
                self.assertEqual(self.lock.read_text(), str(os.getpid()))
                self.assertEqual(self.lock.stat().st_ino, inode)

    def test_exception_releases_lock(self):
        for exception in (RuntimeError('failed'), SystemExit(2)):
            with self.subTest(exception=exception):
                def fail():
                    raise exception

                with self.assertRaises(type(exception)):
                    self.module.running(fail)()
                self.assertTrue(self.lock.exists())
                self.assertEqual(self.module.running(lambda: 'ok')(), 'ok')

    def test_active_lock_blocks_and_killed_owner_releases_lock(self):
        code = '''
import importlib.util
import sys
spec = importlib.util.spec_from_file_location('autosnap', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.__file__ = sys.argv[2]
@module.running
def hold():
    print('ready', flush=True)
    sys.stdin.read()
hold()
'''
        owner = subprocess.Popen(
            [sys.executable, '-B', '-c', code, str(SCRIPT), self.module.__file__],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        try:
            deadline = time.monotonic() + 5
            readiness = b''
            while b'\n' not in readiness:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([owner.stdout], [], [], remaining)[0]:
                    self.fail('Child process did not signal readiness within 5 seconds')
                chunk = os.read(owner.stdout.fileno(), 1024)
                if not chunk:
                    self.fail('Child process exited before signaling readiness')
                readiness += chunk
            self.assertEqual(readiness.strip(), b'ready')
            content = self.lock.read_text()
            self.assertEqual(content, str(owner.pid))
            entered = []
            output = io.StringIO()
            with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as error:
                self.module.running(lambda: entered.append(True))()
            self.assertEqual(error.exception.code, 1)
            self.assertEqual(entered, [])
            self.assertEqual(
                output.getvalue(),
                f'Script already running under PID {owner.pid}, skipping execution.\n',
            )
            self.assertEqual(self.lock.read_text(), content)
            # Even an unreadable PID value cannot bypass an active kernel lock.
            self.lock.write_text('invalid PID')
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                self.module.running(lambda: entered.append(True))()
            self.assertEqual(entered, [])
            owner.kill()
            owner.wait(timeout=5)
            self.assertTrue(self.lock.exists())
            self.assertEqual(self.module.running(lambda: 'ok')(), 'ok')
        finally:
            if owner.poll() is None:
                owner.kill()
            owner.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()

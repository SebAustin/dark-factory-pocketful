import hashlib
import threading
import time
import unittest
from unittest import mock

from app import passwords


class Recorder:
    """Stands in for hashlib.scrypt and records how many calls overlap."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = 0
        self.peak = 0
        self.real = hashlib.scrypt

    def __call__(self, *args, **kwargs):
        with self.lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
        time.sleep(0.01)
        try:
            return self.real(*args, **kwargs)
        finally:
            with self.lock:
                self.running -= 1


def run_threads(fn, count=20):
    errors = []

    def go():
        try:
            fn()
        except Exception as exc:  # pragma: no cover - reported by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(count)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, errors


class HashConcurrencyTest(unittest.TestCase):
    def setUp(self):
        self.stored = passwords.hash_password("correct horse", n=2 ** 11)

    def test_verify_runs_one_hash_at_a_time(self):
        rec = Recorder()
        with mock.patch.object(passwords.hashlib, "scrypt", rec):
            run_threads(lambda: self.assertTrue(passwords.verify_password("correct horse", self.stored)))
        self.assertEqual(rec.peak, 1)

    def test_signup_hash_runs_one_at_a_time(self):
        rec = Recorder()
        with mock.patch.object(passwords.hashlib, "scrypt", rec):
            run_threads(lambda: passwords.hash_password("password1", n=2 ** 11))
        self.assertEqual(rec.peak, 1)

    def test_verify_and_hash_share_the_one_slot(self):
        rec = Recorder()
        with mock.patch.object(passwords.hashlib, "scrypt", rec):
            run_threads(lambda: passwords.verify_password("x", self.stored), 10)
            run_threads(lambda: passwords.hash_password("x", n=2 ** 11), 10)
        self.assertEqual(rec.peak, 1)

    def test_bulk_hashing_for_reset_is_not_serialised(self):
        rec = Recorder()
        with mock.patch.object(passwords.hashlib, "scrypt", rec):
            passwords.hash_many(["pw-%d" % i for i in range(16)])
        self.assertGreater(rec.peak, 1)

    def test_slot_is_released_after_a_failed_verify(self):
        for bad in ("", "scrypt$x", "scrypt$a$b$c$d$e", "scrypt$2048$8$1$zz$00"):
            self.assertFalse(passwords.verify_password("x", bad))
        self.assertTrue(passwords._HASH_SLOT.acquire(timeout=1))
        passwords._HASH_SLOT.release()

    def test_format_and_results_unchanged(self):
        stored = passwords.hash_password("correct horse")
        parts = stored.split("$")
        self.assertEqual(parts[:4], ["scrypt", str(passwords.N), "8", "1"])
        self.assertEqual(passwords.N, 2 ** 13)
        self.assertLessEqual(passwords.SEED_N, passwords.N)
        self.assertTrue(passwords.verify_password("correct horse", stored))
        self.assertFalse(passwords.verify_password("wrong horse", stored))
        self.assertTrue(passwords.verify_password("correct horse", self.stored))  # lighter seeded cost


if __name__ == "__main__":
    unittest.main()

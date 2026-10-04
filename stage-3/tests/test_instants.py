"""S3.1: exact instant keys and the monotonic server clock (plan S3-D1)."""
import unittest
from decimal import Decimal

from harness import port  # noqa: F401  (puts the app on sys.path)

from app import instants


class KeyTest(unittest.TestCase):
    def test_offsets_compare_by_instant(self):
        k = instants.key
        self.assertEqual(k("2026-09-24T19:00:00+02:00"), k("2026-09-24T17:00:00Z"))
        self.assertEqual(k("2026-09-24T17:00:00z"), k("2026-09-24t17:00:00+00:00"))
        self.assertEqual(k("2026-09-24T12:00:00-05:00"), k("2026-09-24T17:00:00+00:00"))
        self.assertLess(k("2026-09-24T18:59:59.999999999+02:00"), k("2026-09-24T17:00:00Z"))

    def test_fractions_are_exact(self):
        k = instants.key
        self.assertEqual(k("2026-09-24T17:00:00.5Z"), k("2026-09-24T17:00:00.500000000Z"))
        self.assertLess(k("2026-09-24T17:00:00.1234567891Z"), k("2026-09-24T17:00:00.1234567892Z"))
        self.assertEqual(k("1970-01-01T00:00:01.25Z"), Decimal("1.25"))
        self.assertEqual(k("1969-12-31T23:59:59Z"), Decimal(-1))

    def test_invalid_is_none(self):
        for bad in ("2026-09-24T17:00:00", "2026-09-24", "", None, 5, "2026-02-30T00:00:00Z",
                    "2026-09-24T24:00:00Z", "2026-09-24T23:59:60Z", "2026-09-24 17:00:00Z",
                    "2026-09-24T17:00:00+24:00", "2026-09-24T17:00:00." + "1" * 41 + "Z",
                    "2026-09-24T17:00:00Z\n", "0000-01-01T00:00:00Z"):
            self.assertIsNone(instants.key(bad), bad)

    def test_extremes(self):
        self.assertIsNotNone(instants.key("9999-12-31T23:59:59-23:59"))
        self.assertIsNotNone(instants.key("0001-01-01T00:00:00+23:59"))


class ClockTest(unittest.TestCase):
    def test_ticks_strictly_increase_even_with_a_frozen_wall_clock(self):
        c = instants.Clock()
        ticks = [c.tick(1_790_000_000.0) for _ in range(5)]
        keys = [instants.key(t) for t in ticks]
        self.assertEqual(keys, sorted(set(keys)))
        self.assertRegex(ticks[0], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}\+00:00$")

    def test_advance_past(self):
        c = instants.Clock()
        c.advance_past(instants.key("2999-01-01T00:00:00Z"))
        self.assertGreater(instants.key(c.tick(0.0)), instants.key("2999-01-01T00:00:00Z"))


if __name__ == "__main__":
    unittest.main()

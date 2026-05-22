"""Unit tests for server.validate_score_body and server.min_score_for_lines.

Run from repo root: `python3 -m unittest tests.test_validate`
or single file: `python3 tests/test_validate.py`.
"""

import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server import validate_score_body, min_score_for_lines, LINE_POINTS  # noqa: E402


def make_body(**overrides):
    """A valid baseline body. Tests override individual fields to fail one check at a time."""
    pid = "12345678-1234-4abc-8def-1234567890ab"
    base = {
        "playerId": pid,
        "displayName": "anon-" + pid[:4],
        # 5 single clears at L=1: 5*40 = 200.
        # level == 5//10 + 1 = 1.
        "score": 200,
        "lines": 5,
        "level": 1,
        "durationMs": 5000,
        "seed": 12345,
        "replayLog": "[]",
    }
    base.update(overrides)
    return base


class MinScoreForLinesTest(unittest.TestCase):

    def test_zero_lines(self):
        self.assertEqual(min_score_for_lines(0), 0)

    def test_one_line(self):
        # 1 line, 0 full levels, remainder=1 at level 1: 40 * 1 * 1 = 40.
        self.assertEqual(min_score_for_lines(1), 40)

    def test_ten_lines(self):
        # 10 lines = 1 full level, all at L=1 (level update happens at line 10).
        # game.js does level = lines//10 + 1, so lines 1..10 are all at L=1.
        # min = 40 * 10 * 1 * 2 / 2 + 40 * 2 * 0 = 400.
        self.assertEqual(min_score_for_lines(10), 400)

    def test_canonical_attack_lines(self):
        # 8000 lines, 800 full levels, remainder 0.
        # min = 40 * 10 * 800 * 801 / 2 = 128_160_000.
        # The canonical 9.5M attack claims this many lines for only 9.5M.
        self.assertEqual(min_score_for_lines(8000), 128_160_000)

    def test_monotonic(self):
        prev = -1
        for n in range(0, 200):
            cur = min_score_for_lines(n)
            self.assertGreaterEqual(cur, prev)
            prev = cur


class ValidateScoreBodyHappyPathTest(unittest.TestCase):

    def test_baseline_valid(self):
        ok, err = validate_score_body(make_body())
        self.assertTrue(ok, err)
        self.assertIsNone(err)

    def test_zero_lines_zero_score(self):
        # Brand-new top-out without clearing any lines.
        ok, err = validate_score_body(make_body(score=0, lines=0, level=1))
        self.assertTrue(ok, err)

    def test_high_legitimate_run(self):
        # 100 lines at L=11, with mostly Tetrises. score ~= 1200 * sum_of_levels.
        # For 100 lines / 25 Tetrises with level rising 1..10 (10 lines/level):
        # cheapest: 100 singles = sum_{L=1..10}(40*10*L) = 22_000.
        # Tetris-y realistic: aim for something in (22k, 1.2M).
        # Pick 500_000 (plausibly achievable).
        ok, err = validate_score_body(
            make_body(score=500_000, lines=100, level=11, durationMs=600_000)
        )
        self.assertTrue(ok, err)


class ValidateScoreBodyMalformedTest(unittest.TestCase):

    def test_not_dict(self):
        ok, err = validate_score_body([1, 2, 3])
        self.assertFalse(ok)

    def test_missing_key(self):
        b = make_body()
        del b["seed"]
        ok, err = validate_score_body(b)
        self.assertFalse(ok)

    def test_extra_key(self):
        ok, err = validate_score_body(make_body(evil=True))
        self.assertFalse(ok)

    def test_bad_uuid(self):
        ok, err = validate_score_body(make_body(playerId="not-a-uuid"))
        self.assertFalse(ok)

    def test_uuid_v1_rejected(self):
        # uuid.uuid1() leaks MAC+time and isn't v4.
        v1 = str(uuid.uuid1())
        ok, err = validate_score_body(make_body(playerId=v1, displayName="anon-" + v1[:4]))
        self.assertFalse(ok)

    def test_display_name_mismatch(self):
        ok, err = validate_score_body(make_body(displayName="anon-ffff"))
        self.assertFalse(ok)

    def test_bool_as_int_rejected(self):
        # In Python, isinstance(True, int) is True. We must reject booleans.
        ok, err = validate_score_body(make_body(score=True))
        self.assertFalse(ok)

    def test_replay_log_not_string(self):
        ok, err = validate_score_body(make_body(replayLog=123))
        self.assertFalse(ok)

    def test_replay_log_too_large(self):
        ok, err = validate_score_body(make_body(replayLog="x" * 100_000))
        self.assertFalse(ok)


class ValidateScoreBodyBoundsTest(unittest.TestCase):

    def test_score_too_high(self):
        ok, err = validate_score_body(make_body(score=10_000_001))
        self.assertFalse(ok)

    def test_score_negative(self):
        ok, err = validate_score_body(make_body(score=-1))
        self.assertFalse(ok)

    def test_seed_too_high(self):
        ok, err = validate_score_body(make_body(seed=2**32))
        self.assertFalse(ok)

    def test_duration_too_short(self):
        ok, err = validate_score_body(make_body(durationMs=999))
        self.assertFalse(ok)


class ValidateScoreBodyInvariantsTest(unittest.TestCase):

    def test_level_lines_mismatch_low(self):
        # 50 lines should give level 6, not level 1.
        ok, err = validate_score_body(make_body(score=2000, lines=50, level=1, durationMs=60_000))
        self.assertFalse(ok)
        self.assertIn("level", err.lower())

    def test_level_lines_mismatch_high(self):
        # 5 lines is level 1; claiming level 99 is forged.
        ok, err = validate_score_body(make_body(level=99))
        self.assertFalse(ok)

    def test_score_below_min_kills_canonical_attack(self):
        # The whole reason this plan tier exists. 8000 lines at level 801
        # requires score >= 128_160_000. Claiming 9.5M is impossible.
        ok, err = validate_score_body(
            make_body(
                score=9_500_000,
                lines=8000,
                level=801,
                durationMs=8_000_000,
                # The plan's upper bounds also need to pass; pick a valid baseline.
                # Actually 9.5M will fail the LOWER bound (min_score = 128M).
            )
        )
        self.assertFalse(ok)
        # The exact message should mention the lower bound — score too small for lines.
        self.assertIn("minimum", err.lower())

    def test_score_with_no_lines_capped(self):
        # No lines cleared but score > drop bonus ceiling is impossible.
        ok, err = validate_score_body(
            make_body(score=10_000, lines=0, level=1, durationMs=5000)
        )
        self.assertFalse(ok)

    def test_too_many_lines_for_duration(self):
        # 1000 lines in 1 second is impossible (MAX_LINES_PER_SEC = 6).
        # 1000 lines = level 101, min_score = 40*10*100*101/2 = 2_020_000.
        # Need to be careful to fail on rate, not other bounds.
        # 5s duration ⇒ 30 lines max. 1000 > 30.
        ok, err = validate_score_body(
            make_body(score=2_020_000, lines=1000, level=101, durationMs=5000)
        )
        self.assertFalse(ok)

    def test_score_above_upper_cross_field(self):
        # 5 lines at L=1: max = 1200*1*5 + drop_bonus_per_sec*5 = 6000 + 570 = 6570.
        # Claiming 10k+ trips the upper cross-field.
        ok, err = validate_score_body(
            make_body(score=50_000, lines=5, level=1, durationMs=5000)
        )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()

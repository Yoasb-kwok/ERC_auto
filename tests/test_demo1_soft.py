"""Boss demo1 soft gateway, coins, and the offscreen window. No car, no UDP."""

import os
import unittest
from io import StringIO
from contextlib import redirect_stdout

from ai.demo1_course import COIN_SPOTS, Demo1Course
from ai.demo1_window import Demo1Window, ensure_demo1_log_only
from ai.soft_gateway import SoftGateway, run_self_check
from ai.transport import send_car_command


class _Clock:
    def __init__(self, t=1_000.0):
        self.t = t

    def __call__(self):
        return self.t


class ScriptedRng:
    def __init__(self, values):
        self.values = list(values)

    def random(self):
        if not self.values:
            return 0.99
        return self.values.pop(0)


def recording_gateway(clock=None):
    sent = []

    def transmit(command_str, dry_run=None, debug=False):
        del dry_run, debug
        sent.append(str(command_str).strip())
        return command_str

    soft = SoftGateway(transmit=transmit, clock=clock or _Clock(), log=lambda _message: None)
    return soft, sent


class SoftGatewayTests(unittest.TestCase):
    def test_self_check_script(self):
        sent = run_self_check(log=lambda _message: None)
        self.assertIn("L:0,R:150,B:0,S:90", sent)
        self.assertIn("L:0,R:0,B:1,S:90", sent)
        self.assertEqual(sent[-1], "L:0,R:100,B:0,S:90")

    def test_boost_slow_freeze_steer_and_cap(self):
        soft, _sent = recording_gateway()
        self.assertTrue(soft.activate("boost"))
        self.assertEqual(soft.rewrite("L:0,R:100,B:0,S:90").strip(), "L:0,R:150,B:0,S:90")
        self.assertEqual(soft.rewrite("L:0,R:190,B:0,S:90").strip(), "L:0,R:255,B:0,S:90")
        self.assertEqual(soft.send(190, 90, 0).strip(), "L:0,R:255,B:0,S:90")
        self.assertEqual(soft.rewrite("L:80,R:0,B:0,S:90").strip(), "L:80,R:0,B:0,S:90")

        self.assertTrue(soft.activate("slow"))
        self.assertEqual(soft.rewrite("L:0,R:100,B:0,S:90").strip(), "L:0,R:40,B:0,S:90")
        self.assertEqual(soft.power, "slow")

        self.assertTrue(soft.activate("freeze"))
        self.assertEqual(soft.rewrite("L:40,R:100,B:0,S:50").strip(), "L:0,R:0,B:1,S:50")

        self.assertTrue(soft.activate("steer"))
        self.assertEqual(soft.rewrite("L:0,R:100,B:0,S:90").strip(), "L:0,R:100,B:0,S:120")
        self.assertTrue(soft.activate("steer", bias_sign=-1))
        self.assertEqual(soft.rewrite("L:0,R:100,B:0,S:90").strip(), "L:0,R:100,B:0,S:60")
        self.assertEqual(soft.rewrite("L:0,R:0,B:0,S:170").strip(), "L:0,R:0,B:0,S:140")
        soft.steer_sign = 1
        self.assertEqual(soft.rewrite("L:0,R:0,B:0,S:170").strip(), "L:0,R:0,B:0,S:180")

    def test_refresh_extends_and_then_expires(self):
        clock = _Clock()
        soft, _sent = recording_gateway(clock)
        self.assertTrue(soft.activate("boost"))
        self.assertAlmostEqual(soft.expires_at, 1_002.0)
        clock.t = 1_001.5
        self.assertTrue(soft.activate("boost"))
        self.assertAlmostEqual(soft.expires_at, 1_003.5)
        clock.t = 1_003.4
        self.assertEqual(soft.rewrite("L:0,R:100,B:0,S:90").strip(), "L:0,R:150,B:0,S:90")
        clock.t = 1_003.5
        self.assertEqual(soft.rewrite("L:0,R:100,B:0,S:90").strip(), "L:0,R:100,B:0,S:90")
        self.assertIsNone(soft.power)

    def test_human_brake_is_not_boosted_into_motion(self):
        soft, _sent = recording_gateway()
        soft.activate("boost")
        self.assertEqual(soft.rewrite("L:0,R:0,B:1,S:90").strip(), "L:0,R:0,B:1,S:90")

    def test_estop_blocks_powerups_and_clear_does_not_restore(self):
        clock = _Clock(2_000.0)
        soft, sent = recording_gateway(clock)
        soft.activate("boost")
        self.assertEqual(soft.send(100, 90, 0).strip(), "L:0,R:150,B:0,S:90")
        self.assertEqual(soft.emergency_stop().strip(), "L:0,R:0,B:1,S:90")
        self.assertIsNone(soft.power)
        self.assertFalse(soft.activate("slow"))
        self.assertFalse(soft.activate("freeze"))
        self.assertFalse(soft.activate("steer"))
        self.assertEqual(soft.send(100, 90, 0).strip(), "L:0,R:0,B:1,S:90")
        self.assertTrue(soft.clear_estop())
        self.assertIsNone(soft.power)
        self.assertFalse(soft.estop_latched)
        self.assertEqual(soft.send(100, 90, 0).strip(), "L:0,R:100,B:0,S:90")
        self.assertNotIn("L:0,R:150,B:0,S:90", sent[sent.index("L:0,R:0,B:1,S:90"):])

    def test_send_car_command_log_only_still_prints(self):
        previous = os.environ.get("ERC_LOG_ONLY")
        os.environ["ERC_LOG_ONLY"] = "1"
        try:
            buffer = StringIO()
            with redirect_stdout(buffer):
                line = send_car_command(100, 90, 0)
            self.assertEqual(line, "L:0,R:100,B:0,S:90\n")
            self.assertIn("[log-only] L:0,R:100,B:0,S:90", buffer.getvalue())
        finally:
            if previous is None:
                os.environ.pop("ERC_LOG_ONLY", None)
            else:
                os.environ["ERC_LOG_ONLY"] = previous


class CourseTests(unittest.TestCase):
    def test_five_coins_score_and_respawn(self):
        clock = _Clock(10.0)
        course = Demo1Course(clock=clock, rng=ScriptedRng([0.9] * 6))
        soft, _sent = recording_gateway(clock)
        self.assertEqual(len(COIN_SPOTS), 5)
        self.assertEqual(course.remaining(), 5)
        for expected in range(1, 6):
            self.assertTrue(course.simulate_detect("coin", soft=soft))
            self.assertEqual(course.score, expected)
            self.assertEqual(course.remaining(), 5 - expected)
        self.assertFalse(course.simulate_detect("coin", soft=soft))
        self.assertEqual(course.score, 5)
        self.assertFalse(course.simulate_detect("mushroom"))
        clock.t = 13.0
        course.step(0.0, set(), soft)
        self.assertEqual(course.remaining(), 5)
        self.assertEqual(course.score, 5)

    def test_coin_boost_is_thirty_percent_and_estop_blocks_it(self):
        clock = _Clock()
        soft, _sent = recording_gateway(clock)
        lucky = Demo1Course(clock=clock, rng=ScriptedRng([0.0]))
        self.assertTrue(lucky.simulate_detect("coin", soft=soft))
        self.assertTrue(lucky.last_pickup_boost)
        self.assertEqual(soft.power, "boost")

        soft.emergency_stop()
        blocked = Demo1Course(clock=clock, rng=ScriptedRng([0.0]))
        self.assertTrue(blocked.simulate_detect("coin", soft=soft))
        self.assertEqual(blocked.score, 1)
        self.assertFalse(blocked.last_pickup_boost)
        self.assertIsNone(soft.power)

        plain = Demo1Course(clock=clock, rng=ScriptedRng([0.30]))
        soft.clear_estop()
        self.assertTrue(plain.simulate_detect("coin", soft=soft))
        self.assertFalse(plain.last_pickup_boost)
        self.assertIsNone(soft.power)

    def test_click_and_drive_over_collect_once(self):
        clock = _Clock()
        course = Demo1Course(clock=clock, rng=ScriptedRng([0.9, 0.9]))
        soft, _sent = recording_gateway(clock)
        coin = course.coins[0]
        self.assertFalse(course.collect_at(0, 0, soft))
        self.assertTrue(course.collect_at(coin.x, coin.y, soft))
        self.assertEqual(course.score, 1)
        self.assertFalse(coin.alive)

        other = next(item for item in course.coins if item.alive)
        course.car_x, course.car_y = other.x, other.y
        course.step(0.0, set(), soft)
        self.assertEqual(course.score, 2)
        course.step(0.0, set(), soft)
        self.assertEqual(course.score, 2)

    def test_oil_zone_applies_slow_once_per_entry(self):
        clock = _Clock(50.0)
        course = Demo1Course(clock=clock, rng=ScriptedRng([0.9]))
        soft, _sent = recording_gateway(clock)
        course.car_x, course.car_y = 250 + 10, 150 + 10
        course.step(0.0, set(), soft)
        self.assertEqual(soft.power, "slow")
        expires = soft.expires_at
        clock.t = 50.4
        course.step(0.0, set(), soft)
        self.assertEqual(soft.expires_at, expires)
        course.car_x, course.car_y = 40, 40
        course.step(0.0, set(), soft)
        course.car_x, course.car_y = 250 + 10, 150 + 10
        course.step(0.0, set(), soft)
        self.assertGreater(soft.expires_at, expires)

    def test_boost_outruns_slow_and_freeze_holds_the_sprite(self):
        clock = _Clock()
        soft, _sent = recording_gateway(clock)
        boost = Demo1Course(clock=clock)
        soft.activate("boost")
        boost.step(1.0, {"up"}, soft)
        slow = Demo1Course(clock=clock)
        soft.activate("slow")
        slow.step(1.0, {"up"}, soft)
        frozen = Demo1Course(clock=clock)
        soft.activate("freeze")
        start = (frozen.car_x, frozen.car_y, frozen.heading)
        frozen.step(1.0, {"up", "left"}, soft)
        self.assertEqual((frozen.car_x, frozen.car_y, frozen.heading), start)
        self.assertLess(boost.car_y, slow.car_y)

    def test_estop_holds_the_sprite(self):
        clock = _Clock()
        course = Demo1Course(clock=clock)
        soft, _sent = recording_gateway(clock)
        soft.emergency_stop()
        start = (course.car_x, course.car_y)
        course.step(1.0, {"up"}, soft)
        self.assertEqual((course.car_x, course.car_y), start)


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["ERC_LOG_ONLY"] = "1"
        try:
            from PyQt5.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PyQt5 is not installed")
        try:
            cls.app = QApplication.instance() or QApplication([])
        except Exception as exc:
            raise unittest.SkipTest(f"Qt offscreen unavailable: {exc}") from exc

    def setUp(self):
        self.window = Demo1Window()

    def tearDown(self):
        self.window.close()

    def test_hud_fields_and_default_log_only(self):
        window = self.window
        self.assertTrue(window.log_only_box.isChecked())
        self.assertEqual(window.score_label.text(), "Score: 0")
        self.assertEqual(window.coins_label.text(), "Remaining coins: 5")
        self.assertEqual(window.power_label.text(), "Power-up: none")
        self.assertEqual(window.estop_label.text(), "E-stop: clear")
        self.assertEqual(window.course.remaining(), 5)

    def test_space_click_and_simulate_detect_increase_score(self):
        from PyQt5.QtCore import Qt

        window = self.window
        self.assertTrue(window.handle_key(Qt.Key_Space))
        self.assertEqual(window.course.score, 1)
        self.assertEqual(window.course.remaining(), 4)
        self.assertEqual(window.score_label.text(), "Score: 1")
        self.assertEqual(window.coins_label.text(), "Remaining coins: 4")
        self.assertTrue(window.simulate_detect("coin"))
        self.assertEqual(window.course.score, 2)
        coin = next(item for item in window.course.coins if item.alive)
        window._on_map_click(coin.x, coin.y)
        self.assertEqual(window.course.score, 3)
        self.assertEqual(window.coins_label.text(), "Remaining coins: 2")

    def test_keys_1_to_4_change_logged_datagrams(self):
        from PyQt5.QtCore import Qt

        window = self.window
        window.held.add("up")
        self.assertTrue(window.handle_key(Qt.Key_1))
        self.assertEqual(window.soft.last_command, "L:0,R:150,B:0,S:90")
        self.assertIn("Boost", window.power_label.text())
        self.assertIn("L:0,R:150,B:0,S:90", window.log.toPlainText())

        self.assertTrue(window.handle_key(Qt.Key_2))
        self.assertEqual(window.soft.last_command, "L:0,R:40,B:0,S:90")
        self.assertIn("Slow", window.power_label.text())

        self.assertTrue(window.handle_key(Qt.Key_3))
        self.assertEqual(window.soft.last_command, "L:0,R:0,B:1,S:90")
        self.assertIn("Freeze", window.power_label.text())

        self.assertTrue(window.handle_key(Qt.Key_4))
        self.assertEqual(window.soft.last_command, "L:0,R:100,B:0,S:120")
        self.assertIn("Steer +30", window.power_label.text())
        self.assertIn("L:0,R:100,B:0,S:120", window.log.toPlainText())

    def test_estop_blocks_powerups_on_the_window(self):
        from PyQt5.QtCore import Qt

        window = self.window
        window.held.add("up")
        window.handle_key(Qt.Key_1)
        self.assertEqual(window.soft.last_command, "L:0,R:150,B:0,S:90")
        window.emergency_stop()
        self.assertTrue(window.soft.estop_latched)
        self.assertEqual(window.estop_label.text(), "E-stop: latched")
        self.assertEqual(window.power_label.text(), "Power-up: none")
        self.assertFalse(window.activate_power("boost"))
        window.handle_key(Qt.Key_2)
        window._emit_motion()
        self.assertEqual(window.soft.last_command, "L:0,R:0,B:1,S:90")
        self.assertIsNone(window.soft.power)
        window.clear_estop()
        self.assertEqual(window.estop_label.text(), "E-stop: clear")
        window._emit_motion()
        self.assertEqual(window.soft.last_command, "L:0,R:100,B:0,S:90")
        self.assertEqual(window.power_label.text(), "Power-up: none")

    def test_qtest_space_and_boost_key(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest

        window = self.window
        window.show()
        self.app.processEvents()
        QTest.keyClick(window, Qt.Key_Space)
        self.app.processEvents()
        self.assertEqual(window.course.score, 1)
        self.assertEqual(window.score_label.text(), "Score: 1")
        window.held.add("up")
        QTest.keyClick(window, Qt.Key_1)
        self.app.processEvents()
        self.assertEqual(window.soft.last_command, "L:0,R:150,B:0,S:90")
        self.assertIn("Boost", window.power_label.text())


class EnvTests(unittest.TestCase):
    def test_unset_log_only_defaults_on_and_explicit_zero_stays(self):
        previous = os.environ.get("ERC_LOG_ONLY")
        try:
            os.environ.pop("ERC_LOG_ONLY", None)
            self.assertTrue(ensure_demo1_log_only())
            self.assertEqual(os.environ["ERC_LOG_ONLY"], "1")
            os.environ["ERC_LOG_ONLY"] = "0"
            self.assertFalse(ensure_demo1_log_only())
            self.assertEqual(os.environ["ERC_LOG_ONLY"], "0")
        finally:
            if previous is None:
                os.environ.pop("ERC_LOG_ONLY", None)
            else:
                os.environ["ERC_LOG_ONLY"] = previous


if __name__ == "__main__":
    unittest.main()

"""Virtual map for Boss demo1: five coins, an oil patch, a score.

No camera. ``simulate_detect("coin")``, the Space key, a click, and driving
onto a coin all call the same pickup. A pickup scores +1 and, 30% of the
time, asks the soft gateway for Boost. The full set of coins returns
``RESPAWN_S`` after the map is cleared.
"""

from __future__ import annotations

import math
import random

from ai.soft_gateway import SoftGateway

MAP_W = 640
MAP_H = 400
CAR_START = (78.0, 330.0)
CAR_RADIUS = 16.0
COIN_RADIUS = 16.0
PICKUP_RADIUS = 30.0
FORWARD_PX_S = 170.0
TURN_DEG_S = 150.0
STEER_DRIFT_DEG_S = 45.0
RESPAWN_S = 3.0
BOOST_CHANCE = 0.30
OIL_RECT = (250.0, 150.0, 140.0, 90.0)  # x, y, w, h
COIN_SPOTS = (
    (150.0, 78.0),
    (330.0, 64.0),
    (540.0, 100.0),
    (210.0, 250.0),
    (500.0, 300.0),
)


class Coin:
    def __init__(self, x: float, y: float):
        self.x = float(x)
        self.y = float(y)
        self.alive = True


class Demo1Course:
    """Car pose, coins, and the score. The soft gateway is passed in per call."""

    def __init__(self, *, rng=None, clock=None, respawn_s: float = RESPAWN_S):
        self.rng = rng or random.Random()
        self._clock = clock or (lambda: 0.0)
        self.respawn_s = float(respawn_s)
        self.car_x, self.car_y = CAR_START
        self.heading = 0.0
        self.score = 0
        self.last_pickup_boost = False
        self.coins = [Coin(x, y) for x, y in COIN_SPOTS]
        self._in_oil = False
        self._empty_since = None

    def remaining(self) -> int:
        return sum(1 for coin in self.coins if coin.alive)

    def simulate_detect(self, label, confidence: float = 1.0, *, soft: SoftGateway | None = None) -> bool:
        """Same hook a later camera can call. Only ``coin`` scores."""
        del confidence
        if str(label).strip().lower() != "coin":
            return False
        return self.collect_nearest(soft)

    def collect_nearest(self, soft: SoftGateway | None = None) -> bool:
        best = None
        best_d = None
        for coin in self.coins:
            if not coin.alive:
                continue
            distance = math.hypot(coin.x - self.car_x, coin.y - self.car_y)
            if best_d is None or distance < best_d:
                best = coin
                best_d = distance
        if best is None:
            return False
        return self._take(best, soft)

    def collect_at(self, x: float, y: float, soft: SoftGateway | None = None) -> bool:
        """Pick up the coin under a map click. Misses do not score."""
        for coin in self.coins:
            if not coin.alive:
                continue
            if math.hypot(coin.x - x, coin.y - y) <= COIN_RADIUS + 4:
                return self._take(coin, soft)
        return False

    def step(self, dt: float, held: set[str], soft: SoftGateway | None = None) -> None:
        """Advance the sprite. E-stop holds the car still; coins can still respawn."""
        dt = max(0.0, float(dt))
        if soft is not None and soft.estop_latched:
            self._maybe_respawn()
            return
        self._drive(dt, held, soft)
        self._oil(soft)
        self._drive_over(soft)
        self._maybe_respawn()

    def _drive(self, dt: float, held: set[str], soft: SoftGateway | None) -> None:
        if soft is not None and soft.power == "freeze":
            return
        if "left" in held and "right" not in held:
            self.heading -= TURN_DEG_S * dt
        elif "right" in held and "left" not in held:
            self.heading += TURN_DEG_S * dt
        if soft is not None and soft.power == "steer" and not soft.estop_latched:
            self.heading += soft.steer_sign * STEER_DRIFT_DEG_S * dt
        self.heading %= 360.0
        direction = 0
        if "up" in held and "down" not in held:
            direction = 1
        elif "down" in held and "up" not in held:
            direction = -1
        if direction == 0 or dt == 0.0:
            return
        scale = 1.0
        if soft is not None and soft.power == "boost":
            scale = 1.5
        elif soft is not None and soft.power == "slow":
            scale = 0.4
        rad = math.radians(self.heading)
        distance = FORWARD_PX_S * dt * direction * scale
        self.car_x += math.sin(rad) * distance
        self.car_y -= math.cos(rad) * distance
        margin = CAR_RADIUS + 4
        self.car_x = min(MAP_W - margin, max(margin, self.car_x))
        self.car_y = min(MAP_H - margin, max(margin, self.car_y))

    def _oil(self, soft: SoftGateway | None) -> None:
        inside = self._car_in_oil()
        if inside and not self._in_oil and soft is not None:
            soft.activate("slow")
        self._in_oil = inside

    def _car_in_oil(self) -> bool:
        x, y, w, h = OIL_RECT
        return x <= self.car_x <= x + w and y <= self.car_y <= y + h

    def _drive_over(self, soft: SoftGateway | None) -> None:
        for coin in self.coins:
            if not coin.alive:
                continue
            if math.hypot(coin.x - self.car_x, coin.y - self.car_y) <= PICKUP_RADIUS:
                self._take(coin, soft)
                return

    def _take(self, coin: Coin, soft: SoftGateway | None) -> bool:
        if not coin.alive:
            return False
        coin.alive = False
        self.score += 1
        self.last_pickup_boost = False
        if self.rng.random() < BOOST_CHANCE and soft is not None:
            self.last_pickup_boost = bool(soft.activate("boost"))
        if self.remaining() == 0:
            self._empty_since = self._now()
        return True

    def _maybe_respawn(self) -> None:
        if self.remaining() > 0:
            self._empty_since = None
            return
        now = self._now()
        if self._empty_since is None:
            self._empty_since = now
        if now - self._empty_since >= self.respawn_s:
            for coin in self.coins:
                coin.alive = True
            self._empty_since = None

    def _now(self) -> float:
        return float(self._clock())

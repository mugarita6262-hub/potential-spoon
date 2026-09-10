"""人間らしい操作間隔をつくるためのペーサー。

- 各操作の間はガウス分布ぎみのランダム待ち（一定間隔にしない）
- ときどき長い休憩（人が席を立つ感じ）
- たまにサッと連続（気が乗っている感じ）
"""
from __future__ import annotations

import random
import time


class Pacer:
    def __init__(self, base=(6.0, 15.0), *, burst_chance=0.12, burst=(2.0, 4.0),
                 rest_every=(9, 18), rest=(35.0, 110.0)):
        self.lo, self.hi = base
        self.burst_chance = burst_chance
        self.burst = burst
        self.rest_min, self.rest_max = rest
        self._n = 0
        self._next_rest = random.randint(*rest_every)
        self._rest_every = rest_every

    def _gauss_between(self, lo: float, hi: float) -> float:
        mid = (lo + hi) / 2
        sd = (hi - lo) / 4
        return max(lo, min(hi, random.gauss(mid, sd)))

    def wait(self, on_rest=None) -> float:
        """操作の合間に呼ぶ。待った秒数を返す。"""
        self._n += 1
        if self._n >= self._next_rest:
            self._n = 0
            self._next_rest = random.randint(*self._rest_every)
            secs = random.uniform(self.rest_min, self.rest_max)
            if on_rest:
                on_rest(secs)
            time.sleep(secs)
            return secs
        if random.random() < self.burst_chance:
            secs = random.uniform(*self.burst)
        else:
            secs = self._gauss_between(self.lo, self.hi)
        time.sleep(secs)
        return secs


def jitter(seconds: float, frac: float = 0.35) -> None:
    """1回だけの軽い待ち（±frac のゆらぎ）。"""
    time.sleep(max(0.2, seconds * random.uniform(1 - frac, 1 + frac)))


def maybe_pause_long(chance: float = 0.05, rng=(20.0, 60.0)) -> None:
    """低確率で長めに止まる。"""
    if random.random() < chance:
        time.sleep(random.uniform(*rng))

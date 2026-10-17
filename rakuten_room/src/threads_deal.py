"""Threadsの値下がり速報で「どのジャンルを・誰に向けて」出すかを決める。

2026-10-18: Threadsは「楽天の値下がり情報アカウント」に一本化。
欲しい人が欲しいタイミングで「ちょうど探してたやつが下がってる」と思える投稿にするため、
時間帯（朝・昼・夜）と季節に合うジャンルを優先し、ジャンル内のペルソナ（GENRE_PERSONAS）
のうち値下がり商品が一番多い層に向けて書く。
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime

# 時間帯ごとに「その時間に思い出す・調べる」ジャンル
SLOT_GENRES = {
    "morning": {"coffee", "water", "rice", "instant", "frozen", "contact", "daily", "battery", "stationery",
                "phone", "kairo", "bicycle", "cyclegear", "bottle", "outer"},
    "noon": {"kitchen", "seasoning", "meat", "fruit", "frozen", "tableware", "bottle", "cleaning", "detergent",
             "laundry", "kitchensupply", "baby", "kidswear", "toy", "gift", "xmas", "osechi", "nabe", "towel"},
    "night": {"sleep", "roomwear", "interior", "lighting", "desk", "storage", "kaden", "cleaner", "heater",
              "pcgear", "ink", "alcohol", "pet", "baby", "outer", "inner", "bag", "wallet", "watch", "sneaker",
              "hairtool", "outdoor", "car", "techo", "randoseru", "kidsbike", "bousai", "gift", "clothcare", "nabe"},
}

# 季節に合うジャンル（月ごと）。ここに入ると優先、SEASON_ONLY は時期外なら出さない
SEASON_GENRES = {
    1: {"heater", "kairo", "outer", "nabe", "randoseru", "techo"},
    2: {"heater", "kairo", "outer", "nabe", "randoseru", "kidsbike"},
    3: {"kidsbike", "bicycle", "cyclegear", "stationery", "randoseru", "storage", "desk"},
    4: {"bicycle", "cyclegear", "kidsbike", "stationery", "outdoor", "randoseru"},
    5: {"outdoor", "bicycle", "cyclegear", "water", "randoseru"},
    6: {"water", "laundry", "randoseru", "outdoor", "bousai"},
    7: {"water", "outdoor", "randoseru", "bottle"},
    8: {"water", "outdoor", "bousai", "randoseru", "bottle"},
    9: {"bousai", "outdoor", "bicycle", "cyclegear"},
    10: {"heater", "kairo", "outer", "nabe", "techo", "sleep", "roomwear", "xmas"},
    11: {"heater", "kairo", "outer", "nabe", "techo", "xmas", "osechi", "gift", "sleep", "roomwear"},
    12: {"heater", "kairo", "outer", "nabe", "techo", "xmas", "osechi", "gift", "cleaning"},
}
SEASON_ONLY = {
    "xmas": lambda d: (d.month == 10 and d.day >= 15) or d.month == 11 or (d.month == 12 and d.day <= 24),
    "osechi": lambda d: (d.month == 10 and d.day >= 15) or d.month == 11 or (d.month == 12 and d.day <= 30),
    "kairo": lambda d: d.month in (10, 11, 12, 1, 2, 3),
    "heater": lambda d: d.month in (9, 10, 11, 12, 1, 2, 3),
}


def slot_of(now: datetime) -> str:
    h = now.hour
    return "morning" if h < 10 else "noon" if h < 16 else "night"


def genre_score(slug: str, n_drops: int, now: datetime) -> float:
    d = now.date() if isinstance(now, datetime) else date.today()
    if slug in SEASON_ONLY and not SEASON_ONLY[slug](d):
        return 0.0
    s = math.log2(n_drops + 1)
    if slug in SLOT_GENRES[slot_of(now)]:
        s *= 2.0
    if slug in SEASON_GENRES.get(d.month, set()):
        s *= 1.8
    return s


def pick_persona(slug: str, drops: list[dict], personas: dict) -> tuple[str, list[dict]]:
    """値下がり商品が一番多いペルソナ（「〜な人に」）と、その人向けの値下がり商品を返す。
    ペルソナに当てはまる商品が2件未満ならジャンル全体（ペルソナ名は空）。"""
    best = ("", drops)
    for label, kws, _ in personas.get(slug, []):
        hit = [d for d in drops if any(k in (d.get("itemName") or "") for k in kws)]
        if len(hit) >= 2 and (not best[0] or len(hit) > len(best[1])):
            best = (label, hit)
    return best


def post_name(name: str, limit: int = 26) -> str:
    """投稿の一覧用に、商品名を単語の切れ目で短くする（同じ語のくり返しや宣伝文句は落とす）。"""
    from .site_builder import _short_name

    words, out = _short_name(name, 120).split(" "), []
    for w in words:
        if not w or any(w in o or o in w for o in out) or re.search(r"送料|ポイント|クーポン|倍|OFF|off|SALE|セール|登場|限定|発送|評価|★|ランキング|位|即納|あす楽|まで|納税|支援|使用", w):
            continue
        if len(" ".join(out + [w])) > limit:
            break
        out.append(w)
    return " ".join(out) or _short_name(name, limit)

"""薬機法・健康増進法のリスクが高い商品を、SNS・ROOMの紹介候補から外す。

2026-10-06、Instagramでエクオール（サプリ）を紹介した投稿に、AIが「朝の目覚めが
スッキリした気がします」という効果の体験談を書いてしまった。プロンプトで禁止しても
商品自体が「効果」を売りにしているとAIが寄っていくので、候補の段階で除外する。
"""
from __future__ import annotations

# 商品名にこれらが含まれていたら紹介しない（健康食品・医薬品・医薬部外品・効能が売りの化粧品など）
RISKY_WORDS = (
    "サプリ", "エクオール", "青汁", "酵素", "乳酸菌", "ビフィズス", "プラセンタ", "コラーゲン",
    "機能性表示", "特定保健用", "トクホ", "健康食品", "栄養補助", "医薬品", "医薬部外品", "第2類",
    "第3類", "指定第2類", "漢方", "薬用", "育毛", "発毛", "白髪染", "ダイエット", "痩せ", "美白",
    "シミ", "ニキビ", "精力", "免疫", "デトックス", "便秘", "睡眠サポート", "快眠サプリ",
    "リンクル", "シワ", "しわ", "レチノ", "たるみ", "エイジング",
)


def is_risky(item: dict) -> bool:
    name = item.get("itemName") or item.get("program_name") or ""
    return any(w in name for w in RISKY_WORDS)


def drop_risky(items: list[dict]) -> list[dict]:
    return [it for it in items if not is_risky(it)]

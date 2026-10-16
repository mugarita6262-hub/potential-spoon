"""買い時ナビ（kaidokinavi.com）の静的サイトを生成する。

楽天の商品検索でジャンルごとの候補を集め、価格を毎日 price_history に記録し、
「人気ランキング」と「値下がりランキング」を数字の根拠つきで出す。
他のランキングサイトとの違いは、自前で毎日記録している価格推移を見せられること。
読み物（選び方ガイド）は content/guides/<genre>/*.md を置くと各ジャンルに載る。

サーバーで1日1回 `python -m src.main site` で再生成する（Caddyが配信）。
"""
from __future__ import annotations

import html
import json
import math
import os
import random
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from .config import DATA_DIR

SITE_NAME = "買い時ナビ"
SITE_URL = "https://kaidokinavi.com"
OUT_DIR = Path("/home/kirui/kaidokinavi")
GUIDES_DIR = Path(__file__).resolve().parent.parent / "content" / "guides"
SITE_ITEMS_FILE = DATA_DIR / "site_items.json"

GENRES = [
    {"slug": "coffee", "name": "コーヒー・お茶", "emoji": "☕",
     "lead": "毎日飲むものだから、少しでもおいしく、少しでも安く。",
     "keywords": ["コーヒー豆", "ドリップバッグ コーヒー", "紅茶 ティーバッグ", "インスタントコーヒー"],
     "a8_genres": ["飲料・カフェ"]},
    {"slug": "sleep", "name": "寝具・睡眠", "emoji": "🛏️",
     "lead": "毎晩使うものは、少し良いものを納得の値段で。",
     "keywords": ["枕", "マットレス", "掛け布団", "敷きパッド"],
     "a8_genres": ["暮らし・家事", "寝具・睡眠"]},
    {"slug": "kitchen", "name": "キッチン・家事", "emoji": "🍳",
     "lead": "毎日の台所仕事を、ちょっとラクにする道具たち。",
     "keywords": ["フライパン", "電気ケトル", "保存容器", "食器用洗剤"],
     "a8_genres": ["キッチン・家事"]},
    {"slug": "pet", "name": "ペット", "emoji": "🐾",
     "lead": "毎日のごはんとケア用品は、続けやすさと値段のバランスで。",
     "keywords": ["ドッグフード", "キャットフード", "猫砂", "ペット おやつ"],
     "a8_genres": ["ペット"]},
    {"slug": "water", "name": "水・飲料", "emoji": "💧",
     "lead": "重くてかさばる飲み物こそ、まとめ買いの単価で差がつきます。",
     "keywords": ["ミネラルウォーター 2L", "炭酸水 500ml", "お茶 ペットボトル", "野菜ジュース"],
     "a8_genres": ["飲料・カフェ", "水・飲料"]},
    {"slug": "rice", "name": "お米・食品", "emoji": "🍚",
     "lead": "値動きの大きいお米は、買うタイミングで年間の出費が変わります。",
     "keywords": ["お米 10kg", "無洗米", "パックご飯", "レトルトカレー"],
     "a8_genres": ["食品・宅食", "お米・食品"]},
    {"slug": "contact", "name": "コンタクトレンズ", "emoji": "👁️",
     "lead": "毎月買うものだから、同じレンズを少しでも安く。",
     "keywords": ["ワンデー コンタクト", "2ウィーク コンタクト", "カラコン ワンデー", "コンタクト 保存液"],
     "a8_genres": ["コンタクト"]},
    {"slug": "baby", "name": "ベビー・おむつ", "emoji": "👶",
     "lead": "おむつやおしりふきは、まとめ買いのタイミングが家計の味方です。",
     "keywords": ["おむつ テープ", "おむつ パンツ", "おしりふき", "粉ミルク"],
     "a8_genres": ["ベビー・キッズ"]},
    {"slug": "daily", "name": "日用品・紙もの", "emoji": "🧻",
     "lead": "トイレットペーパーやティッシュは、なくなる前の値下がりで買うのがいちばん。",
     "keywords": ["トイレットペーパー", "ティッシュペーパー", "キッチンペーパー", "ゴミ袋 45L"],
     "a8_genres": ["日用品"]},
    {"slug": "detergent", "name": "洗剤・掃除", "emoji": "🧺",
     "lead": "毎日使う洗剤は、詰め替えのまとめ買いで1回あたりの値段を下げられます。",
     "keywords": ["洗濯洗剤 詰め替え", "柔軟剤 詰め替え", "食洗機 洗剤", "フローリング 掃除シート"],
     "a8_genres": ["洗剤・掃除", "暮らし・家事"]},
    {"slug": "alcohol", "name": "ビール・お酒", "emoji": "🍺",
     "lead": "重いケース買いこそ、ネットの値下がりと送料込みの単価で比べたい。",
     "keywords": ["ビール ケース", "発泡酒 ケース", "チューハイ ケース", "ハイボール 缶"],
     "a8_genres": ["お酒"],
     "notice": "お酒は20歳になってから。20歳未満の方の飲酒は法律で禁止されています。妊娠中・授乳期の飲酒や、飲酒運転はやめましょう。"},
    {"slug": "bousai", "name": "防災・備蓄", "emoji": "🔦",
     "lead": "いざという時の備えは、値下がりの時にまとめてそろえておくのが賢い買い方です。",
     "keywords": ["保存水 5年", "非常食 5年保存", "防災セット", "モバイルバッテリー"],
     "a8_genres": ["防災・備蓄"]},
    {"slug": "instant", "name": "インスタント・お菓子", "emoji": "🍜",
     "lead": "カップ麺やお菓子は、ケース買いの単価で差がつく定番の「まとめ買い」商品。",
     "keywords": ["カップラーメン 箱買い", "袋麺 5食パック", "スナック菓子 まとめ買い", "お菓子 詰め合わせ 個包装"],
     "a8_genres": ["食品・スイーツ"]},
    {"slug": "interior", "name": "インテリア・収納", "emoji": "🛋️",
     "lead": "ラグや収納は大物だからこそ、値下がりと評判で失敗しない一品を。",
     "keywords": ["収納ボックス", "ラグ カーペット", "遮光カーテン", "スチールラック"],
     "a8_genres": ["インテリア・収納"]},
    {"slug": "outdoor", "name": "アウトドア・キャンプ", "emoji": "🏕️",
     "lead": "キャンプ道具は、シーズン前後の値下がりでそろえるのがおすすめ。",
     "keywords": ["キャンプ チェア", "寝袋 シュラフ", "クーラーボックス", "ランタン LED"],
     "a8_genres": ["アウトドア"]},
    {"slug": "heater", "name": "暖房・加湿", "emoji": "🔥",
     "lead": "寒くなる前がいちばん選べる。暖房と加湿器は、値下がりの早いうちに。",
     "keywords": ["セラミックヒーター", "電気毛布", "こたつ", "加湿器"],
     "a8_genres": ["家電"]},
    {"slug": "cleaner", "name": "掃除機", "emoji": "🧹",
     "lead": "コードレスもロボットも、型落ちや値下がりのタイミングで差がつきます。",
     "keywords": ["コードレス掃除機", "ロボット掃除機", "ハンディクリーナー", "布団クリーナー"],
     "a8_genres": ["家電"]},
    {"slug": "towel", "name": "タオル", "emoji": "🛁",
     "lead": "毎日使うタオルは、まとめ買いでそろえ直すと1枚あたりがぐっと安く。",
     "keywords": ["バスタオル", "フェイスタオル", "今治タオル", "ホテルタオル"],
     "a8_genres": ["日用品"]},
    {"slug": "toy", "name": "おもちゃ・知育", "emoji": "🧸",
     "lead": "誕生日やクリスマスのプレゼントは、評判と値下がりで早めに確保。",
     "keywords": ["知育玩具", "ブロック おもちゃ", "木のおもちゃ", "パズル 子供"],
     "a8_genres": ["ベビー・キッズ"]},
    {"slug": "osechi", "name": "おせち", "emoji": "🎍",
     "lead": "おせちは予約が早いほど割引が大きいことも。人気のものから売り切れます。",
     "keywords": ["おせち 2027", "おせち 冷凍", "おせち 2人前", "おせち 4人前"],
     "a8_genres": ["食品・宅食"]},
    {"slug": "meat", "name": "肉・海鮮", "emoji": "🥩",
     "lead": "お取り寄せの肉やカニは、訳ありや値下がりで買うと満足度が段違い。",
     "keywords": ["訳あり 牛肉", "ズワイガニ", "うなぎ 蒲焼き", "ハンバーグ 冷凍"],
     "a8_genres": ["食品・宅食"]},
    {"slug": "fruit", "name": "果物", "emoji": "🍊",
     "lead": "旬の果物は、産地直送のまとめ買いが安くておいしい。",
     "keywords": ["みかん 訳あり", "りんご 訳あり", "シャインマスカット", "柿"],
     "a8_genres": ["食品・宅食"]},
    {"slug": "phone", "name": "スマホ周辺", "emoji": "📱",
     "lead": "充電器やケーブルは消耗品。評判の良いものを安いときに。",
     "keywords": ["USB-C 充電器", "充電ケーブル", "スマホスタンド", "ワイヤレス充電器"],
     "a8_genres": ["家電"]},
    {"slug": "pcgear", "name": "PC周辺", "emoji": "⌨️",
     "lead": "マウスやキーボードは、毎日使うから評判で選んで値下がりで買う。",
     "keywords": ["ワイヤレスマウス", "ワイヤレスキーボード", "モニター 24インチ", "USBハブ"],
     "a8_genres": ["家電"]},
    {"slug": "gift", "name": "ギフト・お歳暮", "emoji": "🎁",
     "lead": "お歳暮や内祝いは、早割と評判で選ぶと失敗しません。",
     "keywords": ["お歳暮 ギフト", "カタログギフト", "内祝い お菓子", "グルメギフト"],
     "a8_genres": ["ギフト"]},
    {"slug": "kaden", "name": "調理家電", "emoji": "🍚",
     "lead": "炊飯器や電子レンジは、新モデルが出る前後の値下がりが狙い目です。",
     "keywords": ["炊飯器", "電子レンジ", "オーブントースター", "電気圧力鍋"],
     "a8_genres": ["家電"]},
    {"slug": "car", "name": "カー用品", "emoji": "🚗",
     "lead": "ドラレコやチャイルドシートは、評判と値下がりで納得の一台を。",
     "keywords": ["ドライブレコーダー", "カーナビ ポータブル", "チャイルドシート", "車載 スマホホルダー"],
     "a8_genres": ["カー用品"]},
    {"slug": "randoseru", "name": "ランドセル", "emoji": "🎒",
     "lead": "6年間使うランドセルは、人気モデルが売り切れる前に比べて選びたい。",
     "keywords": ["ランドセル 2027", "ランドセル 女の子", "ランドセル 男の子", "ランドセルカバー"],
     "a8_genres": ["ベビー・キッズ"]},
    {"slug": "roomwear", "name": "ルームウェア・スリッパ", "emoji": "🧦",
     "lead": "毎日着る部屋着とスリッパは、寒くなる前の値下がりでそろえ直し。",
     "keywords": ["ルームウェア レディース", "ルームウェア メンズ", "着る毛布", "スリッパ 冬"],
     "a8_genres": ["ファッション"]},
    {"slug": "techo", "name": "手帳・カレンダー", "emoji": "📒",
     "lead": "来年の手帳は、種類がそろっている秋のうちに選ぶのが正解。",
     "keywords": ["手帳 2027", "手帳 ウィークリー", "カレンダー 2027 壁掛け", "卓上カレンダー 2027"],
     "a8_genres": ["文房具"]},
    {"slug": "bicycle", "name": "自転車", "emoji": "🚲",
     "lead": "通勤・通学・子ども乗せ。毎日乗る一台は、評判と値下がりで選びたい。",
     "keywords": ["自転車 27インチ", "電動アシスト自転車", "子供乗せ 自転車", "自転車 ヘルメット"],
     "a8_genres": ["自転車"]},
    {"slug": "battery", "name": "電池・電球", "emoji": "🔋",
     "lead": "電池や電球は、切れる前にまとめ買いしておくと安心で安い。",
     "keywords": ["単3 電池 アルカリ", "充電池 単3", "LED電球 E26", "LED電球 E17"],
     "a8_genres": ["日用品"]},
    {"slug": "clothcare", "name": "衣類ケア", "emoji": "👔",
     "lead": "アイロンやスチーマーで、毎朝の身支度をもっとラクに。",
     "keywords": ["衣類スチーマー", "アイロン コードレス", "毛玉取り器", "アイロン台"],
     "a8_genres": ["家電"]},
    {"slug": "kitchensupply", "name": "キッチン消耗品", "emoji": "🥡",
     "lead": "ラップや保存袋は毎月なくなるもの。まとめ買いの単価で差がつきます。",
     "keywords": ["ラップ 業務用", "アルミホイル", "食品保存袋 ジッパー", "キッチン ポリ袋"],
     "a8_genres": ["日用品"]},
    {"slug": "kairo", "name": "カイロ・防寒小物", "emoji": "🧤",
     "lead": "使い捨てカイロや手袋は、寒くなる前のまとめ買いが安くて確実。",
     "keywords": ["カイロ 貼る", "カイロ 貼らない まとめ買い", "手袋 スマホ対応", "ネックウォーマー"],
     "a8_genres": ["ファッション"]},
    {"slug": "laundry", "name": "洗濯グッズ", "emoji": "👕",
     "lead": "ハンガーや物干しは、そろえ直すと毎日の洗濯がぐっとラクに。",
     "keywords": ["洗濯ネット", "ハンガー すべらない", "室内物干し", "ピンチハンガー"],
     "a8_genres": ["日用品"]},
    {"slug": "stationery", "name": "文房具", "emoji": "✏️",
     "lead": "ノートやペンは、使い慣れたものをまとめ買いしておくと安心。",
     "keywords": ["ノート まとめ買い", "ボールペン 替芯", "ふせん", "シャープペンシル"],
     "a8_genres": ["文房具"]},
    {"slug": "cleaning", "name": "掃除用品・大掃除", "emoji": "🧽",
     "lead": "シートやスポンジは毎月なくなるもの。年末の大掃除の前に、まとめ買いの単価を比べておきましょう。",
     "keywords": ["フローリングワイパー シート", "メラミンスポンジ", "マイクロファイバー クロス", "お風呂 掃除 ブラシ"],
     "a8_genres": ["日用品"]},
    {"slug": "ink", "name": "プリンターインク", "emoji": "🖨️",
     "lead": "年賀状の季節の前に。純正と互換、1枚あたりのコストで比べると選びやすくなります。",
     "keywords": ["プリンターインク 互換 エプソン", "プリンターインク 互換 キヤノン", "インクカートリッジ 純正", "写真用紙 L判"],
     "a8_genres": ["家電"]},
    {"slug": "xmas", "name": "クリスマス", "emoji": "🎄",
     "lead": "ツリーや飾りは、早めに比べておくと選べる幅が広がります。",
     "keywords": ["クリスマスツリー", "クリスマス オーナメント", "イルミネーション LED", "クリスマスリース"],
     "a8_genres": ["インテリア"]},
    {"slug": "storage", "name": "衣替え・圧縮袋", "emoji": "🧳",
     "lead": "衣替えや布団の入れ替えに。圧縮袋や衣装ケースで、季節ものをすっきりしまえます。",
     "keywords": ["布団圧縮袋", "衣類圧縮袋", "衣装ケース 引き出し", "不織布 収納袋 布団"],
     "a8_genres": ["インテリア"]},
    {"slug": "seasoning", "name": "調味料・油", "emoji": "🫒",
     "lead": "油や醤油、だしは毎日使うもの。大きめサイズやまとめ買いで単価が変わります。",
     "keywords": ["オリーブオイル エキストラバージン", "醤油 まとめ買い", "だしパック", "米油"],
     "a8_genres": ["食品"]},
    {"slug": "nabe", "name": "鍋・土鍋", "emoji": "🍲",
     "lead": "寒くなると出番が増える鍋。人数とコンロ（ガス・IH）に合うものを選ぶのがコツです。",
     "keywords": ["土鍋", "両手鍋 IH対応", "すき焼き鍋", "卓上鍋 IH"],
     "a8_genres": ["キッチン"]},
    {"slug": "frozen", "name": "冷凍食品", "emoji": "🥟",
     "lead": "忙しい日の味方。まとめ買いは、冷凍庫の空きと1食あたりの価格で比べましょう。",
     "keywords": ["冷凍食品 まとめ買い", "冷凍餃子", "冷凍 惣菜 セット", "冷凍うどん"],
     "a8_genres": ["冷凍・宅食"]},
    {"slug": "tableware", "name": "食器・マグカップ", "emoji": "🍽️",
     "lead": "毎日使う食器は、電子レンジ・食洗機に対応しているかで使い勝手が変わります。",
     "keywords": ["食器セット", "マグカップ おしゃれ", "お皿 電子レンジ対応", "茶碗"],
     "a8_genres": ["キッチン"]},
    {"slug": "bottle", "name": "水筒・タンブラー", "emoji": "🥤",
     "lead": "飲み物を持ち歩くと、毎日の出費も減らせます。容量と保温・保冷の時間で選びましょう。",
     "keywords": ["水筒 ステンレス", "タンブラー 蓋付き 保温", "マグボトル", "水筒 子供"],
     "a8_genres": ["キッチン"]},
    {"slug": "inner", "name": "あったかインナー・タイツ", "emoji": "🧦",
     "lead": "冬の重ね着は、インナーとタイツで差がつきます。素材と厚さの選び方をまとめました。",
     "keywords": ["あったかインナー レディース", "発熱インナー メンズ", "裏起毛 タイツ", "タイツ 110デニール"],
     "a8_genres": ["ファッション"]},
    {"slug": "hairtool", "name": "ヘアアイロン・ドライヤー", "emoji": "💇",
     "lead": "毎朝使うものだから、温度・幅・重さで選ぶと失敗しません。",
     "keywords": ["ヘアアイロン ストレート", "カールアイロン", "ドライヤー 大風量", "ヘアアイロン 2way"],
     "a8_genres": ["美容家電"]},
    {"slug": "bag", "name": "バッグ", "emoji": "👜",
     "lead": "毎日持つバッグは、入れたい物の大きさと開け閉めのしやすさで選ぶのがコツです。",
     "keywords": ["トートバッグ レディース", "リュック 通勤", "ショルダーバッグ", "トートバッグ A4"],
     "a8_genres": ["ファッション"]},
    {"slug": "sneaker", "name": "スニーカー", "emoji": "👟",
     "lead": "サイズとはき心地が大事なスニーカー。評判とサイズ感の口コミで選びましょう。",
     "keywords": ["スニーカー レディース", "スニーカー メンズ", "厚底スニーカー", "スリッポン"],
     "a8_genres": ["ファッション"]},
    {"slug": "outer", "name": "冬アウター（ダウン・コート）", "emoji": "🧥",
     "lead": "ダウンやコートは、暖かさの目安と丈・重さで選ぶと、冬じゅう活躍します。",
     "keywords": ["ダウンジャケット レディース", "ダウンジャケット メンズ", "コート レディース 冬", "中綿ジャケット"],
     "a8_genres": ["ファッション"]},
    {"slug": "kidswear", "name": "子供服", "emoji": "🧒",
     "lead": "すぐに大きくなる子供服は、サイズの選び方とまとめ買いの単価がポイントです。",
     "keywords": ["子供服 トレーナー", "キッズ アウター", "子供服 長袖 セット", "ベビー服 秋冬"],
     "a8_genres": ["ベビー・キッズ"]},
    {"slug": "cyclegear", "name": "自転車用品・パーツ", "emoji": "🚴",
     "lead": "ライト・ロック・ヘルメット・空気入れ。毎日の自転車を安全で快適にする用品をまとめました。",
     "keywords": ["自転車 ライト 充電式", "自転車 ロック", "自転車 ヘルメット 大人", "自転車 空気入れ"],
     "a8_genres": ["自転車"]},
    {"slug": "wallet", "name": "財布・キーケース", "emoji": "👛",
     "lead": "毎日持ち歩く財布は、入れる物の量と、バッグの大きさで選ぶのがコツです。",
     "keywords": ["財布 レディース 二つ折り", "ミニ財布", "長財布 メンズ", "キーケース"],
     "a8_genres": ["ファッション"]},
    {"slug": "watch", "name": "腕時計", "emoji": "⌚",
     "lead": "電池交換がいらないソーラーや、時刻が合う電波時計など、仕組みで選ぶと長く使えます。",
     "keywords": ["腕時計 メンズ ソーラー", "腕時計 レディース", "電波時計 腕時計", "腕時計 防水"],
     "a8_genres": ["ファッション"]},
    {"slug": "lighting", "name": "照明・電球", "emoji": "💡",
     "lead": "部屋の明るさは、畳数に合った照明と、光の色で決まります。",
     "keywords": ["シーリングライト 6畳", "シーリングライト 調光調色", "LED電球 E26", "ペンダントライト"],
     "a8_genres": ["インテリア・収納"]},
    {"slug": "desk", "name": "デスク・チェア", "emoji": "🪑",
     "lead": "在宅ワークや勉強の机と椅子は、置き場所の寸法と、座る時間の長さで選びましょう。",
     "keywords": ["パソコンデスク", "昇降デスク", "オフィスチェア", "デスクチェア 在宅"],
     "a8_genres": ["インテリア・収納"]},
    {"slug": "kidsbike", "name": "子ども用自転車・キックバイク", "emoji": "🚲",
     "lead": "子どもの自転車は、インチ（タイヤの大きさ）を身長に合わせて選ぶのが基本です。",
     "keywords": ["子供用自転車 16インチ", "子供用自転車 20インチ", "キックバイク", "ストライダー"],
     "a8_genres": ["自転車"]},
]

MIN_REVIEWS = 20
MIN_AVG = 3.8
DROP_MIN_PCT = 5.0
TOP_N = 10
# 1つの検索キーワードから評判ランキングに入れる上限。レビュー件数の多い商品（お菓子など）が
# 上位を独占して、ジャンルの他の商品（カップ麺・寝具ならマットレス等）が消えるのを防ぐ
PER_KEYWORD_MAX = 3


# ---------------------------------------------------------------- データ収集
def collect(api) -> dict[str, list[dict]]:
    """ジャンルごとに楽天で商品を集め、価格を記録する。{slug: [item, ...]} を保存して返す。"""
    from .price_history import record_snapshot
    from .rakuten_api import dedupe

    result: dict[str, list[dict]] = {}
    for g in GENRES:
        items: list[dict] = []
        for kw in g["keywords"]:
            try:
                items += [{**it, "keyword": kw} for it in api.search(kw, 30)]
            except Exception as exc:  # noqa: BLE001
                print(f"  検索失敗 {kw}: {exc}")
            time.sleep(1.2)  # 楽天APIの呼び出し間隔
        items = [it for it in dedupe(items)
                 if it["reviewCount"] >= MIN_REVIEWS and it["reviewAverage"] >= MIN_AVG]
        record_snapshot(items)
        result[g["slug"]] = items
        print(f"  {g['name']}: {len(items)}件")
        if os.environ.get("YAHOO_APP_ID"):
            yitems = []
            for kw in g["keywords"]:
                try:
                    yitems += [{**it, "keyword": kw} for it in yahoo_search(kw, 30)]
                except Exception as exc:  # noqa: BLE001
                    print(f"  Yahoo検索失敗 {kw}: {exc}")
                time.sleep(1.2)
            seen: set[str] = set()
            yitems = [it for it in yitems if not (it["itemCode"] in seen or seen.add(it["itemCode"]))
                      and it["reviewCount"] >= MIN_REVIEWS and it["reviewAverage"] >= MIN_AVG]
            record_snapshot(yitems)
            result[f"yahoo:{g['slug']}"] = yitems
            print(f"  {g['name']}（Yahoo!）: {len(yitems)}件")
    SITE_ITEMS_FILE.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def yahoo_search(query: str, n: int = 30) -> list[dict]:
    """Yahoo!ショッピングの商品検索（レビュー件数順）。楽天の商品と同じ形の辞書で返す。
    Client IDはURLパラメータだと403になるため、ヘッダー（User-Agent）で渡す。"""
    import requests

    r = requests.get("https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch",
                     params={"query": query, "results": n, "sort": "-review_count"},
                     headers={"User-Agent": f"Yahoo AppID: {os.environ['YAHOO_APP_ID']}"}, timeout=20)
    r.raise_for_status()
    out = []
    for h in r.json().get("hits", []):
        rev = h.get("review") or {}
        out.append({
            "itemCode": f"yahoo:{h['code']}", "itemName": h.get("name", ""),
            "itemUrl": h.get("url", ""), "affiliateUrl": h.get("url", ""),
            "price": int(h.get("price") or 0), "shopName": (h.get("seller") or {}).get("name", ""),
            "reviewCount": int(rev.get("count") or 0), "reviewAverage": float(rev.get("rate") or 0),
            "imageUrl": (h.get("image") or {}).get("medium", ""), "mall": "yahoo",
        })
    return out


# ---------------------------------------------------------------- ランキング
def _popularity(it: dict) -> float:
    return it["reviewAverage"] * math.log10(it["reviewCount"] + 1)


def _history(it: dict, hist: dict) -> list[dict]:
    return hist.get(it.get("itemCode") or it.get("itemUrl"), [])


def _enrich(it: dict, hist: dict) -> dict:
    from .price_history import price_drop
    rows = _history(it, hist)
    info = price_drop(it, lookback_days=30, history=hist)
    prices = [r["price"] for r in rows]
    return {**it, **info, "history": rows,
            "days": len(rows), "low": min(prices) if prices else it["price"],
            "high": max(prices) if prices else it["price"]}


def rankings(items: list[dict], hist: dict) -> tuple[list[dict], list[dict]]:
    rich = [_enrich(it, hist) for it in items]
    popular, per_kw, names = [], {}, set()
    for it in sorted(rich, key=_popularity, reverse=True):
        kw = it.get("keyword", "")
        if kw and per_kw.get(kw, 0) >= PER_KEYWORD_MAX:
            continue
        name = _short_name(it.get("itemName", ""), 40)
        if name in names:  # 同じ商品の別ページ（同名）が並ぶのを防ぐ
            continue
        names.add(name)
        per_kw[kw] = per_kw.get(kw, 0) + 1
        popular.append(it)
        if len(popular) >= TOP_N:
            break
    drops = [it for it in rich if it["drop_pct"] >= DROP_MIN_PCT and it["days"] >= 2]
    drops.sort(key=lambda x: (x["drop_pct"], _popularity(x)), reverse=True)
    return popular, drops[:TOP_N]


# ---------------------------------------------------------------- 表示用の共通部品
E = html.escape
ASSETS_DIR = Path(__file__).resolve().parent.parent / "site_assets"
GENRE_BY_SLUG = {g["slug"]: g for g in GENRES}
GENRE_IMG = {g["slug"]: g["slug"] for g in GENRES}
# 楽天のキーワード検索は関係の薄い商品も返すので、ジャンルごとに「商品名に含むべき言葉」で絞る
# （2026-10-07、暖房に座椅子・靴下、タオルにおむつケーキ、スマホ周辺にスーツケースが入っていた）
GENRE_MUST = {
    "coffee": ["コーヒー", "珈琲", "紅茶", "茶", "ドリップ", "ティー", "カフェ", "豆"],
    "kitchen": ["フライパン", "ケトル", "保存容器", "洗剤", "鍋", "包丁", "まな板", "キッチン", "ポット", "容器", "食器"],
    "daily": ["トイレットペーパー", "ティッシュ", "キッチンペーパー", "ゴミ袋", "ごみ袋", "ポリ袋", "ペーパー"],
    "detergent": ["洗剤", "柔軟剤", "掃除", "シート", "洗濯", "漂白", "クリーナー"],
    "water": ["水", "ウォーター", "炭酸", "お茶", "茶", "ジュース", "飲料"],
    "heater": ["ヒーター", "ストーブ", "毛布", "こたつ", "コタツ", "加湿器", "暖房", "ホットカーペット"],
    "cleaner": ["掃除機", "クリーナー", "ロボット"],
    "towel": ["タオル"],
    "toy": ["おもちゃ", "玩具", "ブロック", "パズル", "ままごと", "知育", "積み木", "レゴ", "トイ"],
    "osechi": ["おせち"],
    "fruit": ["みかん", "りんご", "林檎", "柿", "マスカット", "ぶどう", "葡萄", "梨", "いちご", "苺", "フルーツ", "果物", "柑橘", "メロン", "桃"],
    "phone": ["充電", "ケーブル", "スマホ", "iPhone", "アダプタ", "USB"],
    "pcgear": ["マウス", "キーボード", "モニター", "ディスプレイ", "ハブ", "ドック"],
    "kaden": ["炊飯", "レンジ", "トースター", "圧力鍋", "ホットプレート", "ホットクック", "調理"],
    "car": ["ドライブレコーダー", "ドラレコ", "カーナビ", "ナビ", "チャイルドシート", "ジュニアシート", "車載", "車"],
    "randoseru": ["ランドセル"],
    "kitchensupply": ["ラップ", "ホイル", "保存袋", "ジッパー", "ポリ袋", "クッキングシート"],
    "kairo": ["カイロ", "手袋", "ネックウォーマー", "マフラー", "イヤーマフ", "グローブ"],
    "laundry": ["洗濯ネット", "ハンガー", "物干し", "ピンチ", "ランドリー"],
    "stationery": ["ノート", "ボールペン", "替芯", "ふせん", "付箋", "シャープ", "ペン", "消しゴム"],
    "techo": ["手帳", "カレンダー", "ダイアリー", "スケジュール"],
    "bicycle": ["自転車", "サイクル", "ヘルメット", "アシスト"],
    "battery": ["電池", "充電池", "電球", "LED"],
    "clothcare": ["スチーマー", "アイロン", "毛玉", "スチーム"],
    "roomwear": ["ルームウェア", "パジャマ", "スリッパ", "着る毛布", "ルームシューズ", "部屋着", "ガウン"],
    "cleaning": ["シート", "スポンジ", "クロス", "ブラシ", "ワイパー", "モップ", "ほうき", "雑巾", "掃除"],
    "ink": ["インク", "カートリッジ", "写真用紙", "光沢紙"],
    "xmas": ["クリスマス", "ツリー", "オーナメント", "イルミネーション", "リース"],
    "storage": ["圧縮袋", "衣装ケース", "収納袋", "収納ケース", "布団袋", "クローゼット"],
    "seasoning": ["オイル", "油", "醤油", "しょうゆ", "だし", "出汁", "味噌", "みそ", "調味料", "酢"],
    "nabe": ["鍋", "土鍋"],
    "frozen": ["冷凍"],
    "tableware": ["食器", "マグ", "皿", "茶碗", "ボウル", "カップ", "どんぶり", "丼"],
    "bottle": ["水筒", "タンブラー", "ボトル"],
    "inner": ["インナー", "タイツ", "レギンス", "肌着", "ヒートテック"],
    "hairtool": ["アイロン", "ドライヤー"],
    "bag": ["バッグ", "リュック", "トート", "ショルダー", "ポーチ"],
    "sneaker": ["スニーカー", "スリッポン", "シューズ"],
    "outer": ["ダウン", "コート", "ジャケット", "アウター", "ブルゾン", "中綿"],
    "kidswear": ["子供服", "キッズ", "ベビー服", "子ども服", "こども服", "ベビー"],
    "wallet": ["財布", "キーケース", "コインケース", "カードケース", "札入れ"],
    "watch": ["腕時計", "ウォッチ"],
    "lighting": ["シーリング", "ライト", "照明", "電球", "ランプ"],
    "desk": ["デスク", "チェア", "机", "椅子"],
    "kidsbike": ["子供用自転車", "子ども用自転車", "キッズ", "幼児用", "キックバイク", "ストライダー", "バランスバイク", "インチ"],
    "cyclegear": ["ライト", "ロック", "鍵", "ヘルメット", "空気入れ", "ポンプ", "チューブ", "サドル", "グローブ", "スタンド",
                  "カゴ", "バスケット", "サイクルコンピューター", "ボトルケージ", "泥除け"],
}
GENRE_EXCLUDE = {"wallet": ["スマホケース", "手帳型", "iPhone", "バッグ"],
                 "watch": ["スマートウォッチ", "アップルウォッチ", "Apple Watch", "バンド", "ベルト 交換", "保護フィルム", "ケース", "目覚まし", "置き時計", "掛け時計"],
                 "lighting": ["自転車", "懐中電灯", "ヘッドライト", "キャンプ", "ランタン", "車", "バイク", "イルミネーション",
                              "クリスマス", "水槽", "植物", "ライトスタンド 撮影", "リングライト"],
                 "desk": ["ランプ", "ライト", "マット", "ダイニング", "キャスター 交換", "座椅子", "カバー", "クッション", "ゲーム機"],
                 "kidsbike": ["ヘルメット", "ライト", "ロック", "空気入れ", "電動アシスト", "大人用", "26インチ", "27インチ",
                              "ロードバイク", "クロスバイク", "テレビ", "モニター", "スーツケース"],
                 "cyclegear": ["インチ 自転車 本体", "変速", "電動アシスト自転車", "ママチャリ", "シティサイクル", "クロスバイク",
                               "ロードバイク 本体", "子供用自転車", "バイク用", "オートバイ", "原付", "スクーター", "車用",
                               "LEDライト 室内", "シーリング", "懐中電灯", "キャンプ", "ヘッドライト", "三輪車", "バイクロック",
                               "バイク ロック", "バイク用", "ヘッドランプ"],
                 "hairtool": ["衣類", "スチーマー", "アイロン台", "シャツ", "布団", "ケース", "スタンド", "カバー", "収納"],
                 "bag": ["ゴミ", "ごみ", "ポリ", "収納", "エコバッグ 洗剤", "布団", "保存", "冷凍", "ランドセル", "持ち手", "カバー"],
                 "sneaker": ["インソール", "靴紐", "シューレース", "洗剤", "防水スプレー", "ラック", "収納", "乾燥機", "ビジネス", "マリン", "革靴"],
                 "outer": ["ダウンライト", "布団", "掛け", "寝袋", "シュラフ", "毛布", "クリーニング", "ハンガー", "カバー", "ペチコート"],
                 "kidswear": ["おむつ", "オムツ", "おしりふき", "ミルク", "粉ミルク", "ベビーカー", "チャイルドシート", "ベビーベッド",
                              "おもちゃ", "絵本", "ランドセル", "シャンプー", "ローション", "ワセリン", "ソープ", "布団", "スタイ 食事"],
                 "nabe": ["鍋敷き", "鍋つかみ", "ミトン", "スープ", "つゆ", "セット 肉", "具材", "もつ", "火鍋の素", "レシピ", "天ぷら", "揚げ物", "フライヤー"],
                 "frozen": ["冷凍庫", "冷蔵庫", "保存容器", "保存袋", "製氷", "冷凍用"],
                 "tableware": ["カップ麺", "コーヒー豆", "ドリップ", "ブラ", "カップケーキ", "紙皿", "紙コップ", "使い捨て", "フリーズドライ", "茶碗蒸し", "計量"],
                 "bottle": ["ワイン", "焼酎", "日本酒", "ウイスキー", "シャンプー", "化粧", "ミネラルウォーター", "天然水",
                            "スプレー", "詰め替え", "お茶", "飲料", "水切り", "カバー", "ケース", "ポーチ"],
                 "inner": ["マスク", "インナーマッスル", "補正", "着圧", "ダイエット", "骨盤", "シェイプ", "加圧"],
                 "cleaning": ["掃除機", "ロボット", "洗車", "車用", "メイク", "化粧", "洗顔", "ボディ", "フェイス", "メガネ", "めがね", "食器拭き", "スタンド", "収納"],
                 "ink": ["ボールペン", "万年筆", "スタンプ", "朱肉", "インクジェットプリンター本体", "複合機"],
                 "xmas": ["ケーキ", "コフレ", "コスメ", "化粧", "香水", "ランジェリー", "サンタ服", "花苗", "苗"],
                 "seasoning": ["ヘアオイル", "美容", "マッサージ", "ボディ", "アロマ", "エンジン", "ミシン", "スキン", "ネイル",
                               "サプリ", "カプセル", "クロス", "ふきん", "汚れ", "洗剤", "ポット"],
                 "kitchensupply": ["ホルダー", "タオル", "ガウン", "ケース", "スタンド", "鉄粉", "除去剤", "洗車"],
                 "kairo": ["ニトリル", "使い捨て手袋", "ゴム手袋", "ビニール手袋", "作業"],
                 "laundry": ["ラック", "収納", "ネクタイ"],
                 "daily": ["ケース", "カバー", "ホルダー"], "detergent": ["詰め替えボトル", "ディスペンサー", "空ボトル"],
                 "kitchen": ["切身", "サバ", "鮭", "肉"],
                 "kaden": ["お椀", "汁椀", "食器", "ラック", "ゆで卵", "容器", "保存", "皿", "カバー", "マット"],
                 "car": ["自転車", "保護マット"], "roomwear": ["甚平", "夏用", "父の日"],
                 "bicycle": ["カバー", "レインコート", "ポンチョ"], "clothcare": ["ヘアアイロン", "ヘア"],
                 "battery": ["ペンダント", "シーリング", "スタンド", "ライト 北欧"],
                 "heater": ["ソックス", "靴下", "スリッパ"], "towel": ["おむつケーキ"], "toy": ["おむつケーキ"], "phone": ["スーツケース", "キャリー"],
                 "fruit": ["干し芋", "干しいも", "栗"]}


def _name_head(name: str, n: int = 30) -> str:
    """キャンペーン表記（【】など）を除いた商品名の先頭 n 文字。"""
    head = re.sub(r"[【\[［＼][^】\]］／/]*[】\]］／/]", " ", name or "")
    return re.sub(r"\s+", " ", head).strip()[:n]


def _genre_ok(g: dict, it: dict) -> bool:
    name = it.get("itemName", "")
    # 商品名の後ろには検索用の関連語が詰め込まれていることが多いので、
    # キャンペーン表記【】などを除いた先頭30文字で「何の商品か」を判定する
    head = re.sub(r"[【\[［＼\][^】\]］／/]*[】\]］／/]", " ", name)
    head = re.sub(r"\s+", " ", head).strip()[:30]
    must = GENRE_MUST.get(g["slug"])
    if must and not any(w in head for w in must):
        return False
    return not any(w in name for w in GENRE_EXCLUDE.get(g["slug"], []))


# ジャンルが増えてきたので、メニュー・トップ・関連ジャンルは大きなカテゴリでまとめる
CATEGORIES = [
    {"slug": "food", "name": "食品・飲み物", "emoji": "🍙",
     "genres": ["coffee", "water", "rice", "seasoning", "frozen", "instant", "meat", "fruit", "alcohol", "osechi"]},
    {"slug": "daily", "name": "日用品・消耗品", "emoji": "🧻",
     "genres": ["daily", "kitchensupply", "cleaning", "detergent", "laundry", "towel", "battery", "stationery", "baby", "contact", "pet"]},
    {"slug": "appliance", "name": "家電・ガジェット", "emoji": "🔌",
     "genres": ["heater", "cleaner", "kaden", "clothcare", "phone", "pcgear", "ink"]},
    {"slug": "home", "name": "住まい・インテリア", "emoji": "🛋️",
     "genres": ["sleep", "kitchen", "nabe", "tableware", "bottle", "interior", "lighting", "desk", "storage", "roomwear"]},
    {"slug": "fashion", "name": "ファッション・美容", "emoji": "👗",
     "genres": ["outer", "inner", "bag", "wallet", "watch", "sneaker", "hairtool", "kidswear"]},
    {"slug": "season", "name": "レジャー・季節・ギフト", "emoji": "🎁",
     "genres": ["xmas", "outdoor", "bicycle", "cyclegear", "kidsbike", "bousai", "kairo", "toy", "randoseru", "car", "techo", "gift"]},
]
_assigned = [s for c in CATEGORIES for s in c["genres"]]
assert sorted(_assigned) == sorted(g["slug"] for g in GENRES), "カテゴリに入っていないジャンルがある"
CAT_OF = {s: c for c in CATEGORIES for s in c["genres"]}


def _cat_genres(c: dict) -> list[dict]:
    return [GENRE_BY_SLUG[s] for s in c["genres"]]


# グローバルメニュー用の短い表記（15ジャンルを1〜2行に収めるため）
NAV_SHORT = {"coffee": "コーヒー・お茶", "sleep": "寝具", "kitchen": "キッチン", "pet": "ペット", "water": "水・飲料",
             "rice": "お米・食品", "contact": "コンタクト", "baby": "ベビー", "daily": "日用品", "detergent": "洗剤・掃除",
             "alcohol": "お酒", "bousai": "防災", "instant": "インスタント・お菓子", "interior": "インテリア",
             "outdoor": "アウトドア", "heater": "暖房・加湿", "cleaner": "掃除機", "towel": "タオル",
             "toy": "おもちゃ", "osechi": "おせち", "meat": "肉・海鮮", "fruit": "果物", "phone": "スマホ周辺",
             "pcgear": "PC周辺", "gift": "ギフト", "kaden": "調理家電", "car": "カー用品",
             "randoseru": "ランドセル", "roomwear": "ルームウェア", "techo": "手帳", "bicycle": "自転車",
             "battery": "電池・電球", "clothcare": "衣類ケア", "kitchensupply": "キッチン消耗品",
             "kairo": "カイロ・防寒", "laundry": "洗濯グッズ", "stationery": "文房具",
             "cleaning": "掃除用品", "ink": "プリンターインク", "xmas": "クリスマス", "storage": "衣替え・圧縮袋",
             "seasoning": "調味料・油", "nabe": "鍋・土鍋", "frozen": "冷凍食品", "tableware": "食器",
             "bottle": "水筒・タンブラー", "inner": "インナー・タイツ", "hairtool": "ヘアアイロン・ドライヤー",
             "bag": "バッグ", "sneaker": "スニーカー", "outer": "冬アウター", "kidswear": "子供服",
             "cyclegear": "自転車用品", "wallet": "財布", "watch": "腕時計", "lighting": "照明", "desk": "デスク・チェア",
             "kidsbike": "子ども用自転車"}
GA4_ID = "G-MJGWNG8KND"
GA4_TAG = f"""<script async src="https://www.googletagmanager.com/gtag/js?id={GA4_ID}"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}
gtag('js',new Date());gtag('config','{GA4_ID}');
document.addEventListener('click',function(e){{var a=e.target.closest('a[rel~="sponsored"]');if(!a)return;
var h=a.hostname,net=/a8\\.net/.test(h)?'a8':(/rakuten/.test(h)?'rakuten':(/valuecommerce/.test(h)?'vc':(/yahoo/.test(h)?'yahoo':'other')));
var it=a.closest('.item');var n=it?it.querySelector('.item-name'):null;
gtag('event','affiliate_click',{{network:net,link_text:(n?n.textContent:a.textContent).trim().slice(0,90),
page_path:location.pathname,section:(a.closest('section')||{{}}).id||''}});}});</script>"""
# Yahoo!ショッピングは、バリューコマースでサイトが承認されて LinkSwitch の vc_pid を .env の
# VC_LINKSWITCH_PID に入れた時だけ表示する（それまでは素のリンクになり報酬が付かないため）。
# LinkSwitchタグがページ内の素のYahoo!ショッピングURLを自動でアフィリエイトリンクに変える。
def yahoo_enabled() -> bool:
    return bool(os.environ.get("VC_LINKSWITCH_PID")) or os.environ.get("SITE_YAHOO_PREVIEW") == "1"


def _linkswitch_tag() -> str:
    pid = os.environ.get("VC_LINKSWITCH_PID", "")
    if not pid:
        return ""
    return (f'<script>var vc_pid = "{E(pid)}";</script>'
            '<script src="//aml.valuecommerce.com/vcdal.js" async></script>')


YAHOO_CREDIT = ('<p><!-- Begin Yahoo! JAPAN Web Services Attribution Snippet -->'
                '<a href="https://developer.yahoo.co.jp/sitemap/" target="_blank" rel="noopener">Webサービス by Yahoo! JAPAN</a>'
                '<!-- End Yahoo! JAPAN Web Services Attribution Snippet --></p>')
AUTHOR = {"@type": "Person", "name": "aki.h190", "url": f"{SITE_URL}/about/",
          "sameAs": ["https://www.instagram.com/aki.h190/", "https://www.threads.net/@aki.h190"]}
PUBLISHER = {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL,
             "logo": {"@type": "ImageObject", "url": f"{SITE_URL}/img/icon-512.png"}}


def _short_name(name: str, n: int = 52) -> str:
    name = re.sub(r"[【\[［(（][^】\]］)）]{0,40}[】\]］)）]", " ", name)  # 宣伝用のカッコ書きを除く
    name = re.sub(r"[＼\\／/★☆◆◇■□●○※!！]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:n] + ("…" if len(name) > n else "")


def _yen(n: int) -> str:
    return f"{n:,}円"


def _sparkline(rows: list[dict]) -> str:
    if len(rows) < 2:
        return '<span class="muted">価格記録 1日目</span>'
    prices = [r["price"] for r in rows][-60:]
    lo, hi = min(prices), max(prices)
    w, h = 132, 34
    span = (hi - lo) or 1
    pts = [(i * w / (len(prices) - 1), h - 4 - (p - lo) * (h - 8) / span) for i, p in enumerate(prices)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"0,{h} " + line + f" {w},{h}"
    lx, ly = pts[-1]
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="直近{len(prices)}日の価格推移。最安{lo:,}円、最高{hi:,}円">'
            f'<polygon points="{area}" class="spark-area"/>'
            f'<polyline points="{line}" class="spark-line"/>'
            f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3" class="spark-dot"/></svg>')


def _buy_url(it: dict) -> str:
    return it.get("affiliateUrl") or it["itemUrl"]


def _item_card(rank: int, it: dict, mode: str) -> str:
    url = E(_buy_url(it))
    medal = {1: "gold", 2: "silver", 3: "bronze"}.get(rank, "")
    badges = []
    if it.get("is_all_time_low") and it["days"] >= 7:
        badges.append('<span class="badge badge-low">記録上の最安値</span>')
    if mode == "drop":
        badges.append(f'<span class="badge badge-drop">{it["drop_pct"]:.0f}%値下がり</span>')
    stars = f'<span class="stars">★{it["reviewAverage"]:.2f}</span><span class="muted">（{it["reviewCount"]:,}件）</span>'
    was = (f'<s class="was">{_yen(it["reference_price"])}</s>'
           if mode == "drop" and it["reference_price"] > it["price"] else "")
    rng = (f'<span class="muted">記録{it["days"]}日・最安{_yen(it["low"])}・最高{_yen(it["high"])}</span>'
           if it["days"] >= 2 else "")
    img = (f'<img src="{E(it["imageUrl"])}" alt="{E(_short_name(it["itemName"], 40))}" '
           f'loading="lazy" decoding="async" width="112" height="112">'
           if it.get("imageUrl") else '<div class="noimg"></div>')
    is_yahoo = it.get("mall") == "yahoo"
    buttons = (f'<a class="btn-buy btn-yahoo" href="{url}" rel="nofollow sponsored noopener" target="_blank">Yahoo!で見る</a>'
               if is_yahoo else
               f'<a class="btn-buy" href="{url}" rel="nofollow sponsored noopener" target="_blank">楽天で見る</a>')
    if not is_yahoo and yahoo_enabled():
        q = E(quote(_short_name(it["itemName"], 40).rstrip("…")))
        buttons += (f'<a class="btn-sub" href="https://shopping.yahoo.co.jp/search?p={q}" '
                    f'rel="nofollow sponsored noopener" target="_blank">Yahoo!で探す</a>')
    return f"""
<li class="item" id="{mode}-{rank}">
  <div class="rank {medal}">{rank}</div>
  <a class="thumb" href="{url}" rel="nofollow sponsored noopener" target="_blank">{img}</a>
  <div class="item-body">
    <h3 class="item-name"><a href="{url}" rel="nofollow sponsored noopener" target="_blank">{E(_short_name(it["itemName"]))}</a></h3>
    <div class="badges">{"".join(badges)}</div>
    <div class="price-row"><span class="price">{it["price"]:,}<small>円</small></span>{was}</div>
    <div class="rating">{stars}</div>
    <div class="trend">{_sparkline(it["history"])}{rng}</div>
    <div class="item-foot"><span class="muted shop">{E(it.get("shopName", ""))}</span>
      <span class="btns">{buttons}</span></div>
  </div>
</li>"""


VC_LINKS_FILE = Path(__file__).resolve().parent.parent / "data" / "vc_links.yaml"


def _a8_links(genre: dict) -> list[dict]:
    """ジャンルの「おすすめのサービス」に出す案件（A8＋バリューコマース）。"""
    out = []
    try:
        from .a8_selector import load_links
        out += [l for l in load_links() if l.get("genre") in genre["a8_genres"]]
    except Exception:  # noqa: BLE001
        pass
    try:
        import yaml
        vc = yaml.safe_load(VC_LINKS_FILE.read_text(encoding="utf-8")) or []
        out += [l for l in vc if genre["slug"] in (l.get("site_genres") or [])]
    except Exception:  # noqa: BLE001
        pass
    return out


def _svc_name(name: str, n: int = 60) -> str:
    """A8の案件名は【】内がブランド名のことが多いので、括弧だけ外して中身は残す。"""
    name = re.sub(r"[【】\[\]「」]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:n] + ("…" if len(name) > n else "")


def _svc_card(l: dict) -> str:
    """サービス1件のカード。買い時ナビ用のバナー素材(site_banner)があれば画像つきで出す。"""
    bn = l.get("site_banner") or {}
    url = E(bn.get("href") or l["url"])
    rel = 'rel="nofollow sponsored noopener" target="_blank"'
    banner = ""
    if bn.get("img"):
        banner = (f'<a class="svc-banner" href="{url}" {rel}><img src="{E(bn["img"])}" width="{bn.get("width", 300)}" '
                  f'height="{bn.get("height", 250)}" alt="{E(_svc_name(l["program_name"], 40))}" loading="lazy"></a>')
        if bn.get("pixel"):  # A8は計測用の1px画像が別。バリューコマースはバナー画像自体が計測を兼ねる
            banner += f'<img class="px" src="{E(bn["pixel"])}" width="1" height="1" alt="">'
    return (f'<li class="svc">{banner}<div class="svc-body"><b>{E(l.get("site_name") or _svc_name(l["program_name"]))}</b>'
            f'<span>{E((l.get("site_note") or l.get("note", ""))[:80])}</span></div>'
            f'<a class="btn-svc" href="{url}" {rel}>公式サイトを見る</a></li>')


def _a8_box(genre: dict) -> str:
    links = _a8_links(genre)
    if not links:
        return ""
    # 多すぎると選べないので4件まで。A8（ジャンルに合わせて登録した案件）を先に、残りは日替わりで入れ替える
    if len(links) > 4:
        a8 = [l for l in links if l.get("asp") != "valuecommerce"]
        vc = [l for l in links if l.get("asp") == "valuecommerce"]
        random.Random(date.today().isoformat() + genre["slug"]).shuffle(vc)
        links = (a8 + vc)[:4]
    cards = "".join(_svc_card(l) for l in links)
    return f"""
<section class="services" id="services" aria-labelledby="h-services">
  <div class="services-head"><span class="pr">PR</span>
  <h2 id="h-services">{E(genre["name"])}を探している人におすすめのサービス</h2></div>
  <p class="basis">楽天市場以外で、このジャンルの買い物に使える公式ショップや定期便・お試しセットなどです。</p>
  <ul class="svc-list">{cards}</ul>
</section>"""


def _guides(slug: str) -> list[dict]:
    out = []
    d = GUIDES_DIR / slug
    if not d.exists():
        return out
    for p in sorted(d.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        lines = text.splitlines()
        title = lines[0].lstrip("# ").strip() if lines else p.stem
        desc = next((l.strip() for l in lines[1:] if l.strip() and not l.startswith("#")), title)
        out.append({"slug": p.stem, "title": title, "desc": desc[:110], "md": text,
                    "updated": datetime.fromtimestamp(p.stat().st_mtime).date().isoformat()})
    return out


GUIDE_DATES = DATA_DIR / "guide_dates.json"
_guide_dates_cache: dict | None = None


def _guide_published(genre: str, slug: str, updated: str) -> str:
    """ガイドの公開日（初めてサイトに出した日）を記録して固定する。ファイルの更新日は毎回変わりうるため。"""
    global _guide_dates_cache
    if _guide_dates_cache is None:
        try:
            _guide_dates_cache = json.loads(GUIDE_DATES.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            _guide_dates_cache = {}
    key = f"{genre}/{slug}"
    if key not in _guide_dates_cache:
        _guide_dates_cache[key] = min(updated, date.today().isoformat())
        GUIDE_DATES.write_text(json.dumps(_guide_dates_cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return _guide_dates_cache[key]


def _guide_answer(md: str) -> str:
    """ガイド冒頭の「> 」で始まる要約（結論）を取り出す。AIや検索の要約に使われやすい形。"""
    lines = [l[1:].strip() for l in md.splitlines() if l.startswith(">")]
    return re.sub(r"\*\*|\[([^\]]+)\]\([^)]+\)", lambda m: m.group(1) or "", " ".join(lines)).strip()


def _md_to_html(md: str) -> tuple[str, list[tuple[str, str]]]:
    """見出し・段落・箇条書き・表・太字・リンクの最小限Markdown変換。(html, 目次) を返す。"""
    out, toc, in_list, table = [], [], False, []

    def flush_table() -> None:
        if not table:
            return
        rows = [r for r in table if not re.fullmatch(r"\|?[\s:\-|]+\|?", r)]
        cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
        head = "".join(f"<th>{_inline(c)}</th>" for c in cells[0])
        body = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in cells[1:])
        out.append(f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
        table.clear()

    for line in md.splitlines()[1:]:  # 1行目はタイトル
        s = line.rstrip()
        if s.startswith("|"):
            table.append(s); continue
        flush_table()
        if s.startswith("- "):
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append(f"<li>{_inline(s[2:])}</li>"); continue
        if in_list:
            out.append("</ul>"); in_list = False
        if s.startswith("### "):
            out.append(f"<h3>{_inline(s[4:])}</h3>")
        elif s.startswith("## "):
            hid = f"s{len(toc) + 1}"
            toc.append((hid, s[3:]))
            out.append(f'<h2 id="{hid}">{_inline(s[3:])}</h2>')
        elif s.startswith("> "):
            out.append(f'<p class="point">{_inline(s[2:])}</p>')
        elif s:
            out.append(f"<p>{_inline(s)}</p>")
    flush_table()
    if in_list:
        out.append("</ul>")
    return "\n".join(out), toc


def _inline(s: str) -> str:
    s = E(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"\[(.+?)\]\((https?://[^)\s]+|/[^)\s]*)\)",
                  lambda m: (f'<a href="{m.group(2)}">{m.group(1)}</a>' if m.group(2).startswith("/") else
                             f'<a href="{m.group(2)}" rel="nofollow sponsored noopener" target="_blank">{m.group(1)}</a>'), s)


def _jsonld(*objs: dict) -> str:
    return "".join(f'<script type="application/ld+json">{json.dumps(o, ensure_ascii=False)}</script>'
                   for o in objs if o)


def _breadcrumb(items: list[tuple[str, str]]) -> tuple[str, dict]:
    """[(名前, パス), ...] → (HTML, JSON-LD)"""
    html_ = '<nav class="crumbs" aria-label="パンくずリスト"><ol>' + "".join(
        (f'<li><a href="{p}">{E(n)}</a></li>' if i < len(items) - 1 else f'<li aria-current="page">{E(n)}</li>')
        for i, (n, p) in enumerate(items)) + "</ol></nav>"
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": f"{SITE_URL}{p}"}
        for i, (n, p) in enumerate(items)]}
    return html_, ld


def _itemlist_ld(name: str, items: list[dict], path: str) -> dict:
    if not items:
        return {}
    return {"@context": "https://schema.org", "@type": "ItemList", "name": name,
            "url": f"{SITE_URL}{path}", "numberOfItems": len(items),
            "itemListElement": [
                # 比較サイトの一覧なので Product（販売ページ向け）ではなく、順位・名前・リンク先だけを示す。
                # Product にすると「aggregateRating / review がない」と指摘されるが、楽天のレビューを
                # 構造化データに入れるのはGoogleのガイドライン違反（他サイトの評価の転載）になるため
                {"@type": "ListItem", "position": i + 1, "name": _short_name(it["itemName"], 120),
                 "url": it["itemUrl"], **({"image": it["imageUrl"]} if it.get("imageUrl") else {})}
                for i, it in enumerate(items)]}


def _faq(qas: list[tuple[str, str]]) -> tuple[str, dict]:
    html_ = ('<section class="section" id="faq" aria-labelledby="h-faq"><h2 id="h-faq">よくある質問</h2>'
             + "".join(f'<details class="qa"><summary>{E(q)}</summary><p>{E(a)}</p></details>' for q, a in qas)
             + "</section>")
    ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in qas]}
    return html_, ld


# ---------------------------------------------------------------- デザイン
CSS = """
:root{--bg:#f7f3ec;--surface:#fff;--ink:#28231d;--sub:#6f655a;--muted:#958a7d;--line:#e9e0d3;
--brand:#b8562f;--brand-dark:#93421f;--brand-soft:#fbeee6;--green:#2c7a67;--green-soft:#e5f2ee;
--gold:#c9a227;--silver:#9aa3ab;--bronze:#b07a4f;--radius:18px;--shadow:0 1px 2px rgba(40,35,29,.04),0 6px 24px rgba(40,35,29,.06)}
*{box-sizing:border-box}
html{scroll-behavior:smooth;-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.75;font-size:16px;
font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP","Yu Gothic UI",Meiryo,system-ui,sans-serif;
font-feature-settings:"palt" 1}
a{color:inherit}
img{max-width:100%;display:block}
.wrap{width:100%;max-width:1000px;margin:0 auto;padding:0 18px}
.muted{color:var(--muted);font-size:13px}
.prbar{background:#2d2822;color:#e9e0d3;font-size:12px;text-align:center;padding:5px 12px}
.site-header{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.88);
backdrop-filter:saturate(1.4) blur(10px);-webkit-backdrop-filter:saturate(1.4) blur(10px);border-bottom:1px solid var(--line)}
.site-header .hrow{display:flex;align-items:center;gap:16px;min-height:58px}
.site-header .hnav{padding-bottom:6px}
.sbox{margin-left:auto;display:flex;align-items:center;flex:0 1 380px;background:#f4efe8;border:1px solid var(--line);
border-radius:999px;padding:0 6px 0 14px}
.sbox input{flex:1;min-width:0;border:0;background:transparent;font:inherit;font-size:15px;padding:9px 0;outline:none;color:var(--ink)}
.sbox button{border:0;background:var(--brand);color:#fff;border-radius:999px;padding:6px 14px;font:inherit;font-size:14px;font-weight:700;cursor:pointer}
.sbox:focus-within{border-color:var(--brand);background:#fff}
.logo{display:flex;align-items:center;gap:8px;font-weight:800;font-size:19px;text-decoration:none;white-space:nowrap}
.logo svg{flex:none}
.logo em{font-style:normal;color:var(--brand)}
.gnav{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none}
.gnav::-webkit-scrollbar{display:none}
.gnav a{white-space:nowrap;font-size:14px;font-weight:600;text-decoration:none;padding:6px 11px;border-radius:999px;color:var(--sub)}
@media (min-width:761px){.gnav{flex-wrap:wrap;overflow:visible;row-gap:2px}}
@media (max-width:760px){.site-header .hnav{position:relative}
.site-header .hnav::after{content:"";position:absolute;right:0;top:0;bottom:6px;width:36px;pointer-events:none;
background:linear-gradient(90deg,rgba(255,255,255,0),#fff)}}
.gnav a:hover,.gnav a[aria-current]{background:var(--brand-soft);color:var(--brand-dark)}
/* hero */
.hero{position:relative;color:#fff;background:#3a2e24 center/cover no-repeat;isolation:isolate}
.hero::before{content:"";position:absolute;inset:0;z-index:-1;
background:linear-gradient(100deg,rgba(28,20,14,.86) 0%,rgba(28,20,14,.62) 45%,rgba(28,20,14,.15) 100%)}
.hero .wrap{padding-top:64px;padding-bottom:56px}
.hero h1{font-size:clamp(28px,5vw,44px);line-height:1.3;margin:0 0 14px;letter-spacing:.01em}
.hero p{max-width:560px;margin:0 0 22px;color:#f1e9df;font-size:clamp(15px,2.2vw,17px)}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.28);border-radius:999px;padding:5px 13px;font-size:13px}
.chip b{font-size:15px;margin-right:2px}
.banner{position:relative;color:#fff;background:#3a2e24 center/cover no-repeat;isolation:isolate}
.banner::before{content:"";position:absolute;inset:0;z-index:-1;background:linear-gradient(0deg,rgba(28,20,14,.82),rgba(28,20,14,.35))}
.banner .wrap{padding-top:52px;padding-bottom:60px}
.banner h1{font-size:clamp(25px,4.4vw,36px);line-height:1.35;margin:6px 0 6px}
.banner p{margin:0;color:#f1e9df}
.crumbs ol{list-style:none;display:flex;flex-wrap:wrap;gap:4px;margin:0;padding:0;font-size:12px;opacity:.9}
.crumbs li+li::before{content:"›";margin-right:4px}
.crumbs a{text-decoration:none}
main{padding-bottom:40px}
/* summary (AIO) */
.summary{background:var(--surface);border:1px solid var(--line);border-left:5px solid var(--green);
border-radius:var(--radius);padding:18px 20px;margin:-22px 0 8px;position:relative;box-shadow:var(--shadow)}
.summary h2{font-size:15px;margin:0 0 6px;color:var(--green)}
.summary p{margin:0}
.summary ul{margin:8px 0 0;padding-left:20px}
.summary .stamp{display:block;margin-top:8px}
.toc-pills{display:flex;gap:8px;overflow-x:auto;padding:10px 0;scrollbar-width:none;position:sticky;
top:var(--hdr-h,108px);z-index:15;background:var(--bg);margin:0 -18px;padding-left:18px;padding-right:18px}
.toc-pills a.on{background:var(--brand);border-color:var(--brand);color:#fff}
section[id],h2[id],.item[id]{scroll-margin-top:calc(var(--hdr-h,108px) + 64px)}
.notice{margin:16px 0 0;padding:10px 14px;border-radius:10px;background:#fff4e5;border:1px solid #f3cf9a;font-size:14px;font-weight:600}
.totop{position:fixed;right:16px;bottom:calc(16px + env(safe-area-inset-bottom,0px));z-index:30;width:46px;height:46px;border-radius:50%;
border:0;background:var(--ink);color:#fff;font-size:20px;box-shadow:0 6px 18px rgba(0,0,0,.2);cursor:pointer;opacity:0;pointer-events:none;transition:opacity .2s}
.totop.show{opacity:.9;pointer-events:auto}
.related .gcards{grid-template-columns:repeat(auto-fill,minmax(160px,1fr))}
.related .gcard div{padding:10px 12px}.related .gcard b{font-size:15px}
.related .gcard div>span:not(.tag){display:none}
.related .gcard img{aspect-ratio:16/8}
.sresult{display:grid;gap:10px;list-style:none;margin:0;padding:0}
.sresult a{display:flex;gap:12px;align-items:center;background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:10px 12px;text-decoration:none}
.sresult img{width:64px;height:64px;object-fit:contain;border-radius:8px;background:#faf7f2;flex:none}
.sresult b{display:block;font-size:14px;line-height:1.5}.sresult small{color:var(--muted)}
.toc-pills a{white-space:nowrap;text-decoration:none;font-size:14px;font-weight:600;background:var(--surface);
border:1px solid var(--line);border-radius:999px;padding:7px 14px}
.toc-pills a:hover{border-color:var(--brand);color:var(--brand)}
.section{margin:28px 0}
.section>h2{font-size:clamp(20px,3vw,24px);margin:0 0 4px;line-height:1.4}
.basis{font-size:13px;color:var(--sub);margin:0 0 12px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);overflow:hidden}
/* ranking items */
ol.items{list-style:none;margin:0;padding:0}
.item{display:grid;grid-template-columns:34px 112px 1fr;gap:14px;padding:18px;border-top:1px solid var(--line);align-items:start}
.item:first-child{border-top:0}
.rank{width:34px;height:34px;border-radius:50%;display:grid;place-items:center;font-weight:800;
background:#f1ebe2;color:var(--sub);font-size:15px}
.rank.gold{background:var(--gold);color:#fff}.rank.silver{background:var(--silver);color:#fff}.rank.bronze{background:var(--bronze);color:#fff}
.thumb img,.noimg{width:112px;height:112px;object-fit:contain;border-radius:12px;background:#faf7f2;border:1px solid var(--line)}
.item-name{font-size:15px;line-height:1.5;margin:0 0 4px}
.item-name a{text-decoration:none}.item-name a:hover{color:var(--brand)}
.badges{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:2px}
.badge{font-size:11px;font-weight:700;border-radius:6px;padding:2px 8px}
.badge-low{background:var(--green-soft);color:var(--green)}.badge-drop{background:var(--brand-soft);color:var(--brand-dark)}
.price-row{display:flex;align-items:baseline;gap:10px}
.price{font-size:22px;font-weight:800;letter-spacing:.01em}
.price small{font-size:13px;margin-left:1px}
.was{color:var(--muted);font-size:13px}
.stars{color:#c98a12;font-weight:700;font-size:14px;margin-right:2px}
.trend{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:4px 0}
.spark{color:var(--green)}.spark-line{fill:none;stroke:var(--green);stroke-width:2;stroke-linejoin:round}
.spark-area{fill:var(--green-soft)}.spark-dot{fill:var(--green)}
.item-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:6px}
.shop{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.btn-buy{flex:none;background:var(--brand);color:#fff;text-decoration:none;font-weight:700;font-size:14px;
padding:9px 18px;border-radius:999px;transition:background .15s}
.btn-buy:hover{background:var(--brand-dark)}
.btns{display:flex;gap:8px;flex:none;flex-wrap:wrap;justify-content:flex-end}
.btn-yahoo{background:#d92d20}.btn-yahoo:hover{background:#b0241a}
.btn-sub{flex:none;text-decoration:none;font-weight:700;font-size:14px;padding:8px 16px;border-radius:999px;
border:1.5px solid #d92d20;color:#d92d20;background:#fff}
.btn-sub:hover{background:#fdf0ef}
.mall-tag{display:inline-block;font-size:11px;font-weight:700;color:#d92d20;border:1px solid #d92d20;border-radius:4px;padding:0 5px;margin-left:6px;vertical-align:middle}
.empty{padding:22px;color:var(--sub);text-align:center}
/* compare table */
.table-wrap{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius)}
table{width:100%;border-collapse:collapse;font-size:14px;min-width:560px}
th,td{padding:11px 14px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:#faf6f0;font-size:13px;color:var(--sub);white-space:nowrap}
tr:last-child td{border-bottom:0}
td.num{text-align:right;white-space:nowrap}
/* genre cards */
.gcards{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}
.gcard{display:block;text-decoration:none;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
overflow:hidden;box-shadow:var(--shadow);transition:transform .15s,box-shadow .15s}
.gcard:hover{transform:translateY(-3px);box-shadow:0 10px 30px rgba(40,35,29,.12)}
.gcard img{aspect-ratio:16/9;object-fit:cover;width:100%;height:auto}
.gcard div{padding:14px 16px 16px}
.gcard b{display:block;font-size:17px}
.gcard span{font-size:13px;color:var(--sub)}
.gcard .tag{display:inline-block;margin-top:8px;font-size:12px;font-weight:700;color:var(--brand-dark);background:var(--brand-soft);
border-radius:6px;padding:1px 8px}
/* services, guides, faq */
.services{margin:28px 0;background:linear-gradient(135deg,#fff6ef 0%,#fdebdf 100%);border:2px solid #f0c9b0;
border-radius:var(--radius);padding:20px clamp(14px,3vw,24px);box-shadow:var(--shadow)}
.services-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.services h2{font-size:clamp(18px,2.6vw,22px);margin:0;line-height:1.4}
.svc-list{list-style:none;margin:10px 0 0;padding:0;display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.svc{background:#fff;border-radius:14px;padding:16px;display:flex;flex-direction:column;gap:12px;justify-content:space-between;
border:1px solid #f0d7c6}
.svc b{display:block;font-size:16px;line-height:1.45}
.svc-banner{display:block;text-align:center;line-height:0}
.svc-banner img{max-width:100%;height:auto;border-radius:10px}
.svc .px{position:absolute;width:1px;height:1px;opacity:0}
.svc span{display:block;font-size:13px;color:var(--sub);margin-top:4px}
.btn-svc{display:block;text-align:center;background:var(--green);color:#fff;text-decoration:none;font-weight:700;
padding:11px 16px;border-radius:999px}
.btn-svc:hover{background:#225f50}
.service-list,.guide-list{list-style:none;margin:0;padding:0;display:grid;gap:10px}
.service-list a,.guide-list a{display:block;text-decoration:none;background:var(--surface);border:1px solid var(--line);
border-radius:14px;padding:14px 16px}
.service-list a:hover,.guide-list a:hover{border-color:var(--brand)}
.service-list b,.guide-list b{display:block}
.service-list span,.guide-list span{display:block;font-size:13px;color:var(--sub)}
.pr{display:inline-block;font-size:11px;border:1px solid var(--muted);color:var(--muted);border-radius:4px;padding:0 5px;
vertical-align:middle;font-weight:600}
.qa{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:0 16px;margin-bottom:10px}
.qa summary{cursor:pointer;font-weight:700;padding:14px 0;list-style:none}
.qa summary::before{content:"Q. ";color:var(--brand)}
.qa summary::-webkit-details-marker{display:none}
.qa p{margin:0 0 14px;color:var(--sub)}
/* article */
.article{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:clamp(18px,4vw,36px);box-shadow:var(--shadow)}
.article h2{font-size:21px;margin:34px 0 10px;padding-left:12px;border-left:4px solid var(--brand);line-height:1.45}
.article h3{font-size:17px;margin:24px 0 6px}
.article table{min-width:0}
.article .table-wrap{margin:12px 0}
.article .point{background:var(--green-soft);border-radius:12px;padding:12px 16px}
.toc{background:#faf6f0;border-radius:12px;padding:14px 18px;margin:16px 0}
.toc b{font-size:14px}.toc ol{margin:6px 0 0;padding-left:20px;font-size:14px}
.byline{display:flex;gap:12px;flex-wrap:wrap;color:var(--muted);font-size:13px;margin-bottom:10px}
/* footer */
.site-footer{background:#2d2822;color:#cfc4b6;font-size:13px;padding:36px 0 28px;margin-top:40px}
.site-footer a{color:#f1e9df}
.fcols{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px;margin-bottom:18px}
.fcols b{color:#fff;display:block;margin-bottom:6px}
.fcols ul{list-style:none;margin:0;padding:0;line-height:2}
.fcols a{text-decoration:none}

/* ---- 2026-10-06 リデザイン: 強弱をつける ---- */
.eyebrow{margin:0 0 2px;font-size:12px;font-weight:800;letter-spacing:.14em;color:var(--brand)}
.section>h2 .count{display:inline-block;margin-left:10px;font-size:13px;font-weight:700;color:var(--brand-dark);
background:var(--brand-soft);border-radius:999px;padding:2px 10px;vertical-align:middle}
.section.feature{background:linear-gradient(180deg,#fff 0%,#fff8f2 100%);border:1px solid var(--line);border-radius:24px;
padding:22px 20px 24px;box-shadow:var(--shadow)}
.podium{list-style:none;margin:14px 0 0;padding:0;display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.item.big{display:flex;flex-direction:column;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
padding:16px;box-shadow:var(--shadow);position:relative}
.item.big:first-child{border:2px solid var(--gold)}
.picks .item.big:first-child{border:2px solid var(--brand)}
.big-head{display:flex;align-items:center;gap:8px;min-height:34px}
.big-head .badges{margin:0}
.chip-label{font-size:13px;font-weight:800;color:#fff;background:var(--brand);border-radius:999px;padding:4px 12px}
.picks .item.big:nth-child(2) .chip-label{background:var(--green)}
.picks .item.big:nth-child(3) .chip-label{background:#5a6b8c}
.big-img{display:block;margin:10px 0 12px}
.big-img img,.big-img .noimg{width:100%;height:auto;aspect-ratio:1/1;object-fit:contain;background:#faf7f2;border-radius:14px}
.item.big .item-name{font-size:15px;line-height:1.5;margin:0 0 6px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.item.big .price{font-size:26px}
.item.big .trend{min-height:8px}
.item.big .btns{margin-top:auto;display:flex;flex-direction:column;flex-wrap:nowrap;align-items:stretch;gap:8px;padding-top:10px;width:100%}
.item.big .btn-buy,.item.big .btn-sub{text-align:center;display:block}
.rows{list-style:none;margin:14px 0 0;padding:0;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden}
.item.row{display:grid;grid-template-columns:30px 64px 1fr auto;gap:12px;align-items:center;padding:12px 14px;border-top:1px solid var(--line)}
.item.row:first-child{border-top:0}
.item.row .rank{width:28px;height:28px;font-size:13px;background:#f1ebe2;color:var(--sub)}
.row-img img,.row-img .noimg{width:64px;height:64px;object-fit:contain;border-radius:10px;background:#faf7f2}
.item.row .item-name{font-size:14px;margin:0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.row-meta{font-size:13px}
.row-side{display:flex;align-items:center;gap:10px;justify-content:flex-end}
.row-side .price{font-size:18px}
.btn-buy.sm{padding:7px 16px;font-size:13px}
.item.row .btn-buy.sm{flex:none !important;width:auto}
.hscroll{list-style:none;margin:14px -18px 0;padding:4px 18px 14px;display:flex;gap:12px;overflow-x:auto;scroll-snap-type:x mandatory;scrollbar-width:thin}
.item.mini{display:block;flex:0 0 180px;scroll-snap-align:start;background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:10px;box-shadow:var(--shadow)}
.mini-img{display:block;position:relative}
.mini-img img,.mini-img .noimg{width:100%;height:auto;aspect-ratio:1/1;object-fit:contain;background:#faf7f2;border-radius:12px}
.mini-img .badge{position:absolute;left:6px;top:6px;font-size:12px;background:var(--brand);color:#fff}
.item.mini .item-name{font-size:13px;line-height:1.45;margin:8px 0 4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.item.mini .price{font-size:18px}
.tabs{display:flex;gap:6px;margin:12px 0 0;border-bottom:2px solid var(--line)}
.tab{border:0;background:none;font:inherit;font-weight:700;font-size:15px;color:var(--sub);padding:10px 16px;cursor:pointer;
border-bottom:3px solid transparent;margin-bottom:-2px}
.tab.on{color:var(--brand);border-bottom-color:var(--brand)}
.compare-box{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:4px 16px}
.compare-box summary{cursor:pointer;padding:12px 0;list-style:none}
.compare-box summary::-webkit-details-marker{display:none}
.compare-box summary::after{content:"＋";float:right;color:var(--brand);font-weight:800}
.compare-box[open] summary::after{content:"－"}
.h2like{font-size:17px;font-weight:800}
.guide-cards{list-style:none;margin:14px 0 0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.guide-cards a{display:flex;flex-direction:column;height:100%;text-decoration:none;background:var(--surface);border:1px solid var(--line);
border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow);transition:transform .15s}
.guide-cards a:hover{transform:translateY(-3px)}
.g-cover{position:relative;display:block;aspect-ratio:16/8;overflow:hidden;color:var(--ci);
background:radial-gradient(circle at 85% 30%,rgba(255,255,255,.55) 0 18%,transparent 19%),
radial-gradient(circle at 100% 100%,var(--c2) 0 38%,transparent 39%),
radial-gradient(rgba(255,255,255,.5) 1.2px,transparent 1.6px) 0 0/14px 14px,
linear-gradient(135deg,var(--c1),var(--c2))}
.gc-kind{position:absolute;left:16px;top:14px;font-size:11px;font-weight:800;letter-spacing:.12em;padding:3px 10px;border-radius:999px;
background:rgba(255,255,255,.75);color:var(--ci)}
.gc-word{position:absolute;left:16px;bottom:14px;right:32%;font-size:24px;font-weight:900;line-height:1.3;word-break:keep-all;overflow-wrap:anywhere;
letter-spacing:.02em;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.gc-word.m{font-size:20px}.gc-word.s{font-size:17px}
.gc-emoji{position:absolute;right:7%;top:50%;font-size:clamp(46px,6vw,60px);line-height:1;transform:translateY(-50%) rotate(-6deg);
filter:drop-shadow(0 8px 12px rgba(0,0,0,.18));transition:transform .4s var(--ease)}
.guide-cards a:hover .gc-emoji{transform:translateY(-58%) rotate(4deg) scale(1.08)}
.guide-cards .g-tag{margin:12px 16px 0;font-size:12px;font-weight:700;color:var(--brand-dark)}
.guide-cards b{margin:4px 16px 0;font-size:16px;line-height:1.5}
.guide-cards .g-desc{margin:6px 16px 16px;font-size:13px;color:var(--sub);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
@media (max-width:760px){
.podium{grid-template-columns:1fr}
.item.big{display:grid;grid-template-columns:120px 1fr;column-gap:14px;padding:14px}
.item.big .big-head{grid-column:1/-1}
.item.big .big-img{grid-row:2/6;margin:6px 0 0}
.item.big .item-name{-webkit-line-clamp:2;margin-top:6px}
.item.big .price{font-size:22px}
.item.big .btns{grid-column:1/-1;flex-direction:row}
.item.big .btn-buy,.item.big .btn-sub{flex:1}
.item.row{grid-template-columns:26px 56px 1fr;gap:10px}
.row-img img,.row-img .noimg{width:56px;height:56px}
.row-side{grid-column:2/-1;justify-content:space-between}
.section.feature{padding:18px 14px}
}



/* ---- カテゴリのまとめページ ---- */
.catall{margin-left:12px;font-size:13px;font-weight:700;color:var(--brand)}
.cat-h a{text-decoration:none;color:inherit}
.cat-h a span{margin-left:10px;font-size:13px;color:var(--brand);font-weight:700}
.cat-tops{list-style:none;margin:12px 0 0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px}
.cat-tops a{display:flex;flex-direction:column;gap:2px;height:100%;text-decoration:none;background:var(--surface);
border:1px solid var(--line);border-radius:14px;padding:12px 14px}
.cat-tops a:hover{border-color:var(--brand)}
.cat-tops b{font-size:15px}
.cat-tops span{font-size:13px;color:var(--sub)}
.cat-tops em{font-style:normal;font-size:13px;font-weight:700;color:var(--brand-dark)}

/* ---- カテゴリでまとめたメニュー ---- */
.catnav{gap:6px}
.catbtn{white-space:nowrap;border:1px solid var(--line);background:#fff;font:inherit;font-size:14px;font-weight:700;color:var(--sub);
padding:6px 12px;border-radius:999px;cursor:pointer}
.catbtn .caret{font-size:11px;margin-left:4px;color:var(--muted)}
.catbtn:hover,.catbtn[aria-expanded="true"]{border-color:var(--brand);color:var(--brand-dark)}
.catbtn.cur{background:var(--brand-soft);border-color:var(--brand-soft);color:var(--brand-dark)}
.catpanel{position:absolute;left:0;right:0;top:100%;background:#fff;border-top:1px solid var(--line);
box-shadow:0 14px 30px rgba(40,35,29,.14);padding:14px 0 18px;z-index:40}
.catpanel-h{margin:0 0 8px;font-weight:800;font-size:15px}
.catpanel ul{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px}
.catpanel a{display:block;text-decoration:none;padding:10px 14px;border:1px solid var(--line);border-radius:12px;font-weight:700;font-size:14px}
.catpanel a:hover,.catpanel a[aria-current]{border-color:var(--brand);color:var(--brand-dark);background:var(--brand-soft)}
.cat-h{margin:22px 0 10px;font-size:18px}
.chipgroups{margin-top:22px;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px}
.chipgroups-h{margin:0 0 6px;font-weight:800;font-size:14px;color:var(--sub)}
.chipgroup{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:8px 0;border-top:1px dashed var(--line)}
.chipgroup:first-of-type{border-top:0}
.chipgroup b{font-size:13px;margin-right:4px;min-width:150px}
.chipgroup a{font-size:13px;text-decoration:none;border:1px solid var(--line);border-radius:999px;padding:3px 10px;color:var(--sub)}
.chipgroup a:hover{border-color:var(--brand);color:var(--brand-dark)}
.site-footer .fcat{margin-bottom:8px}
.site-footer .fcat b{display:block;font-size:13px;margin-bottom:2px}
.site-footer .fcat a{display:inline-block;margin:0 10px 2px 0;font-size:13px}
@media (max-width:760px){.chipgroup b{min-width:100%}
.catpanel ul{grid-template-columns:1fr 1fr}.catpanel a{padding:9px 10px;font-size:13px}}



/* ---- こんな人には、これ ---- */
.persona .chip-label{white-space:normal;line-height:1.4;font-size:13px}
.why{margin:6px 0 2px;font-size:13px;line-height:1.6;color:var(--ink);background:#fff8ec;border-radius:10px;padding:8px 10px}
.persona{grid-template-columns:repeat(3,1fr)}
@media (max-width:760px){.persona{grid-template-columns:1fr}
.persona .why,.persona .trend{grid-column:1/-1}
.persona.swipe{display:flex;gap:12px;overflow-x:auto;scroll-snap-type:x mandatory;margin:14px -18px 0;padding:4px 18px 14px}
.persona.swipe>li{flex:0 0 86%;scroll-snap-align:start}}

/* ---- 発見（記録データからの事実） ---- */
.discovery ul{list-style:none;margin:12px 0 0;padding:0;display:grid;gap:10px}
.discovery li{position:relative;background:var(--surface);border:1px solid var(--line);border-left:5px solid #e0a43a;
border-radius:14px;padding:12px 16px 12px 44px;line-height:1.7}
.discovery li::before{content:"💡";position:absolute;left:14px;top:12px}

/* ---- 値下がりボード（ページ上部の主役） ---- */
.dropboard{position:relative;margin:-36px 0 8px;padding:22px 20px 18px;border-radius:24px;color:#fff;
background:linear-gradient(135deg,#c2582c 0%,#93421f 100%);box-shadow:0 14px 40px rgba(147,66,31,.28);overflow:hidden}
.dropboard .eyebrow{color:#ffd9c2}
.db-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 14px}
.db-head h2{margin:0;font-size:clamp(20px,3vw,26px);line-height:1.35;width:100%}
.db-stamp{font-size:12px;color:#ffe3d3}
.db-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:14px 0 6px}
.stat{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.18);border-radius:16px;padding:10px 14px}
.stat b{display:block;font-size:clamp(28px,5vw,40px);line-height:1.1;font-weight:800;letter-spacing:.01em}
.stat b small{font-size:15px;margin-left:2px}
.stat span{font-size:13px;color:#ffe3d3}
.stat.hot{background:#fff;color:var(--brand-dark)}
.stat.hot span{color:var(--brand)}
.db-hot{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:10px 0 2px;font-size:13px}
.db-hot>span{color:#ffe3d3;margin-right:2px}
.db-hot a{color:#fff;text-decoration:none;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.25);
border-radius:999px;padding:4px 12px}
.db-hot a b{color:#fff}
.db-lead{margin:10px 0 0;font-size:14px;color:#fff3ec}
.dropboard .hscroll{margin:10px -20px 0;padding:4px 20px 6px}
.dropboard .item.mini{color:var(--ink);border:0}
.dropboard .item.mini .price{color:var(--brand-dark)}
.dropboard ~ .summary{margin:14px 0 8px}
@media (max-width:760px){
.dropboard{margin-top:-24px;padding:18px 14px 14px;border-radius:20px}
.db-stats{gap:6px}
.stat{padding:8px 10px}
.stat span{font-size:11px}
.dropboard .hscroll{margin:10px -14px 0;padding:4px 14px 6px}
}
@media (max-width:560px){
.site-header .hrow{gap:10px;min-height:52px}
.logo span{display:none}
.sbox{flex:1 1 auto}
.item{grid-template-columns:28px 84px 1fr;gap:10px;padding:14px}
.rank{width:28px;height:28px;font-size:13px}
.thumb img,.noimg{width:84px;height:84px}
.item-foot{flex-wrap:wrap}.btns{width:100%}.btn-buy,.btn-sub{flex:1;text-align:center}
}

/* ===== 2026 デザイン調整（色・質感・動き）。見やすさ優先：文字のコントラストは4.5以上を確保 ===== */
:root{--bg:#fbfaf7;--surface:#fff;--ink:#1f1b16;--sub:#5d554c;--muted:#857c72;--line:#ece5da;
--brand:#c4501f;--brand-dark:#9b3a14;--brand-soft:#fdf0e8;--green:#1f7a5f;--green-soft:#e3f3ec;--amber:#f2a541;
--radius:20px;--shadow:0 1px 2px rgba(31,27,22,.04),0 8px 28px -8px rgba(31,27,22,.10);
--shadow-lg:0 2px 4px rgba(31,27,22,.05),0 18px 44px -12px rgba(31,27,22,.20);
--ease:cubic-bezier(.2,.8,.2,1)}
body{background:var(--bg);-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
::selection{background:#ffd9c4}
h1,h2,h3{letter-spacing:.01em}
.section>h2{font-weight:800}
.eyebrow{display:inline-flex;align-items:center;gap:6px}
.eyebrow::before{content:"";width:18px;height:2px;border-radius:2px;background:currentColor}

/* ヘッダー：すりガラス */
.site-header{background:rgba(255,255,255,.72);backdrop-filter:saturate(1.6) blur(14px);-webkit-backdrop-filter:saturate(1.6) blur(14px);
border-bottom:1px solid rgba(236,229,218,.8)}
.sbox{transition:box-shadow .2s var(--ease),border-color .2s}
.sbox:focus-within{box-shadow:0 0 0 4px rgba(196,80,31,.14)}
.catbtn{transition:background .2s,border-color .2s,color .2s,transform .15s}
.catbtn:hover{transform:translateY(-1px)}
.catpanel{animation:panelIn .18s var(--ease)}
@keyframes panelIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
.catpanel a{transition:background .15s,border-color .15s,transform .15s}
.catpanel a:hover{transform:translateX(3px)}

/* カード：浮く・画像が少しだけ拡大 */
.item.big,.gcard,.guide-cards a,.svc,.cat-tops a,.item.mini,.rows{transition:transform .25s var(--ease),box-shadow .25s var(--ease),border-color .25s}
.item.big:hover,.gcard:hover,.guide-cards a:hover,.svc:hover,.cat-tops a:hover,.item.mini:hover{transform:translateY(-4px);box-shadow:var(--shadow-lg)}
.big-img,.mini-img,.gcard,.guide-cards a,.svc-banner{overflow:hidden}
.big-img img,.mini-img img,.gcard img,.guide-cards img,.svc-banner img,.row-img img{transition:transform .5s var(--ease)}
.item.big:hover .big-img img,.item.mini:hover .mini-img img,.gcard:hover img,.guide-cards a:hover img,.svc:hover .svc-banner img,
.item.row:hover .row-img img{transform:scale(1.05)}
.item.row{transition:background .2s}
.item.row:hover{background:#fffaf6}

/* ボタン：乗せると明るく、押すと沈む */
.btn-buy,.btn-svc{background:linear-gradient(180deg,#d0592a,#b8461a);box-shadow:0 1px 0 rgba(255,255,255,.25) inset,0 6px 16px -6px rgba(184,70,26,.55);
transition:transform .15s var(--ease),box-shadow .2s,filter .2s}
.btn-svc{background:linear-gradient(180deg,#24896b,#1b6f56);box-shadow:0 1px 0 rgba(255,255,255,.25) inset,0 6px 16px -6px rgba(27,111,86,.5)}
.btn-yahoo{background:linear-gradient(180deg,#e0362f,#c4231d)}
.btn-buy:hover,.btn-svc:hover{filter:brightness(1.07);transform:translateY(-1px);box-shadow:0 1px 0 rgba(255,255,255,.25) inset,0 10px 22px -8px rgba(184,70,26,.6)}
.btn-buy:active,.btn-svc:active,.catbtn:active,.tab:active{transform:translateY(1px) scale(.98)}
.btn-sub{transition:background .2s,transform .15s}
.btn-sub:hover{transform:translateY(-1px)}
a:focus-visible,button:focus-visible,input:focus-visible{outline:3px solid #f2a541;outline-offset:2px;border-radius:10px}

/* ページ内メニュー・タブ */
.toc-pills a{transition:background .2s,color .2s,border-color .2s,transform .15s}
.toc-pills a:hover{transform:translateY(-1px)}
.toc-pills{background:linear-gradient(var(--bg) 70%,rgba(251,250,247,0))}
.tabs{position:relative}
.tab{position:relative;transition:color .2s}
.tab::after{content:"";position:absolute;left:16px;right:16px;bottom:-2px;height:3px;border-radius:3px;background:var(--brand);
transform:scaleX(0);transition:transform .25s var(--ease)}
.tab.on{border-bottom-color:transparent}
.tab.on::after{transform:scaleX(1)}

/* 値下がりボード：奥行きのあるグラデーション */
.dropboard{background:radial-gradient(120% 140% at 0% 0%,#e0662e 0%,#c4501f 40%,#8f3412 100%)}
.dropboard::after{content:"";position:absolute;inset:0;pointer-events:none;
background:radial-gradient(60% 80% at 100% 0%,rgba(255,255,255,.14),transparent 60%)}
.dropboard>*{position:relative;z-index:1}
.stat{transition:transform .2s var(--ease),background .2s}
.stat:hover{transform:translateY(-2px)}
.stat b{font-variant-numeric:tabular-nums}

/* 発見・こんな人に */
.discovery li{transition:transform .2s var(--ease),box-shadow .2s}
.discovery li:hover{transform:translateX(3px);box-shadow:var(--shadow)}
.section.feature{background:linear-gradient(180deg,#fff 0%,#fff7f1 100%)}

/* スクロールで表示（JSが動く環境だけ。動きを減らす設定の人には出さない） */
.js .rv{opacity:0;transform:translateY(18px);transition:opacity .6s var(--ease),transform .6s var(--ease)}
.js .rv.in{opacity:1;transform:none}
/* 情報の強弱：主役（値下がり・おすすめ・ランキング）を先に、脇役（発見・FAQ・関連）は控えめ */
.hero .wrap{padding-top:44px;padding-bottom:52px}
.banner .wrap{padding-top:38px;padding-bottom:52px}
.section{margin:44px 0}
.section>h2{margin-bottom:6px}
.basis{color:var(--muted)}
.section.feature,#ranking{scroll-margin-top:calc(var(--hdr-h,64px) + 56px)}
.discovery,#faq,.section.related,#compare{padding-top:28px;border-top:1px solid var(--line)}
.discovery>h2,#faq>h2,.section.related>h2{font-size:clamp(18px,2.6vw,21px)}
.discovery .eyebrow{color:#b7791f}
@media (max-width:760px){.section{margin:34px 0}.hero .wrap{padding-top:32px;padding-bottom:44px}.banner .wrap{padding-top:28px;padding-bottom:44px}}
/* スマホでは結論を読みやすい大きさに詰める */
@media (max-width:760px){.summary{padding:14px 14px 12px;font-size:14px;line-height:1.75}.summary ul{padding-left:18px}.summary li+li{margin-top:4px}}
/* 横並びの商品をスライダーに（JSが動く環境だけ。動かない環境では従来どおり横スクロール） */
.slider{position:relative}
.slider .hscroll{scroll-padding-inline:20px;scrollbar-width:none;scroll-behavior:smooth;overscroll-behavior-x:contain}
.slider .hscroll::-webkit-scrollbar{display:none}
.slider.more-r .hscroll{-webkit-mask-image:linear-gradient(90deg,#000 88%,transparent);mask-image:linear-gradient(90deg,#000 88%,transparent)}
.slider.more-l .hscroll{-webkit-mask-image:linear-gradient(90deg,transparent,#000 12%);mask-image:linear-gradient(90deg,transparent,#000 12%)}
.slider.more-l.more-r .hscroll{-webkit-mask-image:linear-gradient(90deg,transparent,#000 10%,#000 90%,transparent);
mask-image:linear-gradient(90deg,transparent,#000 10%,#000 90%,transparent)}
.sl-btn{position:absolute;top:calc(50% - 26px);z-index:2;width:44px;height:44px;border-radius:50%;border:0;cursor:pointer;
display:none;align-items:center;justify-content:center;background:rgba(255,255,255,.96);color:var(--ink);
box-shadow:0 6px 18px -4px rgba(31,27,22,.35);transition:opacity .2s,transform .2s var(--ease),box-shadow .2s}
.sl-btn svg{width:20px;height:20px}
.sl-prev{left:-6px}.sl-next{right:-6px}
.sl-btn:hover{transform:scale(1.08);box-shadow:0 10px 24px -6px rgba(31,27,22,.45)}
.sl-btn[disabled]{opacity:0;pointer-events:none}
@media (hover:hover) and (pointer:fine){.sl-btn{display:flex}}
.sl-bar{height:4px;margin:10px auto 2px;width:min(220px,50%);border-radius:4px;background:rgba(40,35,29,.12);overflow:hidden}
.sl-bar i{display:block;height:100%;border-radius:4px;background:var(--brand);transition:transform .25s var(--ease),width .25s}
.dropboard .sl-bar{background:rgba(255,255,255,.25)}
.dropboard .sl-bar i{background:#fff}
.slider.nofit .sl-bar{display:none}
/* 並べ替え */
.sortbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:12px 0 4px}
.sortbar span{font-size:13px;color:var(--muted);margin-right:2px}
.sortbar button{font:inherit;font-size:13px;font-weight:700;padding:7px 14px;border-radius:999px;border:1px solid var(--line);
background:var(--surface);color:var(--ink);cursor:pointer;transition:background .2s,color .2s,border-color .2s}
.sortbar button:hover{border-color:var(--brand)}
.sortbar button.on{background:var(--ink);color:#fff;border-color:var(--ink)}
/* 値下がり0件のときは小さく */
.dropboard.empty{padding-bottom:16px}
.dropboard.empty .db-stats{display:none}
.slider .swipe{scrollbar-width:none;scroll-behavior:smooth}
.slider .swipe::-webkit-scrollbar{display:none}
.badge-ever{background:#1f7a5f;color:#fff}
@media (prefers-reduced-motion:reduce){
*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}
.js .rv{opacity:1!important;transform:none!important}
.item.big:hover,.gcard:hover,.guide-cards a:hover,.svc:hover,.cat-tops a:hover,.item.mini:hover{transform:none}
}
"""
# CSSの中身が変わるたびに変わる番号。ブラウザに古いstyle.cssを使い回させないため
# （同じ日に何度もデザインを変えると、日付の番号では更新されなかった）
ABOUT_UPDATED = "2026-10-08"  # 運営情報・プライバシーポリシーを書き換えたらこの日付も更新する
CSS_VER = __import__("hashlib").md5(CSS.encode("utf-8")).hexdigest()[:8]

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="#b8562f"/><path d="M14 20 L28 34 L36 26 L50 42" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/><path d="M40 42 H50 V32" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>"""
LOGO_SVG = ('<svg width="30" height="30" viewBox="0 0 64 64" aria-hidden="true">'
            '<rect width="64" height="64" rx="16" fill="#b8562f"/>'
            '<path d="M14 20 L28 34 L36 26 L50 42" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'
            '<path d="M40 42 H50 V32" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def _meta_desc(desc: str, n: int = 120) -> str:
    """検索結果で切れない長さ（約120字）に。できるだけ句点で区切る。"""
    desc = re.sub(r"\s+", " ", desc).strip()
    if len(desc) <= n:
        return desc
    cut = desc[:n]
    k = cut.rfind("。")
    return cut[:k + 1] if k >= 60 else cut[:n - 1] + "…"


def _page(title: str, body: str, desc: str, path: str, *, current: str = "",
          og_image: str = "/img/hero.jpg", ld: str = "", og_type: str = "website", noindex: bool = False) -> str:
    robots = "noindex,follow" if noindex else "index,follow,max-image-preview:large"
    desc = _meta_desc(desc)
    cur_attr = ' aria-current="page"'
    cur_cat = CAT_OF.get(current, {}).get("slug", "")
    nav = "".join(
        f'<button type="button" class="catbtn{" cur" if c["slug"] == cur_cat else ""}" aria-expanded="false" '
        f'aria-controls="cat-{c["slug"]}">{c["emoji"]} {E(c["name"])}<span class="caret">▾</span></button>'
        for c in CATEGORIES)
    panels = "".join(
        f'<div class="catpanel" id="cat-{c["slug"]}" hidden><div class="wrap"><p class="catpanel-h">{c["emoji"]} {E(c["name"])}'
        f'<a class="catall" href="/c/{c["slug"]}/">まとめを見る →</a></p><ul>'
        + "".join(f'<li><a href="/{g["slug"]}/"{cur_attr if g["slug"] == current else ""}>{g["emoji"]} {E(g["name"])}</a></li>'
                  for g in _cat_genres(c))
        + "</ul></div></div>" for c in CATEGORIES)
    full_title = f"{title}｜{SITE_NAME}" if title != SITE_NAME else f"{SITE_NAME}｜毎日の価格記録で買い時が分かる"
    yahoo_credit = (YAHOO_CREDIT if yahoo_enabled() else "")
    footer_genres = "".join(
        f'<li class="fcat"><b>{E(c["name"])}</b>'
        + "".join(f'<a href="/{g["slug"]}/">{E(g["name"])}</a>' for g in _cat_genres(c)) + "</li>"
        for c in CATEGORIES)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{E(full_title)}</title>
<meta name="description" content="{E(desc)}">
<link rel="canonical" href="{SITE_URL}{path}">
<link rel="preload" as="image" href="{og_image}" fetchpriority="high">
<meta name="robots" content="{robots}">
<meta name="theme-color" content="#b8562f">
<meta property="og:site_name" content="{SITE_NAME}"><meta property="og:type" content="{og_type}">
<meta property="og:title" content="{E(full_title)}"><meta property="og:description" content="{E(desc)}">
<meta property="og:url" content="{SITE_URL}{path}"><meta property="og:image" content="{SITE_URL}{og_image}">
<meta property="og:locale" content="ja_JP"><meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="apple-touch-icon" href="/img/apple-touch-icon.png">
<link rel="stylesheet" href="/style.css?v={CSS_VER}">
<link rel="alternate" type="application/rss+xml" title="{SITE_NAME} 選び方ガイド" href="/feed.xml">
{GA4_TAG}
{_linkswitch_tag()}
{ld}
</head><body>
<div class="prbar">当サイトはアフィリエイト広告（楽天アフィリエイト・A8.net・バリューコマース）を利用しています</div>
<header class="site-header" id="hdr">
<div class="wrap hrow"><a class="logo" href="/" aria-label="{SITE_NAME} トップ">{LOGO_SVG}<span>買い時<em>ナビ</em></span></a>
<form class="sbox" action="/search/" method="get" role="search"><input type="search" name="q" placeholder="商品名・ジャンルで探す" aria-label="サイト内検索" enterkeyhint="search"><button type="submit">検索</button></form></div>
<div class="wrap hnav"><nav class="gnav catnav" aria-label="カテゴリ">{nav}</nav></div>
{panels}
</header>
<main>{body}</main>
<button class="totop" type="button" aria-label="ページ上部へ" onclick="scrollTo({{top:0,behavior:'smooth'}})">↑</button>
<script>(function(){{var chev=function(d){{return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="'+(d<0?'M15 5l-7 7 7 7':'M9 5l7 7-7 7')+'"/></svg>'}};
document.querySelectorAll('.hscroll, .swipe').forEach(function(ol){{var w=document.createElement('div');w.className='slider';ol.parentNode.insertBefore(w,ol);w.appendChild(ol);
var pv=document.createElement('button'),nx=document.createElement('button'),bar=document.createElement('div');
pv.type=nx.type='button';pv.className='sl-btn sl-prev';nx.className='sl-btn sl-next';pv.setAttribute('aria-label','前へ');nx.setAttribute('aria-label','次へ');
pv.innerHTML=chev(-1);nx.innerHTML=chev(1);bar.className='sl-bar';bar.innerHTML='<i></i>';w.appendChild(pv);w.appendChild(nx);w.appendChild(bar);
var th=bar.firstChild;function up(){{var m=ol.scrollWidth-ol.clientWidth,x=ol.scrollLeft;w.classList.toggle('nofit',m<4);
pv.disabled=x<24;nx.disabled=x>m-24;w.classList.toggle('more-l',x>24);w.classList.toggle('more-r',x<m-24);
var r=ol.clientWidth/Math.max(ol.scrollWidth,1);th.style.width=(r*100)+'%';th.style.transform='translateX('+(m>0?x/m*(1/r-1)*100:0)+'%)'}}
function go(d){{ol.scrollBy({{left:d*ol.clientWidth*.85,behavior:'smooth'}})}}
pv.addEventListener('click',function(){{go(-1)}});nx.addEventListener('click',function(){{go(1)}});
ol.addEventListener('scroll',up,{{passive:true}});addEventListener('resize',up);if(window.ResizeObserver)new ResizeObserver(up).observe(ol);up()}})}})();</script>
<script>(function(){{document.querySelectorAll('.ranklist').forEach(function(rl){{var d=rl.querySelector('.rank-default'),s=rl.querySelector('.rank-sorted');
rl.querySelectorAll('.sortbar button').forEach(function(b){{b.addEventListener('click',function(){{var k=b.dataset.sort;
rl.querySelectorAll('.sortbar button').forEach(function(x){{x.classList.toggle('on',x===b)}});
if(k==='k'){{d.hidden=false;s.hidden=true;return}}
var li=Array.prototype.slice.call(s.children);li.sort(function(a,c){{return k==='p'?(+a.dataset.p)-(+c.dataset.p):(+c.dataset.r)-(+a.dataset.r)}});
li.forEach(function(x){{s.appendChild(x)}});d.hidden=true;s.hidden=false}})}})}})}})();</script>
<script>(function(){{var R=document.documentElement,rm=matchMedia('(prefers-reduced-motion: reduce)').matches;
if(!rm&&'IntersectionObserver' in window){{R.classList.add('js');
var els=document.querySelectorAll('main .section, main .summary, main .services, main .chipgroups');
var io=new IntersectionObserver(function(es){{es.forEach(function(e){{if(e.isIntersecting){{e.target.classList.add('in');io.unobserve(e.target)}}}})}},{{rootMargin:'0px 0px -8% 0px'}});
els.forEach(function(el){{el.classList.add('rv');io.observe(el)}});
setTimeout(function(){{els.forEach(function(el){{el.classList.add('in')}})}},2500);
document.querySelectorAll('.stat b').forEach(function(b){{var n=b.firstChild;if(!n||n.nodeType!==3)return;var v=parseInt(n.nodeValue,10);if(!(v>0))return;
var s=null;n.nodeValue='0';function step(ts){{if(!s)s=ts;var p=Math.min((ts-s)/700,1);n.nodeValue=String(Math.round(v*(1-Math.pow(1-p,3))));if(p<1)requestAnimationFrame(step)}}
requestAnimationFrame(step)}})}}}})();</script>
<script>(function(){{var h=document.getElementById('hdr'),r=document.documentElement;
function s(){{r.style.setProperty('--hdr-h',h.offsetHeight+'px')}}s();addEventListener('resize',s);
var cbs=[].slice.call(document.querySelectorAll('.catbtn'));function closeCats(){{cbs.forEach(function(x){{
x.setAttribute('aria-expanded','false');document.getElementById(x.getAttribute('aria-controls')).hidden=true}})}}
cbs.forEach(function(b){{b.addEventListener('click',function(e){{e.stopPropagation();var open=b.getAttribute('aria-expanded')==='true';
closeCats();if(!open){{b.setAttribute('aria-expanded','true');document.getElementById(b.getAttribute('aria-controls')).hidden=false;
if(typeof gtag==='function')gtag('event','category_open',{{category:b.getAttribute('aria-controls')}})}}}})}});
document.addEventListener('click',function(e){{if(!e.target.closest('.catpanel'))closeCats()}});
document.addEventListener('keydown',function(e){{if(e.key==='Escape')closeCats()}});
document.querySelectorAll('.tab').forEach(function(b){{b.addEventListener('click',function(){{
var box=b.closest('.section');box.querySelectorAll('.tab').forEach(function(x){{var on=x===b;x.classList.toggle('on',on);
x.setAttribute('aria-selected',on);document.getElementById(x.dataset.tab).hidden=!on}});
if(typeof gtag==='function')gtag('event','tab_switch',{{tab:b.dataset.tab}})}})}});
var t=document.querySelector('.totop');addEventListener('scroll',function(){{t.classList.toggle('show',scrollY>600)}},{{passive:true}});
var links=[].slice.call(document.querySelectorAll('.toc-pills a'));if(!links.length||!('IntersectionObserver'in window))return;
var io=new IntersectionObserver(function(es){{es.forEach(function(e){{if(e.isIntersecting){{links.forEach(function(a){{
var on=a.getAttribute('href')==='#'+e.target.id;a.classList.toggle('on',on);if(on){{var n=a.parentNode;n.scrollTo({{left:a.offsetLeft-n.clientWidth/2+a.offsetWidth/2,behavior:'smooth'}})}}}})}}}})}},
{{rootMargin:'-45% 0px -50% 0px'}});links.forEach(function(a){{var el=document.querySelector(a.getAttribute('href'));if(el)io.observe(el)}});}})();</script>
<footer class="site-footer"><div class="wrap">
<div class="fcols">
<div><b>{SITE_NAME}</b><p>暮らしの定番アイテムの価格を毎日記録して、値下がりと評判から「買い時」をお知らせします。</p></div>
<div><b>ジャンル</b><ul>{footer_genres}</ul></div>
<div><b>サイトについて</b><ul><li><a href="/about/">運営者・ランキングの根拠</a></li><li><a href="/privacy/">プライバシーポリシー</a></li></ul></div>
</div>
<p>掲載価格は更新時点のものです。最新の価格・在庫は各ショップのページでご確認ください。</p>
{yahoo_credit}
<p><!-- Rakuten Web Services BEGIN --><a href="https://webservice.rakuten.co.jp/" target="_blank" rel="noopener">Supported by Rakuten Developers</a><!-- Rakuten Web Services END --></p>
<p>© {date.today().year} {SITE_NAME}</p>
</div></footer>
</body></html>
"""


def _genre_tag(data: tuple) -> str:
    _, popular, drops = data
    return f"{len(drops)}件 値下がり中" if drops else f"評判ランキング TOP{len(popular)}"


def _gcard_small(g: dict, genre_data: dict) -> str:
    return (f'<a class="gcard" href="/{g["slug"]}/"><img src="/img/{GENRE_IMG[g["slug"]]}.jpg" alt="" loading="lazy" '
            f'width="1200" height="675"><div><b>{g["emoji"]} {E(g["name"])}</b>'
            f'<span class="tag">{_genre_tag(genre_data[g["slug"]])}</span></div></a>')


def _related_genres(cur: str, genre_data: dict) -> str:
    """同じカテゴリのジャンルを写真つきで先に、ほかのカテゴリはチップで並べる。"""
    cat = CAT_OF.get(cur)
    same = [g for g in _cat_genres(cat) if g["slug"] != cur] if cat else []
    head = ""
    if same:
        head = (f'<h2 id="h-other">{cat["emoji"]} 同じ「{E(cat["name"])}」の買い時</h2>'
                f'<div class="gcards">{"".join(_gcard_small(g, genre_data) for g in same)}</div>')
    others = "".join(
        f'<div class="chipgroup"><b>{c["emoji"]} {E(c["name"])}</b>'
        + "".join(f'<a href="/{g["slug"]}/">{E(g["name"])}</a>' for g in _cat_genres(c) if g["slug"] != cur) + "</div>"
        for c in CATEGORIES if c is not cat)
    if not head:
        head = '<h2 id="h-other">ほかのジャンルの買い時もチェック</h2>'
    return (f'<section class="section related" aria-labelledby="h-other">{head}'
            f'<div class="chipgroups"><p class="chipgroups-h">ほかのカテゴリ</p>{others}</div></section>')


SEARCH_JS = r"""(function(){var q=new URLSearchParams(location.search).get('q')||'',inp=document.getElementById('sq'),
out=document.getElementById('sres'),msg=document.getElementById('smsg');inp.value=q;
document.querySelectorAll('.sbox input').forEach(function(i){i.value=q});
function norm(s){return(s||'').toLowerCase().replace(/[！-～]/g,function(c){return String.fromCharCode(c.charCodeAt(0)-0xfee0)})
.replace(/[ァ-ヶ]/g,function(c){return String.fromCharCode(c.charCodeAt(0)-0x60)}).replace(/\s+/g,' ')}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
fetch('/search.json').then(function(r){return r.json()}).then(function(d){function run(){var w=norm(inp.value).trim().split(' ').filter(Boolean);
if(!w.length){msg.textContent='キーワードを入力してください。';out.innerHTML='';return}
var hit=d.filter(function(x){var s=norm(x.t+' '+x.k);return w.every(function(v){return s.indexOf(v)>=0})});
hit.sort(function(a,b){return a.o-b.o});msg.textContent='「'+inp.value+'」の検索結果：'+hit.length+'件';
out.innerHTML=hit.slice(0,60).map(function(x){return'<li><a href="'+esc(x.u)+'">'+(x.i?'<img src="'+esc(x.i)+'" alt="" loading="lazy">':'')+
'<div><b>'+esc(x.t)+'</b><small>'+esc(x.s)+'</small></div></a></li>'}).join('')||'';
if(typeof gtag==='function')gtag('event','search',{search_term:inp.value})}
run();document.getElementById('sform').addEventListener('submit',function(e){e.preventDefault();
history.replaceState(null,'','?q='+encodeURIComponent(inp.value));run()})})})();"""


def _search_index(genre_data: dict) -> list[dict]:
    """サイト内検索の索引（ジャンル・ガイド・ランキング掲載商品）。o は表示順の優先度。"""
    idx = []
    for g in GENRES:
        idx.append({"t": f"{g['name']}の買い時", "s": f"ジャンル｜{g['lead']}", "u": f"/{g['slug']}/",
                    "k": " ".join(g["keywords"]), "i": f"/img/{GENRE_IMG[g['slug']]}.jpg", "o": 0})
        for x in _guides(g["slug"]):
            idx.append({"t": x["title"], "s": f"選び方ガイド｜{x['desc']}", "u": f"/{g['slug']}/{x['slug']}/",
                        "k": g["name"], "i": "", "o": 1})
        _, popular, drops = genre_data[g["slug"]]
        seen = set()
        for mode, lst in (("drop", drops), ("pop", popular)):
            for rank, it in enumerate(lst, 1):
                if it["itemCode"] in seen:
                    continue
                seen.add(it["itemCode"])
                label = f"{it['drop_pct']:.0f}%値下がり中" if mode == "drop" else f"評判ランキング{rank}位"
                idx.append({"t": _short_name(it["itemName"], 60), "s": f"{g['name']}｜{it['price']:,}円｜{label}",
                            "u": f"/{g['slug']}/#{mode}-{rank}", "k": f"{g['name']} {it.get('shopName', '')}",
                            "i": it.get("imageUrl", ""), "o": 2 if mode == "drop" else 3})
    return idx


def _write(path: str, content: str) -> None:
    p = OUT_DIR / path.strip("/") / "index.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


_REL = 'rel="nofollow sponsored noopener" target="_blank"'


def _thumb(url: str, size: int) -> str:
    """楽天の商品画像は元サイズ（900px・200KB前後）のまま読むと重いので、表示サイズの2倍程度に縮小した版を使う。"""
    if "thumbnail.image.rakuten.co.jp" in url and "_ex=" not in url:
        px = 128 if size <= 64 else (300 if size <= 160 else 400)
        return f"{url.split('?')[0]}?_ex={px}x{px}"
    return url


def _img(it: dict, size: int) -> str:
    if not it.get("imageUrl"):
        return '<div class="noimg"></div>'
    return (f'<img src="{E(_thumb(it["imageUrl"], size))}" alt="{E(_short_name(it["itemName"], 40))}" loading="lazy" '
            f'decoding="async" width="{size}" height="{size}">')


def _buy_btn(it: dict, cls: str = "btn-buy", label: str = "") -> str:
    is_yahoo = it.get("mall") == "yahoo"
    text = label or ("Yahoo!で見る" if is_yahoo else "楽天で見る")
    yc = " btn-yahoo" if is_yahoo else ""
    return f'<a class="{cls}{yc}" href="{E(_buy_url(it))}" {_REL}>{text}</a>'


def _stars(it: dict) -> str:
    return (f'<span class="stars">★{it["reviewAverage"]:.2f}</span>'
            f'<span class="muted">（{it["reviewCount"]:,}件）</span>')


def _has_drop(it: dict) -> bool:
    return it.get("drop_pct", 0) >= DROP_MIN_PCT and it.get("days", 0) >= 2


def _big_card(rank: int, it: dict, mode: str, label: str = "", reason: str = "") -> str:
    """1〜3位・今日の注目用の大きいカード。"""
    medal = {1: "gold", 2: "silver", 3: "bronze"}.get(rank, "")
    url = E(_buy_url(it))
    chip = (f'<span class="chip-label">{E(label)}</span>' if label
            else f'<span class="rank {medal}">{rank}</span>')
    drop = f'<span class="badge badge-drop">{it["drop_pct"]:.0f}%値下がり</span>' if _has_drop(it) else ""
    low = ('<span class="badge badge-low">記録上の最安値</span>'
           if it.get("is_all_time_low") and it.get("days", 0) >= 7 else "")
    was = (f'<s class="was">{_yen(it["reference_price"])}</s>'
           if drop and it["reference_price"] > it["price"] else "")
    spark = _sparkline(it["history"]) if it.get("days", 0) >= 2 else ""
    sub = ""
    if it.get("mall") != "yahoo" and yahoo_enabled():
        q = E(quote(_short_name(it["itemName"], 40).rstrip("…")))
        sub = f'<a class="btn-sub" href="https://shopping.yahoo.co.jp/search?p={q}" {_REL}>Yahoo!で探す</a>'
    return f"""
<li class="item big" id="{mode}-{rank}">
  <div class="big-head">{chip}<span class="badges">{drop}{low}</span></div>
  <a class="big-img" href="{url}" {_REL}>{_img(it, 240)}</a>
  <h3 class="item-name"><a href="{url}" {_REL}>{E(_short_name(it["itemName"], 60))}</a></h3>
  <div class="price-row"><span class="price">{it["price"]:,}<small>円</small></span>{was}</div>
  <div class="rating">{_stars(it)}</div>
  {f'<p class="why">{E(reason)}</p>' if reason else ''}
  <div class="trend">{spark}</div>
  <div class="btns">{_buy_btn(it)}{sub}</div>
</li>"""


def _row_card(rank: int, it: dict, mode: str) -> str:
    """4位以下用の1行リスト。"""
    url = E(_buy_url(it))
    drop = f'<span class="badge badge-drop">{it["drop_pct"]:.0f}%↓</span>' if _has_drop(it) else ""
    return f"""
<li class="item row" id="{mode}-{rank}">
  <span class="rank">{rank}</span>
  <a class="row-img" href="{url}" {_REL}>{_img(it, 64)}</a>
  <div class="row-body"><h3 class="item-name"><a href="{url}" {_REL}>{E(_short_name(it["itemName"], 56))}</a></h3>
    <div class="row-meta">{_stars(it)}</div></div>
  <div class="row-side"><span class="price">{it["price"]:,}<small>円</small></span>{drop}{_buy_btn(it, "btn-buy sm", "見る")}</div>
</li>"""


def _mini_card(rank: int, it: dict, mode: str) -> str:
    """横スクロール用の小さいカード（値下がり中など）。"""
    url = E(_buy_url(it))
    was = (f'<s class="was">{_yen(it["reference_price"])}</s>'
           if it.get("reference_price", 0) > it["price"] else "")
    badge = (f'<span class="badge badge-ever">★{it["reviewAverage"]:.2f}・{it["reviewCount"]:,}件</span>' if mode == "ever"
             else f'<span class="badge badge-drop">{it["drop_pct"]:.0f}%{"値下がり" if it["drop_pct"] >= DROP_MIN_PCT else "安"}</span>')
    return f"""
<li class="item mini" id="{mode}-{rank}">
  <a class="mini-img" href="{url}" {_REL}>{_img(it, 160)}{badge}</a>
  <h3 class="item-name"><a href="{url}" {_REL}>{E(_short_name(it["itemName"], 40))}</a></h3>
  <div class="price-row"><span class="price">{it["price"]:,}<small>円</small></span>{was}</div>
</li>"""


def _rank_list(items: list[dict], mode: str, empty: str) -> str:
    """1〜3位は大きいカード、4位以下は1行リスト。"""
    if not items:
        return f'<div class="panel"><p class="empty">{empty}</p></div>'
    top = "".join(_big_card(i + 1, it, mode) for i, it in enumerate(items[:3]))
    rest = "".join(_row_card(i + 4, it, mode) for i, it in enumerate(items[3:]))
    html_ = f'<ol class="podium">{top}</ol>' + (f'<ol class="rows" start="4">{rest}</ol>' if rest else "")
    if len(items) < 6:
        return html_
    # 並べ替え用の一覧（JSで切り替え）。順位の数字は評判順のまま見せる
    alt = "".join(_row_card(i + 1, it, f"{mode}s").replace(
        '<li class="item row"', f'<li class="item row" data-p="{it["price"]}" data-r="{it.get("reviewCount", 0)}" data-k="{i + 1}"', 1)
        for i, it in enumerate(items))
    bar = ('<div class="sortbar" role="group" aria-label="並べ替え"><span>並べ替え</span>'
           '<button type="button" class="on" data-sort="k">評判順</button>'
           '<button type="button" data-sort="p">安い順</button>'
           '<button type="button" data-sort="r">レビューが多い順</button></div>')
    return f'<div class="ranklist">{bar}<div class="rank-default">{html_}</div><ol class="rows rank-sorted" hidden>{alt}</ol></div>'


def _instagram_strip() -> str:
    """トップの「Instagramで紹介中の商品」。Instagramのプロフィールのリンク（買い時ナビ）から来た人が、
    投稿で見た商品にすぐたどり着けるように（2026-10-16）。商品情報はInstagramの投稿ジョブが ig_bio_cache.json に残す。"""
    try:
        cache = json.loads((DATA_DIR / "ig_bio_cache.json").read_text(encoding="utf-8"))
        posts = json.loads((DATA_DIR / "sns_posted.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return ""
    seen, cards = set(), []
    for x in reversed(posts):
        code = x.get("itemCode")
        if x.get("platform") != "instagram" or not code or code in seen or not cache.get(code):
            continue
        seen.add(code)
        c = cache[code]
        day = (x.get("posted_at") or "")[5:10].replace("-", "/")
        img = f'<img src="{E(_thumb(c["img"], 160))}" alt="" loading="lazy" width="160" height="160">' if c.get("img") else ""
        cards.append(f'<li class="item mini"><a class="mini-img" href="{E(c["url"])}" {_REL}>{img}'
                     f'<span class="badge badge-ever">{day} の投稿</span></a>'
                     f'<h3 class="item-name"><a href="{E(c["url"])}" {_REL}>{E(_short_name(c["name"], 40))}</a></h3>'
                     f'<div class="price-row"><span class="price">{int(c.get("price") or 0):,}<small>円</small></span></div></li>')
        if len(cards) >= 12:
            break
    if not cards:
        return ""
    return ('<section class="section insta" id="instagram" aria-labelledby="h-insta"><p class="eyebrow">INSTAGRAM</p>'
            '<h2 id="h-insta">Instagramで紹介中の商品</h2>'
            '<p class="basis">Instagram（@aki.h190）の投稿で紹介した商品です。新しい順に並べています。</p>'
            '<ol class="hscroll">' + "".join(cards) + "</ol></section>")


def _hscroll(items: list[dict], mode: str, empty: str) -> str:
    if not items:
        return f'<div class="panel"><p class="empty">{empty}</p></div>'
    return '<ol class="hscroll">' + "".join(_mini_card(i + 1, it, mode) for i, it in enumerate(items)) + "</ol>"


def _today_picks(popular: list[dict], drops: list[dict]) -> str:
    """ページの主役。評判1位・値下がり1位・手頃で高評価の3つを大きく見せる。"""
    picks, used = [], set()

    def add(it, label):
        if it and it["itemCode"] not in used:
            used.add(it["itemCode"])
            picks.append((it, label))

    add(popular[0] if popular else None, "評判No.1")
    most = max(popular, key=lambda x: x["reviewCount"]) if popular else None
    add(most, "レビュー数No.1")
    good = [x for x in popular if x["reviewAverage"] >= 4.3 and x["itemCode"] not in used]
    add(min(good, key=lambda x: x["price"]) if good else None, "手頃で高評価")
    for x in popular:
        if len(picks) >= 3:
            break
        add(x, "人気")
    if not picks:
        return ""
    cards = "".join(_big_card(i + 1, it, "pick", label) for i, (it, label) in enumerate(picks))
    return f'<ol class="podium picks">{cards}</ol>'



# 「こんな人には、これ」のジャンル別タイプ: (どんな人に, 商品名に含む語, その商品の特徴の呼び方)
# 理由は商品名に書かれた仕様と、評価・レビュー件数・価格・値下がりの数字だけで説明する（効能などは書かない）
GENRE_PERSONAS = {
    "coffee": [("1杯ずつ手軽に淹れたい人に", ["ドリップバッグ", "ドリップパック"], "ドリップバッグ"),
               ("豆から挽いて楽しみたい人に", ["豆"], "コーヒー豆")],
    "sleep": [("マットレスを見直したい人に", ["マットレス"], "マットレス"), ("枕を買い替えたい人に", ["枕"], "枕")],
    "kitchen": [("毎日の料理に使う人に", ["フライパン"], "フライパン"), ("お茶やコーヒーをよく飲む人に", ["ケトル"], "電気ケトル")],
    "pet": [("犬と暮らしている人に", ["ドッグ", "犬"], "犬用の商品"), ("猫と暮らしている人に", ["キャット", "猫"], "猫用の商品")],
    "water": [("家で飲む量が多い人に", ["2L", "2l", "2リットル"], "2Lボトル"), ("炭酸が好きな人に", ["炭酸"], "炭酸水")],
    "rice": [("研ぐ手間を省きたい人に", ["無洗米"], "無洗米"), ("家族で食べる量が多い人に", ["10kg", "10キロ", "20kg"], "10kg以上の大袋")],
    "contact": [("毎日のケアを省きたい人に", ["ワンデー", "1day", "1DAY", "1Day"], "ワンデー（1日使い捨て）"),
                ("2週間交換のレンズを使っている人に", ["2week", "2WEEK", "2ウィーク", "2Week"], "2ウィーク")],
    "baby": [("パンツタイプのおむつを使う人に", ["パンツ"], "パンツタイプのおむつ"), ("おしりふきをまとめ買いしたい人に", ["おしりふき"], "おしりふき")],
    "daily": [("トイレットペーパーの交換を減らしたい人に", ["長持ち", "2倍", "3倍", "長巻"], "長尺タイプ"),
              ("ティッシュをまとめ買いしたい人に", ["ティッシュ"], "ティッシュ")],
    "detergent": [("計量の手間を省きたい人に", ["ジェルボール"], "ジェルボール"), ("容量あたりの安さを重視する人に", ["詰め替え", "詰替", "つめかえ"], "詰め替え用")],
    "alcohol": [("ビールをケースで買いたい人に", ["ビール"], "ビール"), ("チューハイ・ハイボール派の人に", ["チューハイ", "ハイボール", "サワー"], "チューハイ・ハイボール")],
    "bousai": [("長期保存の備えをしたい人に", ["5年", "7年", "10年"], "長期保存できる商品"),
               ("停電に備えたい人に", ["モバイルバッテリー", "ポータブル電源"], "充電の備え")],
    "instant": [("カップ麺をまとめ買いしたい人に", ["カップ"], "カップ麺"), ("袋麺派の人に", ["袋麺", "5食"], "袋麺")],
    "interior": [("床まわりを整えたい人に", ["ラグ", "カーペット"], "ラグ"), ("部屋を暗くしたい人に", ["遮光"], "遮光カーテン")],
    "outdoor": [("キャンプを始める人に", ["チェア"], "キャンプチェア"), ("泊まりのキャンプに行く人に", ["寝袋", "シュラフ"], "寝袋")],
    "heater": [("寝るときに暖まりたい人に", ["電気毛布"], "電気毛布"), ("部屋の乾燥が気になる人に", ["加湿器"], "加湿器")],
    "cleaner": [("掃除を任せたい人に", ["ロボット"], "ロボット掃除機"), ("気づいたらすぐ掃除したい人に", ["コードレス"], "コードレス掃除機")],
    "towel": [("乾きやすさを重視する人に", ["速乾", "薄手"], "速乾・薄手タイプ"), ("ホテルのような厚みが欲しい人に", ["ホテル"], "ホテルタイプ")],
    "toy": [("長く遊べるものを探している人に", ["ブロック"], "ブロック"), ("小さな子へのプレゼントを探す人に", ["木製", "木の"], "木のおもちゃ")],
    "osechi": [("少人数で楽しみたい人に", ["1人前", "2人前", "1〜2人前", "2〜3人前", "1～2人前", "2～3人前"], "少人数向けのおせち"),
               ("家族で囲みたい人に", ["4人前", "5人前", "3〜4人前", "4〜5人前", "3～4人前", "4～5人前"], "家族向けのおせち")],
    "meat": [("年末のごちそうを探す人に", ["カニ", "蟹", "ガニ"], "カニ"), ("普段のおかずをまとめ買いしたい人に", ["訳あり", "切り落とし"], "訳あり・切り落とし")],
    "fruit": [("冬の定番を箱買いしたい人に", ["みかん"], "みかん"), ("りんご好きの人に", ["りんご", "林檎"], "りんご")],
    "phone": [("充電を速くしたい人に", ["PD", "急速"], "急速充電対応の商品"), ("置くだけで充電したい人に", ["ワイヤレス"], "ワイヤレス充電")],
    "pcgear": [("机をすっきりさせたい人に", ["ワイヤレス", "Bluetooth", "bluetooth"], "ワイヤレスの商品"), ("画面を広くしたい人に", ["モニター"], "モニター")],
    "gift": [("相手の好みが分からない人に", ["カタログ"], "カタログギフト"), ("グルメを贈りたい人に", ["グルメ", "スイーツ"], "グルメ・スイーツ")],
    "kaden": [("毎日ごはんを炊く人に", ["炊飯"], "炊飯器"), ("温めをもっと手軽にしたい人に", ["レンジ"], "電子レンジ")],
    "car": [("後ろからの追突にも備えたい人に", ["前後"], "前後2カメラのドライブレコーダー"),
            ("小さな子を車に乗せる人に", ["チャイルドシート", "ジュニアシート"], "チャイルドシート")],
    "randoseru": [("女の子のランドセルを探している人に", ["女の子"], "女の子向けのランドセル"), ("男の子のランドセルを探している人に", ["男の子"], "男の子向けのランドセル")],
    "roomwear": [("寒い部屋で過ごす時間が長い人に", ["着る毛布"], "着る毛布"), ("足元が寒い人に", ["スリッパ", "ルームシューズ"], "スリッパ")],
    "techo": [("予定を細かく書きたい人に", ["ウィークリー", "週間"], "ウィークリー手帳"), ("家族の予定を共有したい人に", ["カレンダー"], "カレンダー")],
    "bicycle": [("坂道が多い人に", ["電動", "アシスト"], "電動アシスト自転車"), ("安全に乗りたい人に", ["ヘルメット"], "ヘルメット")],
    "battery": [("電池代を減らしたい人に", ["充電池", "充電式"], "充電池"), ("照明を替えたい人に", ["LED"], "LED電球")],
    "clothcare": [("朝の身支度を早くしたい人に", ["スチーマー", "スチーム"], "衣類スチーマー"), ("セーターの毛玉が気になる人に", ["毛玉"], "毛玉取り器")],
    "kitchensupply": [("冷凍保存をよくする人に", ["保存袋", "ジッパー", "ジップ"], "保存袋"), ("ラップをまとめ買いしたい人に", ["ラップ"], "ラップ")],
    "kairo": [("外で過ごす時間が長い人に", ["カイロ"], "カイロ"), ("手元を温めたい人に", ["手袋", "グローブ"], "手袋")],
    "laundry": [("服がずり落ちて困る人に", ["すべらない", "滑らない"], "すべらないハンガー"), ("部屋干しが多い人に", ["室内", "物干し"], "室内物干し")],
    "stationery": [("書き心地にこだわりたい人に", ["ボールペン", "ペン"], "ペン"), ("メモをよく取る人に", ["ふせん", "付箋", "ノート"], "ふせん・ノート")],
    "cleaning": [("床掃除をラクにしたい人に", ["ワイパー", "モップ"], "ワイパー・モップ"),
                 ("水まわりの汚れが気になる人に", ["スポンジ", "ブラシ"], "スポンジ・ブラシ")],
    "ink": [("エプソンのプリンターを使う人に", ["エプソン", "EPSON", "Epson"], "エプソン用"),
            ("キヤノンのプリンターを使う人に", ["キヤノン", "キャノン", "Canon", "CANON"], "キヤノン用")],
    "xmas": [("ツリーを置きたい人に", ["ツリー"], "ツリー"), ("飾りつけを楽しみたい人に", ["オーナメント", "イルミネーション", "リース"], "飾り")],
    "storage": [("布団をしまいたい人に", ["布団"], "布団用"), ("服をすっきりしまいたい人に", ["衣類", "衣装ケース", "収納ケース"], "衣類用")],
    "nabe": [("IHコンロを使っている人に", ["IH"], "IH対応"), ("土鍋でじっくり煮たい人に", ["土鍋"], "土鍋")],
    "frozen": [("お弁当づくりをラクにしたい人に", ["弁当", "お弁当"], "お弁当向け"),
               ("晩ごはんの一品を増やしたい人に", ["餃子", "惣菜", "おかず", "ハンバーグ"], "おかず")],
    "tableware": [("毎日のコーヒーやお茶をよく飲む人に", ["マグ"], "マグカップ"),
                  ("食器をまとめてそろえたい人に", ["セット"], "食器セット")],
    "bottle": [("子どもに持たせたい人に", ["子供", "キッズ", "子ども"], "子ども用"),
               ("デスクで温かい飲み物を楽しみたい人に", ["タンブラー"], "タンブラー")],
    "wallet": [("キャッシュレス中心で身軽にしたい人に", ["ミニ", "コンパクト", "薄型"], "ミニ財布"),
               ("お札を折らずに入れたい人に", ["長財布"], "長財布")],
    "watch": [("電池交換の手間を減らしたい人に", ["ソーラー"], "ソーラー"), ("時刻を合わせる手間を省きたい人に", ["電波"], "電波時計")],
    "lighting": [("部屋全体を明るくしたい人に", ["シーリング"], "シーリングライト"), ("電球だけ替えたい人に", ["電球"], "LED電球")],
    "desk": [("立って作業もしたい人に", ["昇降"], "昇降デスク"), ("座る時間が長い人に", ["チェア", "椅子"], "チェア")],
    "kidsbike": [("はじめての乗り物を探している人に", ["キックバイク", "ストライダー", "バランスバイク"], "キックバイク"),
                 ("補助輪から始めたい人に", ["補助輪"], "補助輪付き")],
    "cyclegear": [("夜道を走ることが多い人に", ["ライト"], "ライト"),
                  ("駐輪中の盗難が心配な人に", ["ロック", "鍵"], "ロック")],
    "hairtool": [("前髪や短めの髪を整えたい人に", ["ストレート", "ミニ"], "ストレートアイロン"),
                 ("巻き髪をつくりたい人に", ["カール", "2way", "2WAY"], "カール・2wayアイロン")],
    "bag": [("通勤・通学でA4を持ち歩く人に", ["A4", "通勤", "リュック"], "A4が入るバッグ"),
            ("身軽に出かけたい人に", ["ショルダー", "ミニ", "サコッシュ"], "小さめのバッグ")],
    "sneaker": [("歩く時間が長い人に", ["ウォーキング", "軽量", "幅広"], "軽量・幅広タイプ"),
                ("着こなしに合わせやすい白スニーカーを探す人に", ["白", "ホワイト"], "白スニーカー")],
    "outer": [("寒い地域や朝晩の外出が多い人に", ["ダウン"], "ダウン"), ("きれいめに着たい人に", ["コート"], "コート")],
    "kidswear": [("毎日の着替えをまとめてそろえたい人に", ["セット", "枚組", "福袋"], "セット・まとめ買い"),
                 ("外遊び用の上着を探している人に", ["アウター", "ジャンパー", "ジャケット"], "子供用アウター")],
    "inner": [("寒い日の外出が多い人に", ["タイツ", "レギンス"], "タイツ・レギンス"),
              ("重ね着をすっきりさせたい人に", ["インナー", "肌着"], "インナー")],
    "seasoning": [("料理に使う油を見直したい人に", ["オイル", "油"], "油"),
                  ("和食をよく作る人に", ["醤油", "しょうゆ", "だし", "出汁", "味噌", "みそ"], "醤油・だし・味噌")],
}
PERSONA_NOTE = {"contact": "※レンズの種類・度数は、眼科の指示に従って選んでください。"}


def _persona_picks(g: dict, rich: list[dict], popular: list[dict], drops: list[dict]) -> str:
    """「こんな人には、これ」。どんな人向けかと、なぜそう言えるか（数字）を添えて見せる。"""
    pool = [x for x in rich if _qualified(x)]
    cards, used = [], set()

    def add(it, label, reason):
        if it and it["itemCode"] not in used and len(cards) < 6:
            used.add(it["itemCode"])
            cards.append((it, label, reason))

    good = [x for x in pool if x["reviewAverage"] >= 4.3]
    if good:
        x = max(good, key=lambda x: x["reviewCount"])
        add(x, "失敗したくない人に", f"★4.3以上の中でレビューがいちばん多く、{x['reviewCount']:,}件の評価で★{x['reviewAverage']:.2f}です。")
    deal = None
    for x in popular:
        if _has_drop(x):
            deal = (x, f"直近30日の最高値{_yen(x['reference_price'])}から{x['drop_pct']:.0f}%安い{_yen(x['price'])}になっています。")
            break
    if not deal:
        for x in popular:
            if x.get("is_all_time_low") and x.get("days", 0) >= 7:
                deal = (x, f"評判ランキング上位で、いま記録上の最安値（{_yen(x['price'])}）です。")
                break
    if deal:
        add(deal[0], "今がお得なタイミングを狙う人に", deal[1])
    for label, words, feat in GENRE_PERSONAS.get(g["slug"], []):
        # 商品名の後ろには関連語が詰め込まれているので、先頭部分で「何の商品か」を判定する
        m = [x for x in pool if any(w in _name_head(x["itemName"], 40) for w in words) and x["itemCode"] not in used]
        if "kg以上" in feat:  # 重さで分けるタイプは、商品名で最初に出てくる重さで判定（「5kg 10kg 20kg」のような列挙対策）
            min_kg = float(re.search(r"(\d+)kg以上", feat).group(1))
            def first_kg(name):
                mm = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|キロ)", _name_head(name, 60))
                return float(mm.group(1)) if mm else 0.0
            m = [x for x in m if first_kg(x["itemName"]) >= min_kg]
        if m:
            x = max(m, key=_popularity)
            add(x, label, f"{feat}の中で、評価とレビュー件数のバランスがいちばん良い商品です（★{x['reviewAverage']:.2f}・{x['reviewCount']:,}件）。")
    if good:
        rest = [x for x in good if x["itemCode"] not in used]
        if rest:
            x = min(rest, key=lambda x: x["price"])
            add(x, "まずは手頃に試したい人に", f"★4.3以上の中でいちばん手頃な{_yen(x['price'])}です（容量や個数は商品ページで確認を）。")
    top = [x for x in pool if x["reviewCount"] >= 100 and x["itemCode"] not in used]
    if top:
        x = max(top, key=lambda x: x["reviewAverage"])
        add(x, "評価の高さで選びたい人に", f"レビュー100件以上の中で評価がいちばん高い★{x['reviewAverage']:.2f}（{x['reviewCount']:,}件）です。")
    if not cards:
        return ""
    html_ = "".join(_big_card(i + 1, it, "pick", label, reason) for i, (it, label, reason) in enumerate(cards))
    note = f'<p class="basis">{E(PERSONA_NOTE[g["slug"]])}</p>' if g["slug"] in PERSONA_NOTE else ""
    return f'<ol class="podium picks persona swipe">{html_}</ol>{note}'


def _qualified(it: dict) -> bool:
    return it.get("reviewAverage", 0) >= MIN_AVG and it.get("reviewCount", 0) >= MIN_REVIEWS


def _drop_stats(rich: list[dict], drops: list[dict]) -> dict:
    lows = [x for x in rich if x.get("is_all_time_low") and x.get("days", 0) >= 7 and _qualified(x)]
    return {"n": len(drops), "max": max((d["drop_pct"] for d in drops), default=0), "low": len(lows)}


def _near_drops(rich: list[dict], n: int = 12) -> list[dict]:
    """5%未満でも、記録上の最高値より少しでも安くなっている商品（値下がりが無い日の代わり）。"""
    near = [x for x in rich if 0 < x.get("drop_pct", 0) < DROP_MIN_PCT and x.get("days", 0) >= 2 and _qualified(x)]
    return sorted(near, key=lambda x: x["drop_pct"], reverse=True)[:n]


def _drop_board(title: str, stats: dict, drops: list[dict], near: list[dict], updated: str,
                extra: str = "") -> str:
    """ページ上部の主役。値下がりの状況を数字で見せ、そのすぐ下に該当商品を並べる。"""
    if drops:
        lead = f"直近30日の最高値より{DROP_MIN_PCT:.0f}%以上安い商品を、下がった順に並べています。"
        lst = _hscroll(drops, "drop", "")
    elif near:
        lead = (f"今は{DROP_MIN_PCT:.0f}%以上の大きな値下がりはありません。"
                "記録上の最高値より少しだけ安くなっている商品です。")
        lst = '<ol class="hscroll">' + "".join(_mini_card(i + 1, it, "near") for i, it in enumerate(near)) + "</ol>"
    else:
        lead = "今は値下がりしている商品はありません。価格は毎日記録しているので、下がったものがあればここに並びます。"
        lst = ""
        extra = extra + "<!--empty-->"
    mx = f'{stats["max"]:.0f}<small>%</small>' if stats["max"] else "—"
    return f"""
<section class="dropboard{" empty" if "<!--empty-->" in extra else ""}" id="drops" aria-labelledby="h-drops">
  <div class="db-head"><p class="eyebrow">PRICE DROP</p><h2 id="h-drops">{E(title)}</h2>
    <span class="db-stamp">{E(updated)}更新・毎日記録</span></div>
  <div class="db-stats">
    <div class="stat hot"><b>{stats["n"]}<small>件</small></b><span>値下がり中</span></div>
    <div class="stat"><b>{mx}</b><span>最大の下落率</span></div>
    <div class="stat"><b>{stats["low"]}<small>件</small></b><span>記録上の最安値</span></div>
  </div>
  {extra}
  <p class="db-lead">{lead}</p>
  {lst}
</section>"""


# ガイドの表紙（写真ではなく、色・絵文字・テーマ語で描く。権利の心配がなく、ガイドごとに見た目が変わる）
GUIDE_EMOJI = {
    "ミネラルウォーター": "💧", "炭酸水": "🫧", "お茶": "🍵", "ビール": "🍺", "ハイボール": "🥃", "日本酒": "🍶",
    "おむつ": "👶", "おしりふき": "🧴", "電池とLED": "🔋", "充電池": "♻️", "電動アシスト": "⚡", "自転車": "🚲",
    "モバイルバッテリー": "📱", "防災": "🧯", "チャイルドシート": "🚸", "ドライブレコーダー": "📹",
    "ロボット掃除機": "🤖", "掃除機": "🧹", "アイロン": "👔", "毛玉": "🧶", "保存方法": "🫙", "コーヒー豆の選び方": "☕",
    "ドリップバッグ": "🫖", "コンタクトレンズの費用": "💴", "コンタクトレンズの種類": "👁️", "ゴミ袋": "🗑️",
    "ティッシュ": "🤧", "トイレットペーパー": "🧻", "食洗機": "🍽️", "洗濯洗剤": "🧺", "柔軟剤": "🌸",
    "果物": "🍇", "みかん": "🍊", "カタログギフト": "📖", "お歳暮の選び方": "🎁", "人気のジャンル": "🎀",
    "電気毛布": "🛌", "暖房器具": "♨️", "こたつ": "🍊", "カップ麺": "🍜", "お菓子": "🍪", "カーテン": "🪟",
    "ラグ": "🛋️", "収納ボックス": "📦", "電子レンジ": "🍱", "炊飯器": "🍚", "カイロ": "🔥", "保存容器": "🥡",
    "フライパン": "🍳", "電気ケトル": "🫖", "ラップ": "🥪", "ハンガー": "👕", "カニ": "🦀", "肉・海鮮": "🥩",
    "おせち料理の意味": "🎍", "おせちの選び方": "🍱", "キャンプチェア": "🪑", "クーラーボックス": "🧊",
    "寝袋": "🏕️", "PCモニター": "🖥️", "マウス": "🖱️", "猫砂": "🐾", "キャットフード": "🐟", "ドッグフード": "🦴",
    "スマホ充電器": "🔌", "ワイヤレス充電器": "📶", "ランドセルカバー": "🌈", "ランドセルの選び方": "🎒",
    "パックご飯": "🍚", "レトルト": "🍛", "お米": "🌾", "着る毛布": "🧥", "ルームウェア": "🩴", "掛け布団": "☁️",
    "マットレス": "🛏️", "枕": "💤", "ボールペン": "🖊️", "カレンダー": "📅", "手帳": "📓", "タオルの洗い方": "🧼",
    "タオルの選び方": "🛁", "年齢別": "🎈", "おもちゃの選び方": "🧸",
    "大掃除": "🧹", "フローリング": "🧽", "プリンターインク": "🖨️", "年賀状": "📮", "クリスマスツリー": "🎄",
    "オーナメント": "✨", "圧縮袋": "🧳", "衣替え": "👚", "オリーブオイル": "🫒", "醤油": "🍶", "だし": "🐟",
    "土鍋": "🍲", "IH": "🔥", "冷凍食品の選び方": "🥟", "冷凍庫": "🧊", "食器の選び方": "🍽️", "マグカップ": "☕",
    "水筒": "🥤", "タンブラー": "🫖", "インナー": "👕", "タイツ": "🧦",
    "財布の選び方": "👛", "革財布": "🧴", "腕時計の選び方": "⌚", "ベルト": "🔗", "シーリングライト": "💡", "LED電球": "🔆",
    "デスク": "🖥️", "チェア": "🪑", "子ども用自転車": "🚲", "キックバイク": "🛴", "自転車用ヘルメット": "⛑️", "自転車のライトとロック": "🔦", "ヘアアイロン": "💇", "ドライヤー": "🌬️", "トートバッグ": "👜", "リュック": "🎒", "スニーカーのサイズ": "📏",
    "スニーカーのお手入れ": "🧼", "ダウンジャケット": "🧥", "コート": "🧣", "子供服のサイズ": "📐", "子供の冬アウター": "🧒",
}
# 文字が読みやすい淡い色の組（背景2色・文字色）
GUIDE_PALETTE = [("#ffe4d3", "#ffc5a6", "#7a2e0e"), ("#dcf3e8", "#b4e2cd", "#145a43"), ("#dfeaff", "#bcd3ff", "#1d4e89"),
                 ("#eee5ff", "#d6c6ff", "#4b2e83"), ("#fff3c9", "#ffe08c", "#6b4a00"), ("#ffe2e8", "#ffc3d0", "#8a1f3d"),
                 ("#f3ebe0", "#e4d2bb", "#5a4126"), ("#d8f3f3", "#ade2e2", "#0f5757")]
_GUIDE_TAIL = re.compile(r"(の選び方|のまとめ買いガイド|のケース買いガイド|のお取り寄せガイド|の始め方|の意味|の保存方法|"
                         r"の種類と選び方|と買い替え時期|のプレゼントの選び方)$")
_GUIDE_WORD_FIX = [(r"の費用の比べ方$", "の費用"), (r"で人気のジャンルと$", "の人気ジャンル"), (r"^年齢別・", "年齢別 "),
                   (r"^お取り寄せの", "")]


def _guide_cover(g: dict, x: dict) -> str:
    title = x["title"].split("｜")[0]  # 副題の語に引っぱられないよう、見出しの前半だけで判断する
    word = re.split(r"、", title)[0]
    for a, b in _GUIDE_WORD_FIX:
        word = re.sub(a, b, word)
    word = _GUIDE_TAIL.sub("", word)
    kind = ("保存のコツ" if "保存方法" in title else "お金の話" if re.search("費用|いくら", title)
            else "まとめ買い" if re.search("まとめ買い|ケース買い", title) else "お取り寄せ" if "お取り寄せ" in title
            else "豆知識" if "意味" in title else "お手入れ" if "洗い方" in title
            else "はじめかた" if "始め方" in title else "選び方")
    emoji = next((v for k, v in sorted(GUIDE_EMOJI.items(), key=lambda kv: -len(kv[0])) if k in title), g["emoji"])
    siblings = [s["slug"] for s in _guides(g["slug"])]
    gi = next((i for i, gg in enumerate(GENRES) if gg["slug"] == g["slug"]), 0)
    c1, c2, ink = GUIDE_PALETTE[(gi * 3 + (siblings.index(x["slug"]) if x["slug"] in siblings else 0)) % len(GUIDE_PALETTE)]
    # 単語の途中で折り返さないよう、長い語は小さく、区切り（・と）の後ろで改行できるようにする
    longest = max(len(s) for s in re.split(r"[・と ]", word))
    size = "" if len(word) <= 7 else " m" if longest <= 9 else " s"
    word_html = re.sub(r"([・と ])", r"\1<wbr>", E(word))
    return (f'<span class="g-cover" style="--c1:{c1};--c2:{c2};--ci:{ink}" aria-hidden="true">'
            f'<span class="gc-kind">{E(kind)}</span><span class="gc-word{size}">{word_html}</span>'
            f'<span class="gc-emoji">{emoji}</span></span>')


def _guide_card(g: dict, x: dict) -> str:
    return (f'<li><a href="/{g["slug"]}/{E(x["slug"])}/">{_guide_cover(g, x)}<span class="g-tag">{g["emoji"]} {E(g["name"])}</span>'
            f'<b>{E(x["title"])}</b><span class="g-desc">{E(x["desc"])}</span></a></li>')


def _items_list(items: list[dict], mode: str, empty: str) -> str:
    if not items:
        return f'<div class="panel"><p class="empty">{empty}</p></div>'
    return '<div class="panel"><ol class="items">' + "".join(
        _item_card(i + 1, it, mode) for i, it in enumerate(items)) + "</ol></div>"


def _compare_table(items: list[dict]) -> str:
    rows = "".join(
        f'<tr><td>{i + 1}</td><td><a href="{E(_buy_url(it))}" rel="nofollow sponsored noopener" target="_blank">'
        f'{E(_short_name(it["itemName"], 34))}</a></td><td class="num">{_yen(it["price"])}</td>'
        f'<td class="num">★{it["reviewAverage"]:.2f}</td><td class="num">{it["reviewCount"]:,}件</td>'
        f'<td class="num">{_yen(it["low"]) if it["days"] >= 2 else "記録中"}</td></tr>'
        for i, it in enumerate(items))
    return (f'<div class="table-wrap"><table><caption class="muted" style="text-align:left;padding:10px 14px">'
            f'評判ランキング上位の比較（価格は更新時点）</caption><thead><tr><th>順位</th><th>商品</th><th>価格</th>'
            f'<th>評価</th><th>レビュー数</th><th>記録上の最安</th></tr></thead><tbody>{rows}</tbody></table></div>')


_WD = "月火水木金土日"


def _discoveries(rich: list[dict], popular: list[dict]) -> list[str]:
    """毎日の価格記録から、検索では出てこない「お？」となる事実を作る。
    データが少なく言い切れないものは出さない（記録数・差の大きさに下限を設ける）。"""
    out = []
    tracked = [x for x in rich if x.get("days", 0) >= 7 and _qualified(x)]
    # 1) 値動きの大きい商品
    swing = []
    for x in tracked:
        hi, lo = x.get("high", 0), x.get("low", 0)
        prices = [r["price"] for r in x.get("history", [])]
        # 1日だけのセールやセット数の違うページへの切替（ちょうど半額・2倍など）を拾わないよう、
        # 最高値・最安値がそれぞれ2日以上記録され、差が10〜45%のものに限る
        if hi and lo and hi > lo and prices.count(hi) >= 2 and prices.count(lo) >= 2:
            pct = (hi - lo) / hi * 100
            if 10 <= pct <= 45:
                swing.append((pct, x))
    if swing:
        pct, x = max(swing, key=lambda s: s[0])
        if pct >= 10:
            out.append(f"「{_short_name(x['itemName'], 34)}」は、記録した{x['days']}日間で最高{_yen(x['high'])}・"
                       f"最安{_yen(x['low'])}と、{pct:.0f}%も値段が動いています。同じ商品でも、買う日で差が出ます。")
    # 2) 曜日の傾向（商品ごとの平均価格に対する比率を曜日別に集計）
    by_wd = {i: [] for i in range(7)}
    five_zero, others = [], []
    for x in tracked:
        hist = x.get("history", [])
        mean = sum(r["price"] for r in hist) / len(hist)
        if not mean:
            continue
        for r in hist:
            d = date.fromisoformat(r["date"])
            ratio = r["price"] / mean
            by_wd[d.weekday()].append(ratio)
            (five_zero if d.day % 5 == 0 else others).append(ratio)
    if all(len(v) >= 60 for v in by_wd.values()):
        avg = {k: sum(v) / len(v) for k, v in by_wd.items()}
        overall = sum(avg.values()) / 7
        cheap = min(avg, key=avg.get)
        diff = (overall - avg[cheap]) / overall * 100
        if diff >= 0.8:
            n = sum(len(v) for v in by_wd.values())
            out.append(f"記録した{n:,}件の価格では、{_WD[cheap]}曜日が平均より{diff:.1f}%安い傾向がありました。"
                       f"まとめ買いをするなら、{_WD[cheap]}曜日にのぞいてみる価値があります。")
    # 3) 5と0のつく日
    if len(five_zero) >= 80 and len(others) >= 200:
        a = sum(five_zero) / len(five_zero)
        b = sum(others) / len(others)
        d = (b - a) / b * 100
        if d >= 0.8:
            out.append(f"楽天の「5と0のつく日」は、ポイントだけでなく商品の値段そのものも平均{d:.1f}%安くなっていました"
                       f"（記録{len(five_zero):,}件の比較）。")
        elif d <= -0.8:
            out.append(f"意外なことに、楽天の「5と0のつく日」は商品の値段そのものが平均{-d:.1f}%高めでした。"
                       f"ポイント分を差し引いて比べるのがおすすめです。")
    # 4) 評判の良い商品が、いま記録上の最安値
    for i, x in enumerate(popular[:10], 1):
        if x.get("is_all_time_low") and x.get("days", 0) >= 10:
            out.append(f"評判ランキング{i}位の「{_short_name(x['itemName'], 34)}」は、いま記録上の最安値"
                       f"（{_yen(x['price'])}）です。")
            break
    # 5) 値上がりへの注意
    up = [x for x in tracked if x.get("low") and x["price"] >= x["low"] * 1.10]
    if len(up) >= 3:
        out.append(f"一方で、{len(up)}件は記録上の最安値より10%以上高くなっています。"
                   f"値下がり中の商品と見比べてから選ぶと安心です。")
    return out


def _discovery_box(items: list[str], title: str = "毎日の記録から見つけた発見") -> str:
    if not items:
        return ""
    lis = "".join(f"<li>{E(s)}</li>" for s in items[:3])
    return (f'<section class="section discovery" aria-labelledby="h-disc"><p class="eyebrow">DISCOVERY</p>'
            f'<h2 id="h-disc">{E(title)}</h2><ul>{lis}</ul>'
            f'<p class="basis">当サイトが毎日記録している価格データから自動で集計しています。</p></section>')


def _week_trend(rich: list[dict]) -> str:
    """毎日の価格記録から、7日前と比べて安く/高くなった商品の数（このサイトにしかない数字）。"""
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    down = up = same = 0
    for it in rich:
        past = [r["price"] for r in it.get("history", []) if r["date"] <= week_ago]
        if not past:
            continue
        before = past[-1]
        if it["price"] < before:
            down += 1
        elif it["price"] > before:
            up += 1
        else:
            same += 1
    n = down + up + same
    if n < 5:
        return ""
    return (f"7日前から価格を記録している{n}件のうち、7日前より安くなったのは{down}件、"
            f"高くなったのは{up}件、変わらないのは{same}件です。")


def _genre_summary(g: dict, popular: list[dict], drops: list[dict], all_items: list[dict], updated: str,
                   rich: list[dict] | None = None) -> tuple[str, str]:
    """ページ冒頭の結論（AIに引用されやすい要約）と、metaに使う短文。"""
    top = popular[0] if popular else None
    lines = []
    if top:
        lines.append(f'評判が最も良いのは「{_short_name(top["itemName"], 40)}」（★{top["reviewAverage"]:.2f}、'
                     f'レビュー{top["reviewCount"]:,}件、{_yen(top["price"])}）。')
    if drops:
        d = drops[0]
        lines.append(f'値下がり中の商品は{len(drops)}件で、最も下がっているのは「{_short_name(d["itemName"], 40)}」'
                     f'（直近30日の参考価格{_yen(d["reference_price"])}→{_yen(d["price"])}、{d["drop_pct"]:.0f}%下落）。')
    else:
        lines.append("現在、直近30日の最高値から5%以上値下がりしている商品はありません。")
    wk = _week_trend(rich or [])
    if wk:
        lines.append(wk)
    lis = "".join(f"<li>{E(l)}</li>" for l in lines)
    html_ = (f'<section class="summary" aria-labelledby="h-summary"><h2 id="h-summary">結論：{E(updated)}時点の'
             f'{E(g["name"])}の買い時</h2><ul>{lis}</ul>'
             f'<span class="stamp muted">対象：楽天市場の{E(g["name"])} {len(all_items)}商品（★{MIN_AVG}以上・'
             f'レビュー{MIN_REVIEWS}件以上）を毎日記録</span></section>')
    return html_, " ".join(lines)


def _genre_faq(g: dict, popular: list[dict], drops: list[dict], updated: str) -> list[tuple[str, str]]:
    qas = []
    if popular:
        t = popular[0]
        qas.append((f"{g['name']}で一番評判が良い商品は？",
                    f"{updated}時点では「{_short_name(t['itemName'], 50)}」です。楽天市場でのレビュー評価は"
                    f"★{t['reviewAverage']:.2f}、レビュー数は{t['reviewCount']:,}件で、価格は{_yen(t['price'])}でした。"))
    if drops:
        d = drops[0]
        qas.append((f"今、値下がりしている{g['name']}は？",
                    f"{updated}時点で直近30日の最高値から5%以上下がっている商品は{len(drops)}件です。最も下がっているのは"
                    f"「{_short_name(d['itemName'], 50)}」で、{_yen(d['reference_price'])}から{_yen(d['price'])}"
                    f"（{d['drop_pct']:.0f}%）に下がっています。"))
    else:
        qas.append((f"今、{g['name']}は買い時？",
                    f"{updated}時点では、記録している商品に直近30日の最高値から5%以上の値下がりはありません。"
                    "急ぎでなければ、楽天のお買い物マラソンや5と0のつく日など、ポイントが多く付く日を待つのも一つの方法です。"))
    qas.append(("ランキングはどうやって決めていますか？",
                f"楽天市場のレビュー評価が★{MIN_AVG}以上かつレビュー{MIN_REVIEWS}件以上の商品を対象に、評価の高さと"
                "レビュー件数を掛け合わせた点数で機械的に順位を付けています。広告料によって順位を上下させることはありません。"))
    qas.append(("価格はどのくらいの頻度で更新されますか？",
                "毎日1回、楽天市場の価格を記録して更新しています。記録した日数が増えるほど、値下がりの判定や"
                "価格推移のグラフが正確になります。"))
    return qas


def build(items_by_genre: dict[str, list[dict]] | None = None) -> int:
    """サイト一式を書き出す。書き出したページ数を返す。"""
    import shutil

    from .price_history import load_all

    if items_by_genre is None:
        items_by_genre = json.loads(SITE_ITEMS_FILE.read_text(encoding="utf-8"))
    hist = load_all()
    now = datetime.now()
    updated = f"{now.year}年{now.month}月{now.day}日"
    today = date.today().isoformat()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "style.css").write_text(CSS, encoding="utf-8")
    (OUT_DIR / "favicon.svg").write_text(ICON_SVG, encoding="utf-8")
    if (ASSETS_DIR / "img").exists():
        shutil.copytree(ASSETS_DIR / "img", OUT_DIR / "img", dirs_exist_ok=True)

    pages = 0
    genre_data = {}
    yahoo_data: dict[str, list[dict]] = {}
    total_items = 0
    for g in GENRES:
        items = [it for it in items_by_genre.get(g["slug"], []) if _genre_ok(g, it)]
        total_items += len(items)
        popular, drops = rankings(items, hist)
        genre_data[g["slug"]] = (items, popular, drops)
        yitems = [it for it in items_by_genre.get(f"yahoo:{g['slug']}", []) if _genre_ok(g, it)]
        ypop = rankings(yitems, hist)[0] if yahoo_enabled() else []
        yahoo_data[g["slug"]] = ypop

    # ---- ジャンルページ
    for g in GENRES:
        items, popular, drops = genre_data[g["slug"]]
        path = f"/{g['slug']}/"
        img = GENRE_IMG.get(g["slug"], "hero")
        guides = _guides(g["slug"])
        cat = CAT_OF[g["slug"]]
        crumbs, crumbs_ld = _breadcrumb([("ホーム", "/"), (cat["name"], f"/c/{cat['slug']}/"),
                                         (f"{g['name']}の買い時", path)])
        rich = [_enrich(it, hist) for it in items]
        summary, summary_text = _genre_summary(g, popular, drops, items, updated, rich)
        disc = _discoveries(rich, popular)
        board = _drop_board(f"今の{g['name']}の値下がり状況", _drop_stats(rich, drops), drops,
                            _near_drops(rich), updated)
        faq_html, faq_ld = _faq(_genre_faq(g, popular, drops, updated))
        ypop = yahoo_data.get(g["slug"], [])
        rank_basis = (f"レビュー評価（★{MIN_AVG}以上・{MIN_REVIEWS}件以上）の高さと件数を掛け合わせた点数で順位付け"
                      f"（{updated}更新）。広告料による順位の上下はありません。")
        if ypop:
            ranking_body = f"""
  <div class="tabs" role="tablist">
    <button class="tab on" type="button" role="tab" aria-selected="true" data-tab="tab-rakuten">楽天市場</button>
    <button class="tab" type="button" role="tab" aria-selected="false" data-tab="tab-yahoo">Yahoo!ショッピング</button>
  </div>
  <div id="tab-rakuten" class="tabpane">{_rank_list(popular, "pop", "データを準備中です。")}</div>
  <div id="tab-yahoo" class="tabpane" hidden>{_rank_list(ypop, "yahoo", "データを準備中です。")}</div>"""
        else:
            ranking_body = _rank_list(popular, "pop", "データを準備中です。")
        pills = ['<a href="#drops">値下がり状況</a>', '<a href="#picks">こんな人に</a>',
                 '<a href="#ranking">評判ランキング</a>', '<a href="#compare">比較表</a>']
        if guides:
            pills.append('<a href="#guides">選び方ガイド</a>')
        pills.append('<a href="#faq">よくある質問</a>')
        guides_html = ""
        if guides:
            guides_html = ('<section class="section" id="guides" aria-labelledby="h-guides">'
                           '<p class="eyebrow">GUIDE</p><h2 id="h-guides">選び方ガイド</h2>'
                           '<ul class="guide-cards">' + "".join(_guide_card(g, x) for x in guides) + "</ul></section>")
        notice = f'<p class="notice">{E(g["notice"])}</p>' if g.get("notice") else ""
        body = f"""
<section class="banner" style="background-image:url('/img/{img}.jpg')"><div class="wrap">
{crumbs}<h1>{E(g["name"])}の買い時｜値下がり・評判ランキング</h1><p>{E(g["lead"])}</p></div></section>
<div class="wrap">
{board}
{notice}
<nav class="toc-pills" aria-label="ページ内リンク">{"".join(pills)}</nav>
{summary}
<section class="section feature" id="picks" aria-labelledby="h-picks">
  <p class="eyebrow">FOR YOU</p>
  <h2 id="h-picks">こんな人には、この{E(g["name"])}</h2>
  <p class="basis">評価・レビュー件数・価格・値下がりの記録と、商品名に書かれた仕様から選んでいます（{updated}更新）。</p>
  {_persona_picks(g, rich, popular, drops) or _today_picks(popular, drops)}
</section>
<section class="section" id="ranking" aria-labelledby="h-ranking">
  <p class="eyebrow">RANKING</p>
  <h2 id="h-ranking">評判の良い{E(g["name"])}ランキング TOP{len(popular)}</h2>
  <p class="basis">{rank_basis}</p>
  {ranking_body}
</section>
{_a8_box(g)}
{_discovery_box(disc)}
<section class="section" id="compare" aria-labelledby="h-compare">
  <details class="compare-box"><summary><span id="h-compare" class="h2like">ランキング上位の比較表を見る</span></summary>
  {_compare_table(popular)}
  </details>
</section>
{guides_html}
{faq_html}
{_related_genres(g["slug"], genre_data)}
</div>"""
        ld = _jsonld(crumbs_ld, faq_ld,
                     _itemlist_ld(f"評判の良い{g['name']}ランキング", popular, path),
                     {"@context": "https://schema.org", "@type": "CollectionPage",
                      "name": f"{g['name']}の買い時｜値下がり・評判ランキング", "url": f"{SITE_URL}{path}",
                      "dateModified": today, "description": summary_text, "publisher": PUBLISHER})
        _write(path, _page(f"{g['name']}の買い時｜値下がり・評判ランキング【{now.year}年{now.month}月】", body,
                           f"{summary_text} 楽天市場の{g['name']}{len(items)}商品の価格を毎日記録して、値下がり中の商品と評判の良い商品をまとめています。"[:150],
                           path, current=g["slug"], og_image=f"/img/{img}.jpg", ld=ld))
        pages += 1

        # ---- ガイド記事
        for x in guides:
            apath = f"{path}{x['slug']}/"
            art_html, toc = _md_to_html(x["md"])
            head = x["title"].split("｜")[0]
            answer = _guide_answer(x["md"])
            published = _guide_published(g["slug"], x["slug"], x["updated"])
            page_title = x["title"] if len(x["title"]) <= 38 else head
            page_desc = x["desc"] if len(x["desc"]) >= 50 or not answer else f"{x['desc']} {answer}"
            question = (head.replace("の選び方", "") + "はどう選べばいい？") if head.endswith("の選び方") else f"{head}のポイントは？"
            crumbs_a, crumbs_a_ld = _breadcrumb([("ホーム", "/"), (cat["name"], f"/c/{cat['slug']}/"),
                                                 (f"{g['name']}の買い時", path), (x["title"], apath)])
            toc_html = ('<nav class="toc" aria-label="目次"><b>目次</b><ol>' + "".join(
                f'<li><a href="#{hid}">{E(t)}</a></li>' for hid, t in toc) + "</ol></nav>") if len(toc) >= 2 else ""
            body = f"""
<section class="banner" style="background-image:url('/img/{img}.jpg')"><div class="wrap">
{crumbs_a}<h1>{E(x["title"])}</h1></div></section>
<div class="wrap">
{notice}
<article class="article" style="margin-top:24px">
<div class="byline"><span>公開日：<time datetime="{published}">{published}</time></span><span>更新日：<time datetime="{x["updated"]}">{x["updated"]}</time></span><span>書いた人：aki.h190（{SITE_NAME}運営）</span><span class="pr">PR含む</span></div>
{toc_html}
{art_html}
</article>
{_a8_box(g)}
<section class="section" aria-labelledby="h-rel"><h2 id="h-rel">いま評判の良い{E(g["name"])} TOP5</h2>
<p class="basis">{updated}更新。詳しくは<a href="{path}#ranking">{E(g["name"])}の評判ランキング</a>へ。</p>
{_rank_list(popular[:5], "pop", "データを準備中です。")}</section>
{_discovery_box(disc, f"{g['name']}の価格記録から見つけた発見")}
{_related_genres(g["slug"], genre_data)}
</div>"""
            faq_ld = ({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
                {"@type": "Question", "name": question, "acceptedAnswer": {"@type": "Answer", "text": answer}}]}
                if answer else None)
            ld = _jsonld(crumbs_a_ld, *([faq_ld] if faq_ld else []), {"@context": "https://schema.org", "@type": "Article", "headline": x["title"],
                                        "description": x["desc"], "datePublished": published, "dateModified": x["updated"],
                                        "image": f"{SITE_URL}/img/{img}.jpg", "mainEntityOfPage": f"{SITE_URL}{apath}",
                                        "author": AUTHOR,
                                        "publisher": PUBLISHER})
            _write(apath, _page(page_title, body, page_desc, apath, current=g["slug"],
                                og_image=f"/img/{img}.jpg", ld=ld, og_type="article"))
            pages += 1

    # ---- カテゴリのまとめページ
    for c in CATEGORIES:
        cpath = f"/c/{c['slug']}/"
        gs = _cat_genres(c)
        c_items = [it for g in gs for it in genre_data[g["slug"]][0]]
        c_drops = sorted((d for g in gs for d in genre_data[g["slug"]][2]), key=lambda d: d["drop_pct"], reverse=True)
        c_rich = [_enrich(it, hist) for it in c_items]
        crumbs_c, crumbs_c_ld = _breadcrumb([("ホーム", "/"), (c["name"], cpath)])
        hot = [g for g in sorted(gs, key=lambda g: len(genre_data[g["slug"]][2]), reverse=True)
               if genre_data[g["slug"]][2]][:4]
        hot_html = ('<div class="db-hot"><span>値下がりが多いジャンル</span>' + "".join(
            f'<a href="/{g["slug"]}/#drops">{g["emoji"]} {E(g["name"])} <b>{len(genre_data[g["slug"]][2])}件</b></a>'
            for g in hot) + "</div>") if hot else ""
        board_c = _drop_board(f"{c['name']}の値下がり状況", _drop_stats(c_rich, c_drops), c_drops[:16],
                              _near_drops(c_rich), updated, extra=hot_html)
        tops = "".join(
            f'<li><a href="/{g["slug"]}/#ranking"><b>{g["emoji"]} {E(g["name"])}</b>'
            f'<span>{E(_short_name(genre_data[g["slug"]][1][0]["itemName"], 44))}</span>'
            f'<em>{genre_data[g["slug"]][1][0]["price"]:,}円・★{genre_data[g["slug"]][1][0]["reviewAverage"]:.2f}</em></a></li>'
            for g in gs if genre_data[g["slug"]][1])
        c_guides = [(g, x) for g in gs for x in _guides(g["slug"])]
        guides_c = ('<section class="section"><p class="eyebrow">GUIDE</p><h2>選び方ガイド</h2><ul class="guide-cards">'
                    + "".join(_guide_card(g, x) for g, x in c_guides) + "</ul></section>") if c_guides else ""
        others = "".join(f'<a href="/c/{o["slug"]}/">{o["emoji"]} {E(o["name"])}</a>' for o in CATEGORIES if o is not c)
        c_summary = (f"{updated}時点で、{c['name']}の{len(gs)}ジャンル・{len(c_items)}商品の価格を記録しています。"
                     f"直近30日の最高値から5%以上値下がりしている商品は{len(c_drops)}件です。")
        cimg = GENRE_IMG.get(gs[0]["slug"], "hero")
        body = f"""
<section class="banner" style="background-image:url('/img/{cimg}.jpg')"><div class="wrap">
{crumbs_c}<h1>{E(c["name"])}の買い時｜値下がり・評判ランキング</h1><p>{E("・".join(g["name"] for g in gs))}の価格を毎日記録しています。</p></div></section>
<div class="wrap">
{board_c}
<section class="summary" aria-labelledby="h-csum"><h2 id="h-csum">結論：{E(updated)}時点の{E(c["name"])}</h2><p>{E(c_summary)}</p></section>
<section class="section related"><p class="eyebrow">CATEGORY</p><h2>{E(c["name"])}のジャンル</h2>
<div class="gcards">{"".join(_gcard_small(g, genre_data) for g in gs)}</div></section>
<section class="section"><p class="eyebrow">RANKING</p><h2>ジャンルごとの評判No.1</h2><ul class="cat-tops">{tops}</ul></section>
{guides_c}
<div class="chipgroups"><p class="chipgroups-h">ほかのカテゴリ</p><div class="chipgroup">{others}</div></div>
</div>"""
        ld_c = _jsonld(crumbs_c_ld, {
            "@context": "https://schema.org", "@type": "CollectionPage", "name": f"{c['name']}の買い時",
            "url": f"{SITE_URL}{cpath}", "dateModified": today, "description": c_summary, "publisher": PUBLISHER,
            "mainEntity": {"@type": "ItemList", "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "url": f"{SITE_URL}/{g['slug']}/", "name": f"{g['name']}の買い時"}
                for i, g in enumerate(gs)]}})
        _write(cpath, _page(f"{c['name']}の買い時｜値下がり・評判ランキング【{now.year}年{now.month}月】", body,
                            f"{c_summary} {'・'.join(g['name'] for g in gs)}の値下がり中の商品と評判ランキングをまとめています。"[:150],
                            cpath, current=gs[0]["slug"] if False else "", og_image=f"/img/{cimg}.jpg", ld=ld_c))
        pages += 1

    # ---- トップページ
    top_drops = sorted(((g, d) for g in GENRES for d in genre_data[g["slug"]][2][:3]),
                       key=lambda gd: gd[1]["drop_pct"], reverse=True)[:16]
    cards = "".join(
        f'<h3 class="cat-h" id="c-{c["slug"]}"><a href="/c/{c["slug"]}/">{c["emoji"]} {E(c["name"])}<span>まとめを見る →</span></a></h3>'
        f'<div class="gcards">{"".join(_gcard_small(g, genre_data) for g in _cat_genres(c))}</div>'
        for c in CATEGORIES)
    guides_all = [(g, x) for g in GENRES for x in _guides(g["slug"])]
    first_per_genre, seen_g = [], set()
    for g, x in guides_all:
        if g["slug"] not in seen_g:
            seen_g.add(g["slug"])
            first_per_genre.append((g, x))
    guides_home = ('<section class="section" aria-labelledby="h-g"><p class="eyebrow">GUIDE</p>'
                   '<h2 id="h-g">選び方ガイド</h2><ul class="guide-cards">'
                   + "".join(_guide_card(g, x) for g, x in first_per_genre[:6]) + "</ul></section>") if guides_all else ""
    n_drops = sum(len(v[2]) for v in genre_data.values())
    all_rich = [_enrich(it, hist) for g in GENRES for it in genre_data[g["slug"]][0]]
    # ほっといても売れている定番：レビュー1万件以上・★4.3以上で、毎日の記録が2週間以上ある商品
    seen_ev, ever = set(), []
    for x in sorted(all_rich, key=lambda x: x.get("reviewCount", 0), reverse=True):
        key = x.get("itemCode") or x.get("itemUrl")
        if key in seen_ev or x.get("reviewCount", 0) < 10000 or x.get("reviewAverage", 0) < 4.3 or x.get("days", 0) < 14:
            continue
        seen_ev.add(key)
        ever.append(x)
    ever = ever[:12]
    evergreen_html = ((f'<section class="section" id="evergreen" aria-labelledby="h-ever"><p class="eyebrow">LONG SELLER</p>'
                       f'<h2 id="h-ever">ほっといても売れている定番</h2>'
                       f'<p class="basis">レビュー1万件以上・★4.3以上で、当サイトが2週間以上毎日記録している商品です。'
                       f'セールを待たなくても選ばれ続けている、失敗の少ない定番です（{updated}更新）。</p>'
                       + _hscroll(ever, "ever", "") + "</section>") if len(ever) >= 4 else "")
    all_drops = [d for _, d in top_drops]
    hot = sorted(GENRES, key=lambda g: len(genre_data[g["slug"]][2]), reverse=True)
    hot = [g for g in hot if genre_data[g["slug"]][2]][:4]
    hot_html = ('<div class="db-hot"><span>値下がりが多いジャンル</span>' + "".join(
        f'<a href="/{g["slug"]}/#drops">{g["emoji"]} {E(g["name"])} <b>{len(genre_data[g["slug"]][2])}件</b></a>'
        for g in hot) + "</div>") if hot else ""
    home_board = _drop_board("今日の値下がり状況（全ジャンル）",
                             {**_drop_stats(all_rich, all_drops), "n": n_drops}, all_drops,
                             _near_drops(all_rich), updated, extra=hot_html)
    home_summary = (f"{updated}時点で、{len(GENRES)}ジャンル{total_items}商品の価格を記録しています。"
                    f"直近30日の最高値から5%以上値下がりしている商品は{n_drops}件です。")
    body = f"""
<section class="hero" style="background-image:url('/img/hero.jpg')"><div class="wrap">
<h1>毎日の価格記録で、<br>暮らしの「買い時」が分かる。</h1>
<p>水・お米・コンタクト・おむつ・コーヒー・寝具など、毎日の暮らしの定番の価格を毎日記録。値下がりしているものと、評判の良いものを、数字の根拠つきでまとめています。</p>
<div class="chips"><span class="chip"><b>{total_items}</b>商品を記録中</span><span class="chip"><b>{n_drops}</b>件が値下がり中</span><span class="chip">毎朝更新</span></div>
</div></section>
<div class="wrap">
{_instagram_strip()}
{home_board}
{evergreen_html}
<section class="section related" aria-labelledby="h-genres"><p class="eyebrow">CATEGORY</p>
<h2 id="h-genres">カテゴリから探す</h2>{cards}</section>
{_discovery_box(_discoveries(all_rich, []), "全ジャンルの価格記録から見つけた発見")}
{guides_home}
</div>"""
    ld = _jsonld({"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME, "url": SITE_URL,
                  "potentialAction": {"@type": "SearchAction", "target": f"{SITE_URL}/search/?q={{search_term_string}}",
                                      "query-input": "required name=search_term_string"},
                  "description": home_summary, "inLanguage": "ja", "publisher": PUBLISHER})
    _write("/", _page(SITE_NAME, body, f"{home_summary} 楽天市場の暮らしの定番アイテムの価格を毎日記録して、値下がりと評判から買い時をお知らせします。",
                      "/", ld=ld))
    pages += 1

    # ---- 運営情報・プライバシー
    about = f"""
<section class="banner" style="background-image:url('/img/hero.jpg')"><div class="wrap">
{_breadcrumb([("ホーム", "/"), ("このサイトについて", "/about/")])[0]}<h1>このサイトについて</h1></div></section>
<div class="wrap"><article class="article" style="margin-top:24px">
<h2>買い時ナビとは</h2>
<p>水・お米・コンタクトレンズ・おむつ・コーヒー・寝具・キッチン用品・ペット用品など、毎日の暮らしで使う定番アイテムの価格を毎日記録し、「今が買い時か」を数字で判断できるようにまとめたサイトです。値下がりの判定には、当サイトが独自に毎日記録している価格データを使っています。</p>
<h2>ランキングの根拠</h2>
<ul>
<li>商品データは楽天市場（楽天ウェブサービスAPI）から毎日取得しています。</li>
<li>「値下がり」は、当サイトが記録した価格のうち直近30日の最高値と、更新時点の価格を比べた下落率です。記録が2日分以上ある商品が対象です。</li>
<li>「記録上の最安値」は、当サイトが記録を始めてからの最安値であることを示します（記録7日以上の商品のみ表示）。</li>
<li>「評判の良い」ランキングは、レビュー評価★{MIN_AVG}以上・レビュー{MIN_REVIEWS}件以上の商品を、評価の高さとレビュー件数を掛け合わせた点数で並べています。</li>
<li>順位はこれらの数値だけで機械的に決めており、広告料などによって順位を上下させることはありません。</li>
</ul>
<h2>広告について</h2>
<p>当サイトのリンクの多くはアフィリエイトリンク（楽天アフィリエイト・A8.net・バリューコマース）です。リンク経由で購入・申込があった場合、当サイトに報酬が支払われることがあります。報酬の有無はランキングの順位に影響しません。</p>
<h2>編集方針</h2>
<ul>
<li><b>価格データ</b>：楽天市場（楽天ウェブサービスAPI）とYahoo!ショッピング（Yahoo!デベロッパーネットワークAPI）から毎朝自動で取得し、当サイトで価格を記録しています。人の手で数字を書き換えることはありません。</li>
<li><b>選び方ガイド</b>：メーカーの公開情報や、国・業界団体などの公的な情報をもとに、選ぶときの考え方をまとめています。使ってもいない商品を「使ってみた」と書くことはしません。</li>
<li><b>表現への配慮</b>：健康・美容・体への効果をうたう表現（医薬品的な効能など）は使いません。安全に関わる商品（チャイルドシートなど）は、法律や安全基準の情報を優先して記載しています。</li>
<li><b>間違いの訂正</b>：内容に誤りがあった場合は、確認でき次第すみやかに修正します。お気づきの点は下記の連絡先までお知らせください。</li>
</ul>
<h2>運営者</h2>
<p>aki.h190。毎日の暮らしで使う定番アイテムを「いつ買うのがお得か」の視点で調べ、Instagram・Threadsで「日々のくらしで見つけた、これ良かった」を発信しています。</p>
<ul>
<li>Instagram：<a href="https://www.instagram.com/aki.h190/" target="_blank" rel="noopener">@aki.h190</a></li>
<li>Threads：<a href="https://www.threads.net/@aki.h190" target="_blank" rel="noopener">@aki.h190</a></li>
</ul>
<h2>お問い合わせ</h2>
<p>内容の誤りのご指摘や掲載についてのご連絡は、InstagramまたはThreadsのメッセージ（DM）からお送りください。</p>
<h2>写真について</h2>
<p>当サイトのイメージ写真は <a href="https://unsplash.com/" target="_blank" rel="noopener">Unsplash</a> のフリー素材を使用しています。商品画像は楽天市場の各ショップのものです。</p>
</article></div>"""
    _write("/about/", _page("このサイトについて・ランキングの根拠", about, "買い時ナビの運営者、ランキングと値下がり判定の根拠、広告についての説明", "/about/",
                           ld=_jsonld(_breadcrumb([("ホーム", "/"), ("このサイトについて", "/about/")])[1],
                                      {"@context": "https://schema.org", "@type": "AboutPage", "name": "このサイトについて",
                                       "url": f"{SITE_URL}/about/", "publisher": PUBLISHER})))
    yahoo_privacy = ('<tr><td>株式会社バリューコマース（Yahoo!ショッピング・各ショップのアフィリエイト、LinkSwitch）</td>'
                     '<td>リンクのクリック情報、Cookie識別子、閲覧ページのURL</td><td>成果報酬の計測</td></tr>')
    privacy = f"""
<section class="banner" style="background-image:url('/img/hero.jpg')"><div class="wrap">
{_breadcrumb([("ホーム", "/"), ("プライバシーポリシー", "/privacy/")])[0]}<h1>プライバシーポリシー</h1></div></section>
<div class="wrap"><article class="article" style="margin-top:24px">
<p>当サイトでは、お問い合わせ等で取得した個人情報を、本人の同意なく第三者に提供することはありません。</p>
<p>当サイトはアフィリエイトプログラム（楽天アフィリエイト・A8.net・バリューコマース）を利用しています。リンクのクリックや購入の計測のため、提携先がCookieを使用することがあります。Cookieはブラウザの設定で無効にできます。</p>
<h2>アクセス解析ツールについて</h2>
<p>当サイトでは、サイトの利用状況を把握して改善するために、Google LLCのアクセス解析ツール「Googleアナリティクス」を使用しています。Googleアナリティクスは、Cookieを使って、閲覧したページ、滞在時間、どのページのリンクがクリックされたかといった情報を収集します。収集される情報に、氏名など個人を特定する情報は含まれません。</p>
<p>この機能はブラウザのCookieを無効にすることで拒否できます。詳しくは<a href="https://marketingplatform.google.com/about/analytics/terms/jp/" target="_blank" rel="noopener">Googleアナリティクス利用規約</a>と<a href="https://policies.google.com/technologies/partner-sites?hl=ja" target="_blank" rel="noopener">Googleのサービスを使用するサイトやアプリから収集した情報のGoogleによる使用</a>をご確認ください。</p>
<h2>外部送信される情報について</h2>
<table><thead><tr><th>送信先</th><th>送信される情報</th><th>目的</th></tr></thead><tbody>
<tr><td>Google LLC（Googleアナリティクス）</td><td>閲覧ページのURL、リファラー、端末・ブラウザの情報、Cookie識別子、クリックしたリンク</td><td>アクセス解析・サイト改善</td></tr>{yahoo_privacy}
<tr><td>楽天グループ株式会社（楽天アフィリエイト）</td><td>リンクのクリック情報、Cookie識別子</td><td>成果報酬の計測</td></tr>
<tr><td>株式会社ファンコミュニケーションズ（A8.net）</td><td>リンクのクリック情報、Cookie識別子</td><td>成果報酬の計測</td></tr>
</tbody></table>
<p>当サイトの掲載内容は正確さに努めていますが、価格・在庫等は変動するため、購入前に必ず販売ページでご確認ください。</p>
</article></div>"""
    _write("/privacy/", _page("プライバシーポリシー", privacy, "買い時ナビのプライバシーポリシー。個人情報とCookieの扱い、アフィリエイトについて", "/privacy/",
                             ld=_jsonld(_breadcrumb([("ホーム", "/"), ("プライバシーポリシー", "/privacy/")])[1])))
    pages += 2

    # ---- 404（存在しないURLに来た人をトップ・カテゴリへ案内。Caddy の handle_errors で返す）
    nf = f"""
<div class="wrap"><section class="section" style="margin-top:28px"><p class="eyebrow">404</p>
<h1 style="font-size:24px">お探しのページが見つかりませんでした</h1>
<p>ページが移動したか、URLが間違っている可能性があります。下のカテゴリや検索から探してみてください。</p>
<form class="sbox" action="/search/" method="get" role="search" style="margin:12px 0 16px;max-width:560px"><input type="search" name="q" placeholder="商品名・ジャンルで探す" aria-label="サイト内検索"><button type="submit">検索</button></form>
<div class="chipgroups"><p class="chipgroups-h">カテゴリから探す</p><div class="chipgroup">{"".join(f'<a href="/c/{c["slug"]}/">{c["emoji"]} {E(c["name"])}</a>' for c in CATEGORIES)}</div></div>
<p style="margin-top:16px"><a href="/">トップページへ戻る</a></p></section></div>"""
    (OUT_DIR / "404.html").write_text(_page("ページが見つかりません", nf, "お探しのページが見つかりませんでした。", "/404.html",
                                            noindex=True), encoding="utf-8")

    # ---- サイト内検索
    (OUT_DIR / "search.json").write_text(json.dumps(_search_index(genre_data), ensure_ascii=False,
                                                    separators=(",", ":")), encoding="utf-8")
    search = f"""
<div class="wrap"><section class="section" style="margin-top:24px"><h1 style="font-size:24px">サイト内検索</h1>
<form class="sbox" id="sform" role="search" style="margin:12px 0 16px;max-width:560px"><input type="search" id="sq" name="q" placeholder="商品名・ジャンルで探す" aria-label="検索キーワード"><button type="submit">検索</button></form>
<p class="basis" id="smsg">読み込み中…</p><ul class="sresult" id="sres"></ul>
<p class="basis" style="margin-top:20px">見つからないときは、ジャンルから探してみてください。</p></section>
{_related_genres("", genre_data)}</div>
<script>{SEARCH_JS}</script>"""
    _write("/search/", _page("サイト内検索", search, "買い時ナビのサイト内検索", "/search/", noindex=True))
    pages += 1

    # ---- sitemap / robots / llms.txt
    # lastmod は実際に中身が変わる日に。毎日データが変わるページは今日、ガイドは書いた日、運営情報は固定
    urls = ([("/", today), ("/about/", ABOUT_UPDATED), ("/privacy/", ABOUT_UPDATED)]
            + [(f"/c/{c['slug']}/", today) for c in CATEGORIES]
            + [(f"/{g['slug']}/", today) for g in GENRES]
            + [(f"/{g['slug']}/{x['slug']}/", x["updated"]) for g, x in guides_all])
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               + "".join(f"<url><loc>{SITE_URL}{u}</loc><lastmod>{lm}</lastmod></url>" for u, lm in urls)
               + "</urlset>\n")
    (OUT_DIR / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    (OUT_DIR / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n", encoding="utf-8")
    llms = [f"# {SITE_NAME}", "",
            f"> 楽天市場の暮らしの定番アイテム（{'・'.join(g['name'] for g in GENRES)}）の価格を毎日記録し、"
            "値下がり中の商品と評判の良い商品を数字の根拠つきでまとめた日本語の比較サイト。", "",
            f"- 最終更新: {today}", f"- 記録中の商品数: {total_items}", f"- 全ガイドの結論と見出し: {SITE_URL}/llms-full.txt",
            "- 値下がりの定義: 直近30日に記録した最高値と比べて5%以上安い", f"- 評判ランキングの対象: 楽天のレビュー★{MIN_AVG}以上かつ{MIN_REVIEWS}件以上",
            "", "## カテゴリ別ページ"] + [
        f"- [{c['name']}の買い時]({SITE_URL}/c/{c['slug']}/): {'・'.join(GENRE_BY_SLUG[s]['name'] for s in c['genres'])}"
        for c in CATEGORIES] + ["", "## ジャンル別ページ"]
    for g in GENRES:
        items, popular, drops = genre_data[g["slug"]]
        top = f"評判1位: {_short_name(popular[0]['itemName'], 40)}（★{popular[0]['reviewAverage']:.2f}）" if popular else ""
        llms.append(f"- [{g['name']}の買い時]({SITE_URL}/{g['slug']}/): 値下がり中{len(drops)}件。{top}")
    if guides_all:
        llms += ["", "## 選び方ガイド"] + [f"- [{x['title']}]({SITE_URL}/{g['slug']}/{x['slug']}/): {x['desc']}"
                                       for g, x in guides_all]
    llms += ["", "## 運営情報", f"- [ランキングの根拠と運営者]({SITE_URL}/about/)"]
    (OUT_DIR / "llms.txt").write_text("\n".join(llms) + "\n", encoding="utf-8")

    # 新しいガイドの RSS（クローラーやフィードリーダーが新着に気づけるように）
    from email.utils import format_datetime
    feed_items = sorted(((_guide_published(g["slug"], x["slug"], x["updated"]), g, x) for g, x in guides_all),
                        key=lambda r: r[0], reverse=True)[:40]
    def _rfc(d):
        return format_datetime(datetime.fromisoformat(d + "T07:00:00+09:00"))
    rss = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0"><channel>',
           f"<title>{E(SITE_NAME)} 選び方ガイド</title>", f"<link>{SITE_URL}/</link>",
           "<description>楽天市場の暮らしの定番アイテムの選び方ガイド（価格は毎日記録）</description>", "<language>ja</language>"]
    for pub, g, x in feed_items:
        u = f"{SITE_URL}/{g['slug']}/{x['slug']}/"
        rss.append(f"<item><title>{E(x['title'])}</title><link>{u}</link><guid>{u}</guid>"
                   f"<pubDate>{_rfc(pub)}</pubDate><description>{E(x['desc'])}</description></item>")
    rss.append("</channel></rss>")
    (OUT_DIR / "feed.xml").write_text("\n".join(rss) + "\n", encoding="utf-8")

    # llms-full.txt: ガイドの結論と見出し、ジャンルの評判上位を1ファイルに（AIの要約・引用向け）
    full = [f"# {SITE_NAME}（全文要約）", "", f"最終更新: {today}。価格は楽天市場の商品を毎日記録したもの。", ""]
    for g in GENRES:
        items, popular, drops = genre_data[g["slug"]]
        full.append(f"## {g['name']}（{SITE_URL}/{g['slug']}/）")
        full.append(g["lead"])
        for i, it in enumerate(popular[:3], 1):
            full.append(f"- 評判{i}位: {_short_name(it['itemName'], 50)}（{it['price']:,}円、★{it['reviewAverage']:.2f}・{it['reviewCount']:,}件）")
        full.append(f"- 値下がり中: {len(drops)}件（直近30日の最高値から5%以上安い）")
        for x in _guides(g["slug"]):
            full.append(f"### {x['title']}（{SITE_URL}/{g['slug']}/{x['slug']}/）")
            ans = _guide_answer(x["md"])
            if ans:
                full.append(f"結論: {ans}")
            heads = [l[3:].strip() for l in x["md"].splitlines() if l.startswith("## ")]
            if heads:
                full.append("見出し: " + " / ".join(heads))
        full.append("")
    (OUT_DIR / "llms-full.txt").write_text("\n".join(full) + "\n", encoding="utf-8")
    return pages

"""楽天ROOMの投稿を、テーマ別のコレクションに自動で振り分ける（2026-10-13 追加）。

プロフィールに来た人がテーマから商品を探せるようにするためのもの。投稿のたびに増える新しい投稿を、
商品名の先頭に出てくる語でテーマを判定して、該当するコレクションに追加する。
コレクションはテーマごとに、最初に該当する投稿が見つかったときに作る。

ROOMの画面が使っている内部API（app.min.js から確認）:
  作成  POST /api/collection/            name, img_icon, about, collects=投稿ID,投稿ID…
  追加  POST /api/{コレクションID}/collect  collect_id=投稿ID
  （1アカウントのコレクション数の上限は200）
"""
from __future__ import annotations

import json
import random
import time
from datetime import datetime
from urllib.parse import urlencode

from .config import DATA_DIR
from .engage import _api_get, _api_session
from .poster import _launch

STATE = DATA_DIR / "room_collections.json"
API = "https://room.rakuten.co.jp/api"
# 自動削除（prune）の対象になる古い投稿は入れない
MIN_CREATED = "2025-01-01"

# 上から順に判定し、最初に当てはまったテーマに入れる（細かいテーマを先に）
THEMES = [
    {"slug": "pet", "name": "ペットと暮らす", "about": "犬・猫と暮らす人に気になる、フードや猫砂などのペット用品を集めました。",
     "words": ["ペット", "猫砂", "キャットフード", "ドッグフード", "犬用", "猫用", "ねこ", "いぬ"]},
    {"slug": "baby", "name": "子育て・キッズ", "about": "おむつやおしりふき、子どもの毎日に欲しいものを集めました。",
     "words": ["おむつ", "オムツ", "おしりふき", "ベビー", "赤ちゃん", "キッズ", "子供用", "子ども用", "ランドセル", "知育",
               "授乳", "ほほえみ", "粉ミルク", "抱っこ", "ベビーカー"]},
    {"slug": "sweets", "name": "スイーツ・お菓子", "about": "見つけるとつい欲しくなる、スイーツとお菓子のコレクションです。",
     "words": ["チョコ", "スイーツ", "ケーキ", "和菓子", "クッキー", "プリン", "バウム", "どら焼き", "お菓子", "アイス"]},
    {"slug": "gift", "name": "ギフト・お歳暮", "about": "お歳暮や内祝い、ちょっとしたお礼に選びたいギフトを集めました。",
     "words": ["お歳暮", "御歳暮", "ギフト", "内祝い", "カタログギフト", "贈り物", "プレゼント"]},
    {"slug": "winter", "name": "冬のあったかグッズ", "about": "寒い季節に欲しい、カイロ・毛布・暖房グッズを集めました。",
     "words": ["カイロ", "毛布", "ブランケット", "ヒーター", "こたつ", "湯たんぽ", "ネックウォーマー", "暖房",
               "加湿器", "着る毛布", "あったか", "防寒"],
     "exclude": ["サンダル", "冷感", "夏用"]},
    {"slug": "food", "name": "お米・食品のストック", "about": "お米や飲み物、レトルトなど、まとめ買いしたい食品を集めました。",
     "words": ["米", "パックご飯", "レトルト", "カップ麺", "ラーメン", "ミネラルウォーター", "天然水", "炭酸水",
               "お茶", "コーヒー", "肉", "カニ", "みかん", "冷凍", "調味料", "醤油", "オイル", "ふるさと納税",
               "おせち", "果物", "フルーツ", "柿", "シャインマスカット", "ぶどう", "りんご", "いちご", "梨", "惣菜"]},
    {"slug": "daily", "name": "日用品のまとめ買い", "about": "トイレットペーパーや洗剤など、なくなる前に買っておきたい日用品です。",
     "words": ["トイレットペーパー", "ティッシュ", "洗剤", "柔軟剤", "ゴミ袋", "ごみ袋", "キッチンペーパー", "ラップ",
               "歯ブラシ", "電池", "マスク", "シャンプー", "ボディソープ", "ハンドソープ", "掃除", "コンタクト",
               "コピー用紙", "文房具", "ボールペン"]},
    {"slug": "kitchen", "name": "キッチン用品", "about": "毎日の料理がちょっとラクになりそうな、キッチン用品を集めました。",
     "words": ["フライパン", "鍋", "保存容器", "包丁", "まな板", "ケトル", "水筒", "タンブラー", "食器", "キッチン"]},
    {"slug": "kaden", "name": "家電・ガジェット", "about": "暮らしを便利にしてくれそうな家電やガジェットを集めました。",
     "words": ["掃除機", "炊飯器", "電子レンジ", "ドライヤー", "イヤホン", "充電器", "モバイルバッテリー", "ケーブル",
               "スマホ", "タブレット", "モニター", "マウス", "キーボード", "家電", "空気清浄機", "サーキュレーター",
               "パソコン", "ノートPC", "Fire TV", "プレーヤー", "テレビ", "スピーカー", "カメラ", "プリンター"]},
    {"slug": "home", "name": "インテリア・寝具", "about": "部屋を心地よくしてくれそうな、インテリアや寝具を集めました。",
     "words": ["収納", "ラグ", "カーテン", "クッション", "布団", "枕", "マットレス", "シーツ", "ソファ", "ライト", "照明",
               "タオル", "ハンガー"]},
    {"slug": "sports", "name": "スポーツ・アウトドア・旅行", "about": "体を動かす日やお出かけ・旅行に欲しいものを集めました。",
     "words": ["自転車", "クロスバイク", "ヨガマット", "フォームローラー", "ゴルフ", "スーツケース", "キャリーケース",
               "レジャーシート", "ランニング", "トレーニング", "キャンプ", "アウトドア", "テント", "バランスボール", "バランスドーム"]},
    {"slug": "fashion", "name": "ファッション・靴", "about": "着回しやすい服や靴、毎日使いたいファッション小物を集めました。",
     "words": ["レディース", "メンズ", "シャツ", "ニット", "ブルゾン", "アウター", "ジャケット", "コート", "スニーカー",
               "シューズ", "革靴", "サンダル", "スリッポン", "ブーツ", "バッグ", "リュック", "ワンピース", "財布", "帽子"]},
    {"slug": "beauty", "name": "コスメ・美容グッズ", "about": "評判の良いコスメや、身だしなみに使う美容グッズを集めました。",
     "words": ["コスメ", "ファンデ", "パウダー", "リップ", "アイシャドウ", "マスカラ", "化粧", "スキンケア", "美容",
               "ヘアアイロン", "ドライヤー", "アイラッシュ", "ネイル", "香水", "リファ"]},
]


def _theme_of(name: str) -> dict | None:
    head = (name or "")[:50]
    for t in THEMES:
        if any(w in head for w in t.get("exclude", [])):
            continue
        if any(w in head for w in t["words"]):
            return t
    return None


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save(state: dict) -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def _post(page, url: str, body: str) -> dict:
    res = page.evaluate(
        """([u,b])=>fetch(u,{method:'POST',credentials:'include',
            headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'},
            body:b}).then(r=>r.text().then(t=>({s:r.status,t})))""", [url, body])
    try:
        j = json.loads(res.get("t") or "{}")
    except ValueError:
        j = {}
    j["_status"] = res.get("s")
    j["_text"] = (res.get("t") or "")[:200]
    return j


def _check_survival(page, uid: str, tok: str, days: int = 3) -> None:
    """直近の投稿が実際にROOMに残っているかを、投稿記録（posted.json）と日付ごとに比べる。
    残りが投稿数の8割を切った日があれば通知する（2026-10-13に、投稿の大半が削除ジョブで
    消えていたのに1か月以上気づかなかったことの再発防止）。"""
    from collections import Counter
    from datetime import date, timedelta
    from .notify import notify
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    try:
        posted = json.loads((DATA_DIR / "posted.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return
    want = Counter((x.get("posted_at") or "")[:10] for x in posted
                   if x.get("kind") == "posted" and (x.get("posted_at") or "")[:10] >= since)
    have: Counter = Counter()
    for pg in range(60):
        data = _api_get(page, f"{API}/{uid}/collects?api_version=1&limit=20&offset={pg * 20}&csrf_tkn={tok}").get("data") or []
        if not data:
            break
        days_ = [(c.get("created_at") or "")[:10] for c in data]
        have.update(d for d in days_ if d >= since)
        if min(days_) < since:
            break
        time.sleep(random.uniform(0.6, 1.2))
    lines, bad = [], False
    for d in sorted(want):
        ok = have.get(d, 0) >= want[d] * 0.8
        bad |= not ok
        lines.append(f"{d}: 投稿 {want[d]} / 残り {have.get(d, 0)}{'' if ok else ' ←少ない'}")
    print("  投稿の残り確認: " + " ／ ".join(lines))
    if bad:
        notify("ROOMの投稿が想定より消えています。\n" + "\n".join(lines), title="ROOM posts missing")


def collections_round(cfg: dict, slug: str, max_add: int = 150, max_pages: int = 30) -> None:
    """新しい投稿をテーマ別コレクションへ振り分ける。前回見た投稿より新しいものだけを見る。"""
    state = _load()
    cols = state.setdefault("collections", {})
    done = set(state.get("done", []))
    pw, ctx, _b = _launch()
    page = None
    try:
        page = ctx.new_page()
        uid, tok = _api_session(page, slug)
        # 新しい順に読み、前回の続き（処理済みの投稿）か、古すぎる投稿に当たったら止める
        todo = []
        for pg in range(max_pages):  # after_id でのページ送りは途中で飛ぶので offset を使う
            u = f"{API}/{uid}/collects?api_version=1&limit=20&offset={pg * 20}&csrf_tkn={tok}"
            data = _api_get(page, u).get("data") or []
            if not data:
                break
            stop = False
            for c in data:
                if c["id"] in done or (c.get("created_at") or "") < MIN_CREATED:
                    stop = True
                    break
                todo.append(c)
            if stop:
                break
            time.sleep(random.uniform(0.8, 1.6))
        todo.reverse()  # 古い順に入れる（コレクション内は新しいものが上に来る）
        print(f"  未処理の投稿 {len(todo)} 件")
        added, created, ng = 0, 0, 0
        for c in todo:
            if added >= max_add or ng >= 3:
                break
            t = _theme_of(c.get("name", ""))
            if t:
                info = cols.get(t["slug"])
                if not info:
                    j = _post(page, f"{API}/collection/?csrf_tkn={tok}", urlencode(
                        {"name": t["name"], "img_icon": "", "about": t["about"], "collects": c["id"]}))
                    if j.get("status") == "success":
                        cols[t["slug"]] = {"id": j["data"]["id"], "name": t["name"], "count": 1}
                        created += 1
                        added += 1
                        print(f"  コレクション作成: {t['name']}")
                    else:
                        ng += 1
                        print(f"  作成できませんでした: {t['name']}（{j['_status']} {j['_text']}）")
                        continue
                else:
                    j = _post(page, f"{API}/{info['id']}/collect?csrf_tkn={tok}", urlencode({"collect_id": c["id"]}))
                    if j.get("status") == "success" or "R200" in j["_text"]:
                        info["count"] = info.get("count", 0) + 1
                        added += 1
                        ng = 0
                    else:
                        ng += 1
                        print(f"  追加できませんでした: {t['name']}（{j['_status']} {j['_text']}）")
                        continue
                time.sleep(random.uniform(1.5, 3.5))
            done.add(c["id"])
        # 処理済みの記録は直近分だけ残せば十分（新しい順の読み取りを止める目印に使う）
        state["done"] = sorted(done)[-3000:]
        state["last_run"] = datetime.now().isoformat(timespec="seconds")
        _save(state)
        _check_survival(page, uid, tok)
        summary = "・".join(f"{v['name']} {v.get('count', 0)}" for v in cols.values())
        print(f"コレクションに {added} 件追加（新規作成 {created}）。{summary}")
    finally:
        if page:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass
        pw.stop()

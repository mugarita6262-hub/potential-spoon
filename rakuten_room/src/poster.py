"""楽天ROOM への半自動投稿（Playwright）。

方針（②半自動）:
  - ツール専用の Chrome プロファイル（楽天ログイン済み）に CDP でつなぐ。
    楽天のログイン画面は自動化を検知して固まるため、Playwright 内蔵ブラウザは使わない。
  - 投稿は https://room.rakuten.co.jp/mix?itemcode=<ショップ:商品ID> を開くと出る
    モーダル（#collect-content にコメント、button.collect-btn「完了」で投稿）を使う。
  - コメントは自動入力。最後の「完了」クリックは人間が確認して押す
    （y を押せば自動クリックも可能）。
  - セレクタが変わって自動入力に失敗しても、コメントはクリップボードに入るので
    貼り付けて投稿すれば作業は続けられる。
"""
from __future__ import annotations

import os
import platform
import random
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

from .captions import load_captions, load_drafts, load_plan
from .config import SESSION_DIR
from .posted_log import posted_today, record_posted

MIX_URL = "https://room.rakuten.co.jp/mix?itemcode={code}"
COMMENT_SEL = "#collect-content"
SUBMIT_SEL = "button.collect-btn:visible"

CDP_PORT = 9222
IS_LINUX = platform.system() == "Linux"
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
] if not IS_LINUX else [
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
]
# 普段の Chrome とは別の、ツール専用プロファイル（ここに楽天ログインを保存）
TOOL_PROFILE = str(SESSION_DIR / "chrome_profile")

ROOM_TOP = "https://room.rakuten.co.jp/"
ROOM_MY = "https://room.rakuten.co.jp/myaccount"


def _find_chrome() -> str:
    for p in CHROME_CANDIDATES:
        if p and Path(p).exists():
            return p
    raise RuntimeError(
        "Chrome/Chromium が見つかりませんでした。インストールしてください。"
    )


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _kill_tool_chrome() -> None:
    """ツール専用プロファイルの Chrome だけを終了する（普段の Chrome は触らない）。"""
    if IS_LINUX:
        try:
            subprocess.run(["pkill", "-f", "--", "--user-data-dir=.*chrome_profile"],
                            capture_output=True, timeout=20)
        except Exception:  # noqa: BLE001
            pass
    else:
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
            "Where-Object { $_.CommandLine -like '*chrome_profile*' } | "
            "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force } catch {} }"
        )
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=20)
        except Exception:  # noqa: BLE001
            pass
    time.sleep(2.0)


def _cdp_healthy() -> bool:
    """デバッグポートが生きていて応答するか（stale 接続の検出）。"""
    if not _port_open(CDP_PORT):
        return False
    try:
        import urllib.request
        with urllib.request.urlopen(
            f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=5
        ) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _enable_session_restore() -> None:
    """「前回開いていたページを開く」設定にする。この設定だとChromeは再起動後も
    セッションCookie（楽天ログインの一部）を復元するので、落ちてもログインが残る。
    Chromeが起動していない時にだけ呼ぶこと（起動中に書き換えると上書きされる）。"""
    import json

    pref = Path(TOOL_PROFILE) / "Default" / "Preferences"
    if not pref.exists():
        return
    try:
        data = json.loads(pref.read_text(encoding="utf-8"))
        if (data.get("session") or {}).get("restore_on_startup") == 1:
            return
        data.setdefault("session", {})["restore_on_startup"] = 1
        pref.write_text(json.dumps(data), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _start_chrome_with_debugging() -> None:
    """ツール専用プロファイルで Chrome をデバッグポート付きで起動する。

    普段の Chrome とは別プロファイルなので、普段の Chrome が起動中でも
    独立したプロセスとして立ち上がり、デバッグ接続できる。
    サーバー（Linux）ではヘッドレスではなく、Xvfbの仮想画面(:99)上で通常起動する。
    ヘッドレスはUAに"HeadlessChrome"が出るなど楽天側から自動化を見分けやすく、
    ログインもできない（noVNC経由で仮想画面を見ながら手動ログインするため）。
    """
    chrome = _find_chrome()
    Path(TOOL_PROFILE).mkdir(parents=True, exist_ok=True)
    _enable_session_restore()
    args = [
        chrome,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={TOOL_PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate",
    ]
    if IS_LINUX:
        args += ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                 "--window-position=0,0", "--window-size=1366,900"]
    args.append("https://room.rakuten.co.jp/")
    if IS_LINUX:
        # 出力を切り離さないと、呼び出し元のSSH/ジョブがChrome終了まで閉じない
        kwargs = {"start_new_session": True,
                  "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                  "env": {**os.environ, "DISPLAY": os.environ.get("ROOM_DISPLAY", ":99")}}
    else:
        kwargs = {"creationflags": getattr(subprocess, "DETACHED_PROCESS", 0)}
    subprocess.Popen(args, **kwargs)


def _launch(headless: bool = False):
    """ツール専用プロファイルの Chrome に CDP でつなぐ。

    ポートは開いているのに応答しない（前回の残骸）場合は、
    ツール用 Chrome だけ落として起動し直す。
    """
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()

    if _port_open(CDP_PORT) and not _cdp_healthy():
        print("前回のツール用 Chrome が残っているようです。終了して起動し直します...")
        _kill_tool_chrome()

    if not _cdp_healthy():
        _kill_tool_chrome()  # 念のためプロファイルロックを解放
        _start_chrome_with_debugging()
        for _ in range(90):  # 最大45秒待つ
            if _cdp_healthy():
                break
            time.sleep(0.5)
        else:
            pw.stop()
            raise RuntimeError(
                "ツール用 Chrome のデバッグ接続を開始できませんでした。\n"
                "  ・ウイルス対策ソフトがブロックしていないか確認\n"
                "  ・PC を再起動してからもう一度お試しください"
            )
        time.sleep(2.0)

    browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    ctx.set_default_navigation_timeout(45000)
    return pw, ctx, browser


def _safe_goto(page, url: str) -> None:
    """読み込み完了を待たずに遷移する。重いページでも固まらない。"""
    try:
        page.bring_to_front()
    except Exception:  # noqa: BLE001
        pass
    try:
        page.goto(url, wait_until="commit", timeout=35000)
    except Exception:  # noqa: BLE001
        # commit すら来ない場合はもう一度だけ緩めに試す
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=35000)
        except Exception as exc:  # noqa: BLE001
            print(f"  （ページ遷移の警告。無視して進みます: {exc}）")


def _my_slug() -> str:
    try:
        import re

        from .config import load_config
        m = re.search(r"/(room_[0-9a-z]+|[A-Za-z0-9_.-]+)/items",
                      load_config().get("my_room_url", ""))
        return m.group(1) if m else ""
    except Exception:  # noqa: BLE001
        return ""


def _is_logged_in(page) -> bool:
    """未ログインでも myaccount はリダイレクトされず「フォロー」等の文字も出るため、
    ログイン中だけページに現れる自分のROOM ID（my_room_url内のもの）で判定する。"""
    try:
        _safe_goto(page, ROOM_MY)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:  # noqa: BLE001
            pass
        slug = _my_slug()
        # Chrome起動直後は裏でSSOの自動再認証（login.account.rakuten.com を一瞬経由して
        # 戻ってくる）が走ることがあるので、ログインページを見ても即断せず待ち続ける
        for i in range(14):  # 最大 ~20秒
            page.wait_for_timeout(1500)
            try:
                html = page.content()
            except Exception:  # noqa: BLE001
                continue
            if slug and slug in html:
                return True
            if not slug and ("ログアウト" in html):
                return True
            if i == 6 and "myaccount" not in page.url:
                _safe_goto(page, ROOM_MY)  # SSOから戻らなければ一度だけ開き直す
        return False
    except Exception:  # noqa: BLE001
        return False


def login() -> None:
    """普段の Chrome につなぎ、楽天ROOMにログイン済みかを確認する。"""
    pw, ctx, _browser = _launch()
    try:
        page = ctx.new_page()
        _safe_goto(page, ROOM_TOP)
        page.wait_for_timeout(3000)
        if _is_logged_in(page):
            print("楽天ROOMにログイン済みです。このまま post を実行できます。")
            return
        print(
            "\n============================================================\n"
            "開いた Chrome（ツール専用）で楽天ROOMにログインしてください。\n"
            "  ・普段の Chrome とは別枠なので、初回はログインが必要です\n"
            "  ・右上メニュー →『ログイン』から楽天IDで\n"
            "  ・2回目以降はこのログインが保存され、不要になります\n"
            "\n"
            "ログインできてROOMのトップ／マイページが見えたら、\n"
            "この黒い画面に戻って Enter キーを押してください。\n"
            "============================================================"
        )
        input()
        if _is_logged_in(page):
            print("ログインを確認しました。次回からはログイン不要です。")
        else:
            print(
                "ログイン状態を確認できませんでした。\n"
                "Chrome でマイページが開けているなら、そのまま post を試して大丈夫です。"
            )
    finally:
        pw.stop()  # Chrome は閉じない（ユーザーの普段のブラウザ）


def _open_mix_modal(page, item_code: str) -> bool:
    """商品の投稿モーダルを開き、コメント欄が出て初期化が済んだら True。"""
    _safe_goto(page, MIX_URL.format(code=quote(item_code, safe="")))
    try:
        page.wait_for_selector(COMMENT_SEL, state="visible", timeout=25000)
    except Exception:  # noqa: BLE001
        return False
    # AngularJS の初期化待ち: 文字数カウンター「0 / 500」と「完了」ボタンが出るまで
    for _ in range(30):
        try:
            body = page.locator("body").inner_text(timeout=3000)
            if "/ 500" in body and "完了" in body:
                break
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(500)
    page.wait_for_timeout(2500)
    return True


_SET_VALUE_JS = """
([sel, val]) => {
  const e = document.querySelector(sel);
  if (!e) return false;
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(e, val);
  e.dispatchEvent(new Event('input', {bubbles: true}));
  e.dispatchEvent(new Event('change', {bubbles: true}));
  e.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true}));
  return e.value === val;
}
"""


def _current_value(page) -> str:
    try:
        return (page.input_value(COMMENT_SEL) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _fill_comment(page, caption: str) -> bool:
    target = caption.strip()

    def _try(method) -> bool:
        try:
            method()
        except Exception:  # noqa: BLE001
            return False
        page.wait_for_timeout(1200)  # Angular が消さないか少し様子見
        return _current_value(page) == target

    methods = [
        # JS で value を直接セット + input イベント（AngularJS 対策・絵文字OK）
        lambda: page.evaluate(_SET_VALUE_JS, [COMMENT_SEL, caption]),
        # Playwright の fill
        lambda: page.fill(COMMENT_SEL, caption, timeout=8000),
    ]
    for _ in range(4):
        for m in methods:
            if _try(m):
                return True
        page.wait_for_timeout(1000)
    # 最後の手段: 部分的にでも入っていれば良しとする
    return len(_current_value(page)) >= min(20, len(target))


def _modal_text(page) -> str:
    try:
        return page.locator('[ng-controller="CollectItemCtrl"]').inner_text(timeout=3000)
    except Exception:  # noqa: BLE001
        try:
            return page.locator("body").inner_text(timeout=3000)
        except Exception:  # noqa: BLE001
            return ""


def _already_posted_modal(page, wait_ms: int = 5000) -> bool:
    """「すでにコレしている商品です」は少し遅れて出るので、しばらく待ちながら確認する
    （即時チェックだと見逃して同じ商品を再コレしてしまった: 2026-09-30）。"""
    for _ in range(max(1, wait_ms // 500)):
        t = _modal_text(page)
        if "既に" in t or "すでにコレ" in t:
            return True
        page.wait_for_timeout(500)
    return False


def _limit_reached(page) -> bool:
    return "登録上限に達しました" in _modal_text(page)


def post_drafts_tabs(cfg: dict, day: str | None = None, full_day: bool = False) -> None:
    """新規の投稿を1件ずつ自動で完了まで進める（完全自動・人の操作なし）。
    full_day=True なら post_batch_size を無視して今日の残り全部。

    2026-09-26: 『完了』クリックだけ人間が押す半自動方式から、規約違反リスクを
    受け入れて完全自動に変更（本人の明示的な判断による）。失敗した商品は
    記録せずスキップし、次の商品に進む（ログには残るので後で人が確認できる）。
    """
    drafts = load_drafts(day)
    captions = load_captions(day)
    if not captions:
        print("キャプション（紹介文）がまだありません。先に prepare とキャプション作成を。")
        return

    targets = [it for it in drafts if captions.get(it["itemUrl"], "").strip()
               and it.get("itemCode")]
    # 同じ日に複数回実行されるので、投稿履歴にある商品は確実に除外する
    # （ROOM側の「すでにコレ」表示だけに頼ると見逃して二重コレになる）
    from .posted_log import recently_posted_keys
    done_keys = recently_posted_keys(int((cfg.get("exclude") or {}).get("reposted_within_days", 60)))
    targets = [it for it in targets if (it.get("itemCode") or it.get("itemUrl")) not in done_keys]
    if not targets:
        print("投稿できる商品がありません。")
        return

    # 今日の目標数（セール倍率込み）は prepare が _plan.json に書く
    plan = load_plan(day)
    target_count = int(plan.get("target_count") or cfg.get("post_count", 10))
    done_today = posted_today()
    remaining = max(0, target_count - done_today)
    batch = remaining if full_day else int(cfg.get("post_batch_size") or target_count)
    this_run = min(remaining, batch)

    if plan.get("reasons"):
        print(f"今日の目標: {target_count} 件（{' / '.join(plan['reasons'])}）")
    if this_run <= 0:
        print(f"今日はすでに {done_today}/{target_count} 件投稿済みです。おつかれさまでした。")
        return
    print(f"今日 {done_today}/{target_count} 件投稿済み → この回で最大 {this_run} 件、自動で完了まで進めます。")

    lo, hi = cfg.get("post_interval_seconds", [20, 45])
    pw, ctx, _browser = _launch()
    try:
        page0 = ctx.new_page()
        if not _is_logged_in(page0):
            print("楽天ROOMに未ログインです。先に login.bat を実行してください。")
            if IS_LINUX:
                from .notify import notify
                notify("サーバーの楽天ROOMログインが切れています。自動投稿が止まっているので、"
                       "Claudeに『ROOMの再ログイン』を頼んでください。",
                       title="rakuten_room: ROOM login expired")
            return
        try:
            page0.close()
        except Exception:  # noqa: BLE001
            pass

        posted = 0
        skipped = 0
        failed = 0
        for it in targets:
            if posted >= this_run:
                break
            code = it["itemCode"]
            # 商品ごとに新しいタブを開く（1つのタブを使い回すと、AngularJSが前の
            # モーダルの『完了』ボタンを消さずに残すことがあり、ボタンが2つ存在
            # して strict mode violation になるバグが2026-09-28に発覚したため）
            tab = ctx.new_page()
            try:
                if not _open_mix_modal(tab, code):
                    print(f"  × モーダルが開かず、スキップ: {it['itemName'][:40]}")
                    failed += 1
                    continue
                if _limit_reached(tab):
                    print("\n⚠ 楽天ROOMの登録上限に達しています。今回はここで打ち切ります"
                          "（次回の prune で空きができてから続きます）。")
                    break
                if _already_posted_modal(tab):
                    skipped += 1
                    print(f"  - 既にROOMにある: {it['itemName'][:40]}")
                    record_posted(it, kind="skipped_existing")
                    continue

                caption = captions[it["itemUrl"]].strip()
                filled = _fill_comment(tab, caption)
                if not filled:
                    print(f"  △ コメント入力に失敗、スキップ: {it['itemName'][:40]}")
                    failed += 1
                    continue

                try:
                    tab.locator(SUBMIT_SEL).first.click(timeout=8000)
                    tab.wait_for_timeout(3000)
                except Exception as exc:  # noqa: BLE001
                    print(f"  × 完了クリックに失敗、スキップ: {it['itemName'][:40]}: {exc}")
                    failed += 1
                    continue

                # クリックできても登録されていないことがあった（2026-09-29にデスクトップで
                # 「✅」表示なのに未登録の例）ので、開き直して「すでにコレ」を確認してから記録する
                if not (_open_mix_modal(tab, code) and _already_posted_modal(tab)):
                    print(f"  × 完了を押したが登録を確認できず、スキップ: {it['itemName'][:40]}")
                    failed += 1
                    continue

                record_posted(it, kind="posted")
                posted += 1
                print(f"  ✅ {posted}/{this_run}. {it['itemName'][:46]}")
            finally:
                try:
                    tab.close()
                except Exception:  # noqa: BLE001
                    pass
            if posted < this_run:
                wait = random.randint(int(lo), int(hi))
                time.sleep(wait)

        total_today = done_today + posted
        print(f"\n{posted} 件投稿（既存スキップ {skipped} 件・失敗 {failed} 件）。"
              f"今日の合計 {total_today}/{target_count} 件。")
        if total_today < target_count and failed == 0 and posted < this_run:
            print("候補が尽きました。次回の prepare で候補を増やしてください。")
    finally:
        pw.stop()


def post_drafts(cfg: dict, day: str | None = None, dry_run: bool = False) -> None:
    drafts = load_drafts(day)
    captions = load_captions(day)
    if not captions:
        print(
            "キャプション（紹介文）がまだありません。\n"
            "  『準備だけ』を先に実行してください（ANTHROPIC_API_KEY があれば自動生成）。"
        )
        return

    lo, hi = cfg["post_interval_seconds"]
    pw, ctx, _browser = _launch()
    try:
        page = ctx.new_page()
        if not _is_logged_in(page):
            print("楽天ROOMに未ログインです。先に login.bat を実行してログインしてください。")
            return

        targets = [it for it in drafts if captions.get(it["itemUrl"], "").strip()
                   and it.get("itemCode")]
        if not targets:
            print("投稿できる商品がありません（itemCode かキャプション不足）。")
            return

        target_count = int(cfg.get("post_count", 10))
        pool = len(targets)
        print(f"\n新規で {target_count} 件投稿するのが目標です（候補 {pool} 件から、"
              f"既存とかぶった分は次の候補で埋めます）。")

        done = 0
        skipped_existing = 0
        for it in targets:
            if done >= target_count:
                break
            caption = captions[it["itemUrl"]].strip()
            code = it["itemCode"]
            try:
                import pyperclip
                pyperclip.copy(caption)
            except Exception:  # noqa: BLE001
                pass  # ヘッドレスサーバーにはクリップボードが無いので無視

            print("\n" + "=" * 72)
            print(f"[新規 {done}/{target_count}] {it['itemName'][:58]}")
            print(f"  {it['price']:,}円 / レビュー{it['reviewCount']}件 "
                  f"平均{it['reviewAverage']} / スコア{it.get('score', '-')}")
            print(f"  コメント（クリップボードにもコピー済み）:\n    {caption}")

            opened = _open_mix_modal(page, code)
            if not opened:
                print("  ⚠ 投稿モーダルが開きませんでした。次の候補へ。")
                continue
            if _already_posted_modal(page):
                skipped_existing += 1
                print(f"  既にROOMにある商品なのでスキップ（{skipped_existing}件目）。次の候補へ。")
                record_posted(it)
                continue

            filled = _fill_comment(page, caption)
            print(f"  コメント自動入力: {'OK' if filled else '失敗（Ctrl+V で貼り付けてください）'}")

            if dry_run:
                print("  [dry-run] 『完了』は押しません。")
                input("  確認したら Enter で次へ > ")
                done += 1
                continue

            ans = input(
                "  ブラウザで内容を確認 →『完了』ボタンを押してください。\n"
                "  投稿できたら Enter。この商品を飛ばすなら s。自動で『完了』を押すなら y > "
            ).strip().lower()
            if ans == "s":
                print("  飛ばしました（新規カウントに入れません）。")
                continue
            if ans == "y":
                try:
                    page.locator(SUBMIT_SEL).first.click(timeout=8000)
                    page.wait_for_timeout(3000)
                    print("  『完了』を自動クリックしました。")
                except Exception as exc:  # noqa: BLE001
                    print(f"  自動クリック失敗: {exc}\n  手動で『完了』を押してから Enter してください。")
                    input("  > ")

            record_posted(it)
            done += 1
            if done < target_count:
                wait = random.randint(int(lo), int(hi))
                print(f"  記録（新規 {done}/{target_count}）。スパム判定対策で {wait} 秒待機...")
                time.sleep(wait)

        print(f"\n完了: 新規 {done} 件投稿（既存スキップ {skipped_existing} 件）。")
        if done < target_count:
            print(f"候補が尽きて {target_count} 件に届きませんでした。"
                  "config.yaml の candidate_pool を増やすか、ジャンルを追加してください。")
    finally:
        pw.stop()  # ツール用 Chrome は開いたままにする

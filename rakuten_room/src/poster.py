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
import random
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

import pyperclip

from .captions import load_captions, load_drafts
from .config import SESSION_DIR
from .posted_log import record_posted

MIX_URL = "https://room.rakuten.co.jp/mix?itemcode={code}"
COMMENT_SEL = "#collect-content"
SUBMIT_SEL = "button.collect-btn"

CDP_PORT = 9222
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
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
        "Google Chrome が見つかりませんでした。Chrome をインストールしてください。"
    )


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _kill_tool_chrome() -> None:
    """ツール専用プロファイルの Chrome だけを終了する（普段の Chrome は触らない）。"""
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


def _start_chrome_with_debugging() -> None:
    """ツール専用プロファイルで Chrome をデバッグポート付きで起動する。

    普段の Chrome とは別プロファイルなので、普段の Chrome が起動中でも
    独立したプロセスとして立ち上がり、デバッグ接続できる。
    """
    chrome = _find_chrome()
    Path(TOOL_PROFILE).mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            chrome,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={TOOL_PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
            "https://room.rakuten.co.jp/",
        ],
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )


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


def _is_logged_in(page) -> bool:
    try:
        _safe_goto(page, ROOM_MY)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(3000)
        url = page.url
        try:
            html = page.content()
        except Exception:  # noqa: BLE001
            html = ""
        if "login" in url or "grp01.id.rakuten" in url or "account.rakuten" in url:
            return False
        return ("myaccount" in url) or ("マイページ" in html) or ("フォロー" in html) \
            or ("ログアウト" in html)
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


def _already_posted_modal(page) -> bool:
    t = _modal_text(page)
    return "既に" in t or "すでにコレ" in t


def _limit_reached(page) -> bool:
    return "登録上限に達しました" in _modal_text(page)


def post_drafts_tabs(cfg: dict, day: str | None = None) -> None:
    """新規10件ぶんのタブを一気に開き、コメント入力済みにする。
    ユーザーは各タブで『完了』を押すだけ。"""
    drafts = load_drafts(day)
    captions = load_captions(day)
    if not captions:
        print("キャプション（紹介文）がまだありません。先に prepare とキャプション作成を。")
        return

    targets = [it for it in drafts if captions.get(it["itemUrl"], "").strip()
               and it.get("itemCode")]
    if not targets:
        print("投稿できる商品がありません。")
        return

    target_count = int(cfg.get("post_count", 10))
    pw, ctx, _browser = _launch()
    try:
        page0 = ctx.new_page()
        if not _is_logged_in(page0):
            print("楽天ROOMに未ログインです。先に login.bat を実行してください。")
            return
        try:
            page0.close()
        except Exception:  # noqa: BLE001
            pass

        prepared: list[dict] = []
        skipped = 0
        print(f"新規 {target_count} 件ぶんのタブを準備します...")
        for it in targets:
            if len(prepared) >= target_count:
                break
            code = it["itemCode"]
            tab = ctx.new_page()
            if not _open_mix_modal(tab, code):
                print(f"  × モーダルが開かず: {it['itemName'][:40]}")
                try:
                    tab.close()
                except Exception:  # noqa: BLE001
                    pass
                continue
            if _limit_reached(tab):
                print("\n⚠ 楽天ROOMの登録上限に達しています。\n"
                      "  prune.bat で古い投稿を削除して空きを作ってから、もう一度 post してください。")
                return
            if _already_posted_modal(tab):
                skipped += 1
                print(f"  - 既にROOMにある: {it['itemName'][:40]}")
                record_posted(it)
                try:
                    tab.close()
                except Exception:  # noqa: BLE001
                    pass
                continue
            filled = _fill_comment(tab, it_caption := captions[it["itemUrl"]].strip())
            n = len(prepared) + 1
            print(f"  {n}. {'✓' if filled else '△(手動貼付)'} {it['itemName'][:46]}")
            prepared.append(it)

        if not prepared:
            print("\n開けるタブがありませんでした（候補が全部既存 or エラー）。")
            return

        print("\n" + "=" * 64)
        print(f"{len(prepared)} 個のタブを用意しました（既存スキップ {skipped} 件）。")
        print("各タブで内容を確認して赤い『完了』ボタンを押してください。")
        print("※ 連続で押しすぎるとスパム判定されることがあります。数秒あけると安心。")
        print("全部終わったら、この画面で Enter を押してください。")
        input("> ")

        for it in prepared:
            record_posted(it)
        print(f"\n{len(prepared)} 件を投稿済みとして記録しました。")
        if len(prepared) < target_count:
            print(f"（{target_count} 件に届かず。candidate_pool を増やすかジャンル追加を検討）")
    finally:
        pw.stop()


def post_drafts(cfg: dict, day: str | None = None, dry_run: bool = False) -> None:
    drafts = load_drafts(day)
    captions = load_captions(day)
    if not captions:
        print(
            "キャプション（紹介文）がまだありません。\n"
            f"  1) data/drafts/(日付)_prompt.md の中身を Claude に貼る\n"
            f"  2) 返ってきた JSON を data/drafts/(日付)_captions.json に保存\n"
            "  3) もう一度 post_now.bat を実行\n"
            "  ※ Claude Code と一緒に作業しているなら、Claude に作ってもらえます"
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
            pyperclip.copy(caption)

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
                    page.locator(SUBMIT_SEL).click(timeout=8000)
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

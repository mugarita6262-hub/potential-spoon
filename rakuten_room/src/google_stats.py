"""買い時ナビのGA4・Search Consoleの数字を毎晩 data/google_stats.json に記録する（読み取りのみ）。

鍵は data/google_sa.json（サービスアカウント、コミットしない）。
サーバーからGoogleへのIPv6がつながらないため、IPv4に固定して接続する。
"""
from __future__ import annotations

import json
import socket
from datetime import date, timedelta

from .config import DATA_DIR

KEY = DATA_DIR / "google_sa.json"
OUT = DATA_DIR / "google_stats.json"
GA4_PROPERTY = "properties/557266711"
SC_SITE = "https%3A%2F%2Fkaidokinavi.com%2F"


def _ipv4_only() -> None:
    import urllib3.util.connection as uc
    uc.allowed_gai_family = lambda: socket.AF_INET


def _ga4(cred, days: list[str]) -> dict:
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest

    c = BetaAnalyticsDataClient(credentials=cred)

    def run(dims: list[str], metrics: list[str]) -> list:
        r = c.run_report(RunReportRequest(
            property=GA4_PROPERTY, date_ranges=[DateRange(start_date=days[0], end_date=days[-1])],
            dimensions=[Dimension(name=d) for d in ["date", *dims]], metrics=[Metric(name=m) for m in metrics], limit=2000))
        return [([v.value for v in x.dimension_values], [float(v.value) for v in x.metric_values]) for x in r.rows]

    out: dict = {d: {"sources": {}, "landing": {}, "events": {}, "aff_pages": {}} for d in days}
    for k in out:
        out[k]["users"] = 0
    fmt = lambda s: f"{s[:4]}-{s[4:6]}-{s[6:]}"  # noqa: E731
    for (d, src), (ses, users) in run(["sessionSource"], ["sessions", "activeUsers"]):
        out[fmt(d)]["sources"][src] = int(ses)
        out[fmt(d)]["users"] += int(users)
    for (d, lp), (ses,) in run(["landingPage"], ["sessions"]):
        out[fmt(d)]["landing"][lp] = int(ses)
    for (d, ev), (n,) in run(["eventName"], ["eventCount"]):
        out[fmt(d)]["events"][ev] = int(n)
    for (d, ev, path), (n,) in run(["eventName", "pagePath"], ["eventCount"]):
        if ev == "affiliate_click":
            out[fmt(d)]["aff_pages"][path] = int(n)
    # 楽天リンクのクリックを流入元別に（Threads戦略の判定: 2026-11-30までに threads 経由で累計30回）
    for (d, ev, src), (n,) in run(["eventName", "sessionSource"], ["eventCount"]):
        if ev == "affiliate_click":
            out[fmt(d)].setdefault("aff_sources", {})[src] = int(n)
    return out


def _sc(cred, days: list[str]) -> dict:
    from google.auth.transport.requests import AuthorizedSession

    s = AuthorizedSession(cred.with_scopes(["https://www.googleapis.com/auth/webmasters.readonly"]))
    url = f"https://searchconsole.googleapis.com/webmasters/v3/sites/{SC_SITE}/searchAnalytics/query"
    out: dict = {}
    for d in days:
        def q(dim: str, n: int = 50) -> list:
            r = s.post(url, json={"startDate": d, "endDate": d, "dimensions": [dim], "rowLimit": n}, timeout=60)
            r.raise_for_status()
            return r.json().get("rows", [])
        rows = {"clicks": 0, "impressions": 0, "queries": {}, "pages": {}}
        for x in q("query"):
            rows["queries"][x["keys"][0]] = [x["clicks"], x["impressions"], round(x["position"], 1)]
        for x in q("page"):
            p = x["keys"][0].replace("https://kaidokinavi.com", "")
            rows["pages"][p] = [x["clicks"], x["impressions"], round(x["position"], 1)]
            rows["clicks"] += x["clicks"]
            rows["impressions"] += x["impressions"]
        out[d] = rows
    return out


def record_google_stats(back: int = 4) -> None:
    """直近の数日分を取り直して上書きする（Search Consoleは2〜3日遅れて確定するため）。"""
    if not KEY.exists():
        print("google_stats: 鍵がないのでスキップ")
        return
    _ipv4_only()
    from google.oauth2 import service_account

    cred = service_account.Credentials.from_service_account_file(str(KEY))
    days = [(date.today() - timedelta(days=i)).isoformat() for i in range(back, 0, -1)]
    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"ga4": {}, "sc": {}}
    for name, fn in (("ga4", _ga4), ("sc", _sc)):
        try:
            data[name].update(fn(cred, days))
        except Exception as e:  # noqa: BLE001
            print(f"google_stats: {name} の取得に失敗 {str(e)[:150]}")
    for name in ("ga4", "sc"):
        data[name] = dict(sorted(data[name].items())[-120:])
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    y = days[-1]
    g, s = data["ga4"].get(y, {}), data["sc"].get(days[-3], {})
    print(f"google_stats: {y} 訪問 {g.get('users', 0)}人・アフィリクリック {g.get('events', {}).get('affiliate_click', 0)}／"
          f"検索 {days[-3]} 表示 {s.get('impressions', 0)}・クリック {s.get('clicks', 0)}")


if __name__ == "__main__":
    record_google_stats(back=30)

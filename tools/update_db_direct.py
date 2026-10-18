"""One-shot direct REST update script (no marketdb required).

Endpoint: GET https://fuyao.aicubes.cn/api/a-share/prices/historical
Auth:     X-api-key header
Schema:   data.item[] with date_ms/open_price/high_price/low_price/close_price/volume/turnover

Env vars:
  FINANCIAL_API_BASE_URL  default https://fuyao.aicubes.cn
  FINANCIAL_API_KEY       required

Args:
  --db       DuckDB path
  --target   YYYY-MM-DD target trading day
  --days     lookback window (default 14)
  --qps      client throttle (default 5.0)
  --limit-stocks  debug: only first N stocks (0=all)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import duckdb
import requests

#: §0 (audit 2026-10-15, 时间确定性): 交易所时区固定为 **UTC+8**(A 股,无夏令时)。
#:
#: 原实现把日期与毫秒时间戳互转时用的是**本机时区** —— `datetime.strptime(...)`
#: 得到 naive datetime,其 `.timestamp()` 按本地时区解释;反方向的
#: `datetime.fromtimestamp(...)` 同样按本地时区还原。后果是**同一份 API 负载在
#: 不同机器上会落成不同的 bar 日期**(UTC 与 UTC+8 机器可差一天),直接违反 §0
#: 「把时间戳归一到单一交易所时区」。CLAUDE.md §0 的可复现性要求里这一条是明写的。
EXCHANGE_TZ = timezone(timedelta(hours=8))


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"ERROR: env var {name} not set")
    return val


def to_ms(date_str: str) -> int:
    """交易日 → epoch ms,以**交易所时区**当日 00:00 为基准(与本机时区无关)。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=EXCHANGE_TZ)
    return int(dt.timestamp() * 1000)


def from_ms(ms: int) -> str:
    """epoch ms → 交易日字符串,按**交易所时区**还原(与本机时区无关)。

    与 `to_ms` 构成往返:`from_ms(to_ms(d)) == d`,且两者都不依赖 TZ 环境变量。
    """
    return datetime.fromtimestamp(ms / 1000, tz=EXCHANGE_TZ).strftime("%Y-%m-%d")


def fetch_historical(
    base_url: str, api_key: str, thscode: str,
    start_ms: int, end_ms: int, adjust: str = "none",
    timeout: int = 10, max_retries: int = 3,
) -> list[dict]:
    url = f"{base_url.rstrip('/')}/api/a-share/prices/historical"
    headers = {"X-api-key": api_key}
    params = {
        "thscode": thscode,
        "interval": "1d",
        "start": start_ms,
        "end": end_ms,
        "adjust": adjust,
    }
    last_err = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 429:
                time.sleep(2 + attempt * 2)
                continue
            r.raise_for_status()
            data = r.json()
            code = data.get("code")
            if code == 4001:
                time.sleep(2 + attempt * 2)
                continue
            if code != 0:
                raise RuntimeError(f"API code={code}: {data.get('message')}")
            return (data.get("data") or {}).get("item", []) or []
        except (requests.RequestException, ValueError) as e:
            last_err = e
            if attempt == max_retries - 1:
                raise
            time.sleep(1)
    raise RuntimeError(f"failed after {max_retries} retries: {last_err}")


def update_verdict(inserted: int, skipped: int, errors: int) -> tuple[int, str]:
    """本工具的口径 —— 委托给共享实现 `core.cli_verdict`(§0 单一实现)。

    `attempted = inserted + skipped`(有数据回包的目标数),`succeeded = inserted`。
    """
    from core.cli_verdict import cli_verdict

    return cli_verdict(
        failures=errors, attempted=inserted + skipped, succeeded=inserted,
        what="行情库更新",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--target", default="2026-09-19")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--limit-stocks", type=int, default=0)
    ap.add_argument("--qps", type=float, default=5.0)
    args = ap.parse_args()

    base_url = _require_env("FINANCIAL_API_BASE_URL")
    api_key = _require_env("FINANCIAL_API_KEY")

    target_dt = datetime.strptime(args.target, "%Y-%m-%d")
    start_dt = target_dt - timedelta(days=args.days)
    start_ms = to_ms(start_dt.strftime("%Y-%m-%d"))
    end_ms = to_ms(args.target)

    print(f"[update_db_direct] db={args.db}")
    print(f"[update_db_direct] range: {start_dt.strftime('%Y-%m-%d')} -> {args.target}")
    print(f"[update_db_direct] base_url: {base_url}")

    con = duckdb.connect(args.db, read_only=False)
    cur_max = con.execute("SELECT MAX(date) FROM raw_kline_daily").fetchone()[0]
    print(f"[update_db_direct] DB max(date) = {cur_max}")

    symbols = con.execute(
        "SELECT thscode FROM dim_symbol WHERE asset_type = 'a-share' ORDER BY thscode"
    ).fetchdf()["thscode"].tolist()
    if args.limit_stocks:
        symbols = symbols[:args.limit_stocks]
    print(f"[update_db_direct] {len(symbols)} stocks")

    min_interval = 1.0 / max(args.qps, 0.1)
    inserted = 0
    skipped = 0
    errors = 0
    t0 = time.time()
    batch_id = f"direct-incr-{int(time.time() * 1000)}"

    for i, code in enumerate(symbols):
        try:
            rows = fetch_historical(base_url, api_key, code, start_ms, end_ms, "none")
        except Exception as e:
            errors += 1
            if errors < 5:
                print(f"  [{code}] FETCH ERR: {type(e).__name__}: {e}")
            time.sleep(min_interval)
            continue

        if not rows:
            skipped += 1
            time.sleep(min_interval)
            continue

        to_insert = []
        for r in rows:
            try:
                date_str = from_ms(r["date_ms"])
                to_insert.append((
                    code, date_str,
                    float(r["open_price"]), float(r["high_price"]),
                    float(r["low_price"]), float(r["close_price"]),
                    None,
                    float(r["volume"]), float(r["turnover"]),
                    batch_id,
                ))
            except (KeyError, ValueError, TypeError) as e:
                if errors < 5:
                    print(f"  [{code}] PARSE ERR: {e} | {r}")
                errors += 1

        if to_insert:
            try:
                con.executemany(
                    """INSERT OR IGNORE INTO raw_kline_daily
                       (thscode, date, open, high, low, close, prev_close, volume, amount, batch_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    to_insert,
                )
                inserted += len(to_insert)
            except Exception as e:
                errors += 1
                if errors < 5:
                    print(f"  [{code}] INSERT ERR: {e}")
        else:
            skipped += 1

        time.sleep(min_interval)

        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            print(f"  [{i+1}/{len(symbols)}] inserted={inserted} skipped={skipped} "
                  f"errors={errors} elapsed={elapsed:.0f}s")

    new_max = con.execute("SELECT MAX(date) FROM raw_kline_daily").fetchone()[0]
    print(f"\n[update_db_direct] Done:")
    print(f"  processed: {len(symbols)}")
    print(f"  inserted:  {inserted}")
    print(f"  skipped:   {skipped}")
    print(f"  errors:    {errors}")
    print(f"  max(date): {cur_max} -> {new_max}")
    print(f"  elapsed:   {time.time() - t0:.0f}s")
    con.close()

    # §0 (附六十三): 结论落在**退出码**上 —— 部分失败必须非零,否则 pipeline 会把
    # 一次半更新当成成功,下游回测随即读到不一致的行情库。
    code, msg = update_verdict(inserted, skipped, errors)
    print(f"\n[update_db_direct] {msg}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
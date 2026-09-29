"""自定义 DB 增量更新脚本（绕过 marketdb schema drift）。

marketdb 包代码与现有 DB 的 schema 不兼容（_import_batches、stg_symbols、stg_kline_daily
等表都有列名/列数差异），无法直接跑 `marketdb update-daily`。

本脚本：
  1. 用 RestProvider.historical() 拉每只股票近 N 天的 K 线
  2. INSERT OR IGNORE 进 raw_kline_daily（DB 实际的 schema）
  3. v_daily / v_daily_qfq / dim_symbol 等视图保持现状（它们已是按 DB 实际 schema 创建的）

REST 返回字段（实测）：
  {date_ms, open_price, high_price, low_price, close_price, volume, turnover}
DB raw_kline_daily 字段：
  (thscode, date, open, high, low, close, prev_close, volume, amount, batch_id)

环境变量:
  FINANCIAL_API_PATH     marketdb 包路径(原硬编码 /Users/zhl/code/Financial-API/python)
  FINANCIAL_API_BASE_URL REST base URL(原硬编码 https://fuyao.aicubes.cn)
  FINANCIAL_API_KEY      REST API key(原硬编码在源码,已迁出)
  任一未设置则启动时报错并退出(避免静默走默认值)。

用法:
  export FINANCIAL_API_PATH=/path/to/Financial-API
  export FINANCIAL_API_BASE_URL=https://fuyao.aicubes.cn
  export FINANCIAL_API_KEY=sk-...
  python3 -m tools.update_db --db <DB_PATH> --target 2026-09-19 [--days 30]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import duckdb


def _require_env(name: str) -> str:
    """Strict env var lookup — fail-fast if missing (CLAUDE.md §0 Pessimistic Default)."""
    value = os.environ.get(name)
    if not value:
        raise SystemExit(
            f"ERROR: 环境变量 {name} 未设置。请在执行前 export 该变量。\n"
            f"  export {name}=..."
        )
    return value


# 让 marketdb 可被 import(路径由 FINANCIAL_API_PATH 控制,不再硬编码)
_marketdb_root = Path(_require_env("FINANCIAL_API_PATH")).resolve()
sys.path.insert(0, str(_marketdb_root / "python"))
from marketdb.providers.rest import RestProvider  # noqa: E402


def to_ms(date_str: str) -> int:
    """YYYY-MM-DD → epoch milliseconds (UTC midnight)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return int(dt.timestamp() * 1000)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="DuckDB path")
    ap.add_argument("--target", default="2026-09-19", help="目标日期 YYYY-MM-DD")
    ap.add_argument("--days", type=int, default=14,
                    help="回看天数（保险，DB 已最新只补少量；建议 14）")
    ap.add_argument("--limit-stocks", type=int, default=0,
                    help="只更新前 N 只股票（调试用，0=全部）")
    ap.add_argument("--qps", type=float, default=5.0,
                    help="客户端节流 QPS（默认 5，每请求间隔 1/QPS 秒）")
    args = ap.parse_args()

    # 计算拉取区间
    target_dt = datetime.strptime(args.target, "%Y-%m-%d")
    start_dt = target_dt - timedelta(days=args.days)
    start_ms = to_ms(start_dt.strftime("%Y-%m-%d"))
    end_ms = to_ms(args.target)

    print(f"[update_db] db={args.db}")
    print(f"[update_db] 拉取区间: {start_dt.strftime('%Y-%m-%d')} → {args.target}")

    con = duckdb.connect(args.db, read_only=False)

    # 当前 DB 状态
    cur_max = con.execute("SELECT MAX(date) FROM raw_kline_daily").fetchone()[0]
    print(f"[update_db] DB 当前 max(date) = {cur_max}")

    # 取所有 stock 列表
    symbols = con.execute(
        "SELECT thscode FROM dim_symbol WHERE asset_type = 'a-share' ORDER BY thscode"
    ).fetchdf()["thscode"].tolist()
    if args.limit_stocks:
        symbols = symbols[:args.limit_stocks]
    print(f"[update_db] 待更新 {len(symbols)} 只股票")

    # 启动 REST provider(凭据来自环境变量,不再硬编码在源码中)
    provider = RestProvider(
        base_url=_require_env("FINANCIAL_API_BASE_URL"),
        api_key=_require_env("FINANCIAL_API_KEY"),
        min_interval_seconds=1.0 / max(args.qps, 0.1),
    )

    inserted = 0
    skipped = 0
    errors = 0
    t0 = time.time()
    batch_id = f"rest-incr-{int(time.time() * 1000)}"

    for i, code in enumerate(symbols):
        try:
            rows = provider.historical(
                thscode=code,
                start_ms=start_ms,
                end_ms=end_ms,
                interval="1d",
                adjust="none",
            )
        except Exception as e:
            errors += 1
            if errors < 5:
                print(f"  [{code}] FETCH ERR: {type(e).__name__}: {e}")
            continue

        if not rows:
            skipped += 1
            continue

        # 转成 raw_kline_daily 格式
        to_insert = []
        for r in rows:
            try:
                date_ms = r["date_ms"]
                date_str = datetime.fromtimestamp(date_ms / 1000).strftime("%Y-%m-%d")
                to_insert.append((
                    code,
                    date_str,
                    float(r["open_price"]),
                    float(r["high_price"]),
                    float(r["low_price"]),
                    float(r["close_price"]),
                    None,                       # prev_close (REST 不返回，留空)
                    float(r["volume"]),
                    float(r["turnover"]),
                    batch_id,
                ))
            except (KeyError, ValueError, TypeError) as e:
                if errors < 5:
                    print(f"  [{code}] PARSE ERR: {e} | {r}")
                errors += 1
                continue

        if to_insert:
            try:
                con.executemany(
                    """
                    INSERT OR IGNORE INTO raw_kline_daily
                    (thscode, date, open, high, low, close, prev_close, volume, amount, batch_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    to_insert,
                )
                inserted += len(to_insert)
            except Exception as e:
                errors += 1
                if errors < 5:
                    print(f"  [{code}] INSERT ERR: {e}")
        else:
            skipped += 1

        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            print(f"  [{i+1}/{len(symbols)}] inserted={inserted} skipped={skipped} "
                  f"errors={errors} elapsed={elapsed:.0f}s")

    # 最终统计
    new_max = con.execute("SELECT MAX(date) FROM raw_kline_daily").fetchone()[0]
    print("\n[update_db] 完成:")
    print(f"  处理股票: {len(symbols)}")
    print(f"  新增行数: {inserted}")
    print(f"  跳过（无新数据）: {skipped}")
    print(f"  错误: {errors}")
    print(f"  max(date): {cur_max} → {new_max}")
    print(f"  耗时: {time.time() - t0:.0f}s")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

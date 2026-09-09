"""信号字段审计 — 逐股逐字段核验 conditions A-E + 排除项 + NaN。

run_audit 独立从 DuckDB 重算 v33 指标（不调用 compute_panel_indicators）——
审计的本质是验证，而非重用信号生成逻辑。若两者结果漂移，会立即报错。
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)


def run_audit(signal_json: Path, db_path: Path) -> list[tuple[str, str, str]]:
    """返回 errors 列表 [(thscode, field, msg), ...]；空列表 = 全部通过。

    字段标签:
      数据存在     — 缺 K 线 / 当日无数据
      条件A        — close < MA60
      条件B        — up_streak ∈ [3, 10]
      条件C        — pct_chg ∈ [2%, 6%]
      条件D        — macd_bar < 0
      条件E        — am60 ∈ [3e7, 3e8]
      数据完整性   — pct_chg 或 dif NaN
    """
    data = json.loads(signal_json.read_text(encoding="utf-8"))
    today_str = data["signal_date"]
    today_dt = pd.Timestamp(today_str)
    signals = data["signals"]

    con = duckdb.connect(str(db_path), read_only=True)
    errors: list[tuple[str, str, str]] = []

    try:
        for sig in signals:
            code = sig["thscode"]
            df = con.execute(
                "SELECT date, open, high, low, close, amount FROM v_daily "
                "WHERE thscode = ? ORDER BY date",
                [code],
            ).fetchdf()
            if df.empty:
                errors.append((code, "数据存在", "无历史数据"))
                continue
            df["date"] = pd.to_datetime(df["date"])

            # 重算指标（独立于 compute_panel_indicators，避免仅验证"scan 重跑了同一个函数"）
            df["ma20"] = df["close"].rolling(20, min_periods=20).mean()
            df["ma60"] = df["close"].rolling(60, min_periods=60).mean()
            df["ema12"] = df["close"].ewm(span=12, adjust=False).mean()
            df["ema26"] = df["close"].ewm(span=26, adjust=False).mean()
            df["dif"] = df["ema12"] - df["ema26"]
            df["dea"] = df["dif"].ewm(span=9, adjust=False).mean()
            df["macd_bar"] = 2 * (df["dif"] - df["dea"])
            df["prev_close"] = df["close"].shift(1)
            df["pct_chg"] = (df["close"] - df["prev_close"]) / df["prev_close"]
            df["am60"] = df["amount"].rolling(60, min_periods=60).mean()
            df["up_day"] = (df["pct_chg"] > 0).fillna(False)
            df["down_break"] = (~df["up_day"]).astype(int)
            df["up_id"] = df["down_break"].cumsum()
            df["up_streak"] = df.groupby(["up_id"]).cumcount() + 1
            df.loc[~df["up_day"], "up_streak"] = 0

            row = df[df["date"] == today_dt]
            if row.empty:
                errors.append((code, "数据存在", f"无 {today_str} K 线"))
                continue
            r = row.iloc[0]

            # A. close < MA60
            if not (r["close"] < r["ma60"]):
                errors.append((code, "条件A", f"close({r['close']}) < MA60({r['ma60']}) 不成立"))
            # B. up_streak ∈ [3, 10]
            if not (3 <= r["up_streak"] <= 10):
                errors.append((code, "条件B", f"up_streak={r['up_streak']} 不在 [3,10]"))
            # C. pct_chg ∈ [2%, 6%]
            pct = float(r["pct_chg"]) * 100 if pd.notna(r["pct_chg"]) else None
            if pct is None or not (2.0 <= pct <= 6.0):
                errors.append((code, "条件C", f"pct_chg={pct} 不在 [2,6]"))
            # D. macd_bar < 0
            if not (r["macd_bar"] < 0):
                errors.append((code, "条件D", f"macd_bar={r['macd_bar']} 不 < 0"))
            # E. am60 ∈ [3e7, 3e8]
            am = float(r["am60"]) if pd.notna(r["am60"]) else None
            if am is None or not (3e7 <= am <= 3e8):
                errors.append((code, "条件E", f"am60={am} 不在 [3e7,3e8]"))
            # 数据完整性
            if pd.isna(r["pct_chg"]) or pd.isna(r["dif"]):
                errors.append((code, "数据完整性", "pct_chg 或 dif NaN"))
    finally:
        con.close()

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="short_reversal 信号字段审计")
    parser.add_argument("--signals", default="short_reversal/results/today_signals.json")
    parser.add_argument(
        "--db-path",
        default="/Users/holeon/Library/Application Support/hithink-finance/data/market.duckdb",
    )
    args = parser.parse_args()

    errors = run_audit(Path(args.signals), Path(args.db_path))
    if not errors:
        print("✓ 全部通过")
    else:
        print(f"❌ 发现 {len(errors)} 处问题:")
        for code, field, msg in errors:
            print(f"  {code} [{field}] {msg}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
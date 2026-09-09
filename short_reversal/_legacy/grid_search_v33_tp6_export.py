"""
v33 TP=6% 全部交易导出 + 完整 HTML

策略: v33 信号 (柱转红) + TP=6% / SL=5% / Time=30
结果: 32 笔, 胜率 65.6%, +97.15%, MaxDD 14.26%, 平均持仓 4.6d

每笔展示:
- 信号日 + 入场日 + 出场日 + 出场原因 + pnl
- K线 (信号日前 60 天 → 入场后 30 天)
- MA20/MA60
- MACD (DIF/DEA/柱)
- 信号特征
"""
import json
from pathlib import Path

import pandas as pd
import duckdb

DB_PATH = "/Users/holeon/Library/Application Support/hithink-finance/data/market.duckdb"
CACHE_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "results"

INITIAL_CAPITAL = 1.0
SL_PCT = 0.05
TP_PCT = 0.06
MAX_HOLD = 30
UP_STREAK_RANGE = (3, 10)
PCT_CHG_RANGE = (0.02, 0.06)
LIQUIDITY_MIN = 30_000_000
LIQUIDITY_MAX = 3e8
BACKTEST_START = "2025-09-01"
BACKTEST_END = "2026-09-01"


def load_filters():
    hs300 = {x["thscode"] for x in json.load(open(CACHE_DIR / "hs300.json"))["data"]["item"]}
    zhongtou = set()
    for x in json.load(open(CACHE_DIR / "zhongtou_stocks.json")):
        t = x["ticker"]
        zhongtou.add(t + ".SH" if t.startswith(("6", "9")) else t + ".SZ")
    finance = set()
    for t in json.load(open(CACHE_DIR / "finance_stocks.json")):
        finance.add(t + ".SH" if t.startswith(("6", "9")) else t + ".SZ")
    return hs300, zhongtou, finance


def main():
    print("=" * 80)
    print("v33 TP=6% 全部交易导出 + 完整 HTML")
    print("=" * 80)

    con = duckdb.connect(DB_PATH, read_only=True)
    hs300, zhongtou, finance = load_filters()

    sql = """
    SELECT thscode, date, open, high, low, close, amount
    FROM v_daily
    WHERE date BETWEEN '2024-01-01' AND '2026-09-30'
      AND thscode IN (SELECT thscode FROM dim_symbol WHERE asset_type='a-share' AND exchange IN ('SH','SZ'))
    ORDER BY thscode, date
    """
    raw = con.execute(sql).fetchdf()
    raw["date"] = pd.to_datetime(raw["date"])

    all_excl = hs300 | zhongtou | finance
    raw = raw[~raw["thscode"].isin(all_excl)].reset_index(drop=True)
    raw = raw.sort_values(["thscode", "date"]).reset_index(drop=True)

    raw["ma20"] = raw.groupby("thscode")["close"].transform(lambda x: x.rolling(20, min_periods=20).mean())
    raw["ma60"] = raw.groupby("thscode")["close"].transform(lambda x: x.rolling(60, min_periods=60).mean())
    raw["ema12"] = raw.groupby("thscode")["close"].transform(lambda x: x.ewm(span=12, adjust=False).mean())
    raw["ema26"] = raw.groupby("thscode")["close"].transform(lambda x: x.ewm(span=26, adjust=False).mean())
    raw["dif"] = raw["ema12"] - raw["ema26"]
    raw["dea"] = raw.groupby("thscode")["dif"].transform(lambda x: x.ewm(span=9, adjust=False).mean())
    raw["macd_bar"] = 2 * (raw["dif"] - raw["dea"])
    raw["bar_prev"] = raw.groupby("thscode")["macd_bar"].shift(1)

    raw["pc"] = raw.groupby("thscode")["close"].shift(1)
    raw["pct_chg"] = (raw["close"] - raw["pc"]) / raw["pc"]

    raw["up_day"] = (raw["pct_chg"] > 0).fillna(False)
    raw["down_break"] = (~raw["up_day"]).astype(int)
    raw["up_id"] = raw["down_break"].cumsum()
    raw["up_streak"] = raw.groupby(["thscode", "up_id"]).cumcount() + 1
    raw.loc[~raw["up_day"], "up_streak"] = 0

    raw["am60"] = raw.groupby("thscode")["amount"].transform(lambda x: x.rolling(60, min_periods=60).mean())

    prices_map = {t: g.reset_index(drop=True) for t, g in raw.groupby("thscode")}

    # ===== v33 信号池 =====
    signals = raw[
        (raw["close"] < raw["ma60"])
        & (raw["up_streak"] >= UP_STREAK_RANGE[0])
        & (raw["up_streak"] <= UP_STREAK_RANGE[1])
        & (raw["pct_chg"] >= PCT_CHG_RANGE[0])
        & (raw["pct_chg"] <= PCT_CHG_RANGE[1])
        & (raw["macd_bar"] < 0)
        & (raw["am60"] >= LIQUIDITY_MIN)
        & (raw["am60"] <= LIQUIDITY_MAX)
        & raw["pct_chg"].notna()
        & raw["dif"].notna()
        & (raw["date"] >= BACKTEST_START)
        & (raw["date"] <= BACKTEST_END)
    ].reset_index(drop=True)

    signals = signals.sort_values("date").reset_index(drop=True)

    # ===== 回测 (TP=6%) =====
    capital = INITIAL_CAPITAL
    trades = []
    busy_until_date = None

    for _, sig in signals.iterrows():
        sig_date = sig["date"]
        if busy_until_date is not None and sig_date < busy_until_date:
            continue

        sp = prices_map.get(sig["thscode"])
        if sp is None:
            continue

        future = sp[sp["date"] > sig_date].reset_index(drop=True)
        if future.empty:
            continue
        entry_date_real = future.iloc[0]["date"]
        entry = future.iloc[0]["open"]
        future = future.iloc[1:].reset_index(drop=True)
        if future.empty:
            continue

        sl_p = entry * (1 + SL_PCT)
        tp_p = entry * (1 - TP_PCT)

        exit_price, exit_reason, exit_date, exit_day = None, None, None, None
        for i, row in future.iterrows():
            if i >= MAX_HOLD:
                exit_price = row["close"]
                exit_reason = "time"
                exit_date = row["date"]
                exit_day = i
                break
            if row["low"] <= tp_p:
                exit_price = tp_p
                exit_reason = "TP"
                exit_date = row["date"]
                exit_day = i
                break
            if row["high"] >= sl_p:
                exit_price = sl_p
                exit_reason = "SL"
                exit_date = row["date"]
                exit_day = i
                break

        if exit_price is None:
            k = min(MAX_HOLD - 1, len(future) - 1)
            if k < 0:
                continue
            exit_price = future.iloc[k]["close"]
            exit_reason = "time"
            exit_date = future.iloc[k]["date"]
            exit_day = k + 1

        pnl = (entry - exit_price) / entry
        capital *= (1 + pnl)
        trades.append({
            "thscode": sig["thscode"],
            "sig_date": sig_date,
            "entry_date": future.iloc[0]["date"],
            "entry_price": entry,
            "exit_date": exit_date,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "exit_day": exit_day,
            "pnl": pnl,
            "capital_after": capital,
            "sig_close": float(sig["close"]),
            "sig_dif": float(sig["dif"]),
            "sig_dea": float(sig["dea"]),
            "sig_macd_bar": float(sig["macd_bar"]),
            "sig_bar_prev": float(sig["bar_prev"]) if pd.notna(sig["bar_prev"]) else None,
            "sig_up_streak": int(sig["up_streak"]),
            "sig_pct_chg": float(sig["pct_chg"]),
            "sig_ma60": float(sig["ma60"]),
        })
        trades[-1]["entry_date"] = entry_date_real  # 修正: 真实入场日 = sig_date+1
        busy_until_date = exit_date + pd.Timedelta(days=1)

    print(f"\n回测完成: {len(trades)} 笔, 最终资金 {capital:.4f}")

    # ===== 导出每笔的图表数据 =====
    chart_data = []
    for t in trades:
        code = t["thscode"]
        sig_date = t["sig_date"]
        sp = prices_map.get(code)
        sig_idx_list = sp.index[sp["date"] == sig_date].tolist()
        if not sig_idx_list:
            continue
        sig_idx = sig_idx_list[0]

        # 信号日前 50 天 + 信号后 30 天 (为 TP=6% 留足够出场空间)
        start_idx = max(0, sig_idx - 50)
        end_idx = min(len(sp) - 1, sig_idx + 30)
        subset = sp.iloc[start_idx:end_idx + 1].reset_index(drop=True)
        local_sig_idx = sig_idx - start_idx
        local_entry_idx = local_sig_idx + 1

        candles = []
        for i, row in subset.iterrows():
            candles.append({
                "i": int(i),
                "date": row["date"].strftime("%Y-%m-%d"),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "ma20": float(row["ma20"]) if pd.notna(row["ma20"]) else None,
                "ma60": float(row["ma60"]) if pd.notna(row["ma60"]) else None,
                "dif": float(row["dif"]) if pd.notna(row["dif"]) else None,
                "dea": float(row["dea"]) if pd.notna(row["dea"]) else None,
                "macd_bar": float(row["macd_bar"]) if pd.notna(row["macd_bar"]) else None,
            })

        # 出场日在 candles 中的位置
        exit_date = t["exit_date"]
        local_exit_idx = None
        for i, c in enumerate(candles):
            if c["date"] == exit_date.strftime("%Y-%m-%d"):
                local_exit_idx = i
                break

        chart_data.append({
            "thscode": code,
            "sig_date": sig_date.strftime("%Y-%m-%d"),
            "sig_close": t["sig_close"],
            "sig_dif": t["sig_dif"],
            "sig_dea": t["sig_dea"],
            "sig_macd_bar": t["sig_macd_bar"],
            "sig_bar_prev": t["sig_bar_prev"],
            "sig_up_streak": t["sig_up_streak"],
            "sig_pct_chg": t["sig_pct_chg"] * 100,
            "sig_ma60": t["sig_ma60"],
            "entry_date": t["entry_date"].strftime("%Y-%m-%d") if hasattr(t["entry_date"], 'strftime') else t["entry_date"],
            "entry_price": t["entry_price"],
            "exit_date": t["exit_date"].strftime("%Y-%m-%d"),
            "exit_price": t["exit_price"],
            "exit_reason": t["exit_reason"],
            "exit_day": t["exit_day"],
            "pnl": t["pnl"],
            "capital_after": t["capital_after"],
            "candles": candles,
            "sig_idx": local_sig_idx,
            "entry_idx": local_entry_idx,
            "exit_idx": local_exit_idx,
        })

    output_path = OUTPUT_DIR / "chart_data_v33_tp6.json"
    with open(output_path, "w") as f:
        json.dump(chart_data, f, ensure_ascii=False, indent=1)
    print(f"图表数据已保存: {output_path}")
    print(f"  共 {len(chart_data)} 笔交易")

    # 计算月度统计
    monthly = {}
    for t in trades:
        m = t["sig_date"].strftime("%Y-%m")
        if m not in monthly:
            monthly[m] = {"n": 0, "wins": 0, "pnl_sum": 0.0, "cap_end": 1.0}
        monthly[m]["n"] += 1
        monthly[m]["pnl_sum"] += t["pnl"]
        if t["pnl"] > 0:
            monthly[m]["wins"] += 1
        monthly[m]["cap_end"] = t["capital_after"]

    metrics = {
        "trades": len(trades),
        "win_rate": sum(1 for t in trades if t["pnl"] > 0) / len(trades),
        "total_yield": capital - 1.0,
        "max_dd": max(
            (max(t["capital_after"] for t in trades[:i + 1]) - t["capital_after"])
            / max(t["capital_after"] for t in trades[:i + 1])
            for i, t in enumerate(trades)
        ) if trades else 0,
        "avg_pnl": sum(t["pnl"] for t in trades) / len(trades),
        "avg_hold": sum(t["exit_day"] for t in trades) / len(trades),
        "tp_n": sum(1 for t in trades if t["exit_reason"] == "TP"),
        "sl_n": sum(1 for t in trades if t["exit_reason"] == "SL"),
        "time_n": sum(1 for t in trades if t["exit_reason"] == "time"),
        "monthly": monthly,
    }

    metrics_path = OUTPUT_DIR / "trades_v33_tp6_meta.json"
    with open(metrics_path, "w") as f:
        json.dump({
            "version": "v33_tp6",
            "tp_pct": TP_PCT, "sl_pct": SL_PCT, "max_hold": MAX_HOLD,
            "metrics": metrics,
        }, f, ensure_ascii=False, indent=2)
    print(f"指标已保存: {metrics_path}")

    con.close()


if __name__ == "__main__":
    main()
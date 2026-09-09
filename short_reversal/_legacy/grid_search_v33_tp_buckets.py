"""
v33 TP 分桶扫描: 每 1% 一档 (0.5%-15%), 找最佳止盈区间

复用 v33 信号池, 仅改变 TP_PCT, 固定 SL=5% / Time=30.

输出:
- 表格: TP 档位 / 笔数 / 胜率 / 笔均 / 总收益 / MaxDD / TP 率 / 平均持仓
- 找最佳 TP 区间 (考虑稳健性)
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import duckdb

DB_PATH = "/Users/holeon/Library/Application Support/hithink-finance/data/market.duckdb"
CACHE_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "results"

INITIAL_CAPITAL = 1.0
SL_PCT = 0.05
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


def load_signals():
    con = duckdb.connect(DB_PATH, read_only=True)
    sql = """
    SELECT thscode, date, open, high, low, close, amount
    FROM v_daily
    WHERE date BETWEEN '2024-01-01' AND '2026-09-30'
      AND thscode IN (SELECT thscode FROM dim_symbol WHERE asset_type='a-share' AND exchange IN ('SH','SZ'))
    ORDER BY thscode, date
    """
    raw = con.execute(sql).fetchdf()
    raw["date"] = pd.to_datetime(raw["date"])

    hs300, zhongtou, finance = load_filters()
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

    raw["pc"] = raw.groupby("thscode")["close"].shift(1)
    raw["pct_chg"] = (raw["close"] - raw["pc"]) / raw["pc"]

    raw["am60"] = raw.groupby("thscode")["amount"].transform(lambda x: x.rolling(60, min_periods=60).mean())

    raw["up_day"] = (raw["pct_chg"] > 0).fillna(False)
    raw["down_break"] = (~raw["up_day"]).astype(int)
    raw["up_id"] = raw["down_break"].cumsum()
    raw["up_streak"] = raw.groupby(["thscode", "up_id"]).cumcount() + 1
    raw.loc[~raw["up_day"], "up_streak"] = 0

    con.close()

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

    prices_map = {t: g.reset_index(drop=True) for t, g in raw.groupby("thscode")}
    return signals, prices_map


def backtest(signals, prices_map, tp_pct, sl_pct=SL_PCT, max_hold=MAX_HOLD):
    signals = signals.sort_values("date").reset_index(drop=True)
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
        entry = future.iloc[0]["open"]
        future = future.iloc[1:].reset_index(drop=True)
        if future.empty:
            continue

        sl_p = entry * (1 + sl_pct)
        tp_p = entry * (1 - tp_pct)

        exit_price, exit_reason, exit_date, exit_day = None, None, None, None
        for i, row in future.iterrows():
            if i >= max_hold:
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
            k = min(max_hold - 1, len(future) - 1)
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
            "sd": sig_date,
            "entry_date": future.iloc[0]["date"],
            "pnl": pnl,
            "exit_reason": exit_reason,
            "exit_day": exit_day,
            "capital_after": capital,
            "m": sig_date.to_period("M"),
        })
        busy_until_date = exit_date + pd.Timedelta(days=1)

    return capital - 1.0, capital, trades


def max_dd(trades):
    peak = 1.0
    cap = 1.0
    md = 0.0
    for t in trades:
        if cap > peak:
            peak = cap
        dd = (peak - cap) / peak
        if dd > md:
            md = dd
        cap = t["capital_after"]
    return md


def month_excl_min_yield(trades):
    """最差月份剥离: 对每个月份排除后跑回测, 取最低收益."""
    if not trades:
        return 0.0
    months = sorted(set(t["m"] for t in trades))
    worst = 0.0
    for excl in months:
        sub = [t for t in trades if t["m"] != excl]
        if not sub:
            continue
        cap = 1.0
        for t in sub:
            cap *= (1 + t["pnl"])
        yld = cap - 1.0
        if yld < worst:
            worst = yld
    return worst


def main():
    print("=" * 80)
    print("v33 TP 分桶扫描 — 每 1% 一档")
    print("=" * 80)

    print("\n[1] 加载信号池...")
    signals, prices_map = load_signals()
    print(f"    信号数: {len(signals)}")

    print("\n[2] TP 档位扫描 (SL=5%, Time=30)")
    print("=" * 80)

    tp_buckets = [
        (0.005, "0.5%"),
        (0.01, "1%"),
        (0.02, "2%"),
        (0.03, "3% (当前)"),
        (0.04, "4%"),
        (0.05, "5%"),
        (0.06, "6%"),
        (0.07, "7%"),
        (0.08, "8%"),
        (0.09, "9%"),
        (0.10, "10%"),
        (0.11, "11%"),
        (0.12, "12%"),
        (0.13, "13%"),
        (0.14, "14%"),
        (0.15, "15%"),
    ]

    results = []
    for tp_pct, label in tp_buckets:
        yld, cap, trades = backtest(signals, prices_map, tp_pct=tp_pct)
        if not trades:
            results.append({"tp": label, "tp_pct": tp_pct, "n": 0})
            continue
        n = len(trades)
        win = sum(1 for t in trades if t["pnl"] > 0) / n
        avg = np.mean([t["pnl"] for t in trades])
        mdd = max_dd(trades)
        avg_day = np.mean([t["exit_day"] for t in trades])
        tp_n = sum(1 for t in trades if t["exit_reason"] == "TP")
        sl_n = sum(1 for t in trades if t["exit_reason"] == "SL")
        time_n = sum(1 for t in trades if t["exit_reason"] == "time")
        worst_m_excl = month_excl_min_yield(trades)
        pnls = [t["pnl"] for t in trades]
        sharpe = (np.mean(pnls) / np.std(pnls, ddof=1) * math.sqrt(n)) if n > 1 else 0
        results.append({
            "tp": label, "tp_pct": tp_pct,
            "n": n, "win": win, "avg": avg, "yld": yld,
            "cap": cap, "mdd": mdd, "avg_day": avg_day,
            "tp_n": tp_n, "sl_n": sl_n, "time_n": time_n,
            "sharpe": sharpe, "worst_m_excl": worst_m_excl,
            "trades": trades,
        })

    print(f"\n  {'TP':<14} {'笔数':>5} {'胜率':>7} {'笔均':>8} {'总收益':>10} "
          f"{'Sharpe':>7} {'MaxDD':>8} {'TP率':>5} {'SL率':>5} {'time率':>6} {'持仓':>7} "
          f"{'最差剥离':>10}")
    print(f"  {'-'*125}")
    for r in results:
        if r["n"] == 0:
            print(f"  {r['tp']:<14} {0:>5} -        -          -          -         -        -        -        -        -          -")
            continue
        marker = " ★" if r["yld"] >= 0.5 else (" ✓" if r["yld"] >= 0.3 else "")
        print(f"  {r['tp']:<14} {r['n']:>5} {r['win']*100:>6.1f}% "
              f"{r['avg']*100:>+7.2f}% {r['yld']*100:>+9.2f}%{marker} "
              f"{r['sharpe']:>6.2f} {r['mdd']*100:>7.2f}% "
              f"{r['tp_n']/r['n']*100:>4.0f}% {r['sl_n']/r['n']*100:>4.0f}% "
              f"{r['time_n']/r['n']*100:>5.0f}% {r['avg_day']:>6.1f}d "
              f"{r['worst_m_excl']*100:>+9.2f}%")

    valid = [r for r in results if r["n"] > 0]
    valid.sort(key=lambda x: x["yld"], reverse=True)
    print("\n" + "=" * 80)
    print("[3] Top 5 TP 档位 (按总收益)")
    print("=" * 80)
    print(f"  {'排名':<5} {'TP':<14} {'总收益':>10} {'Sharpe':>7} {'MaxDD':>8} {'笔均':>8} {'最差剥离':>10}")
    print(f"  {'-'*70}")
    for i, r in enumerate(valid[:5], 1):
        print(f"  {i:<5} {r['tp']:<14} {r['yld']*100:>+9.2f}% {r['sharpe']:>6.2f} "
              f"{r['mdd']*100:>7.2f}% {r['avg']*100:>+7.2f}% {r['worst_m_excl']*100:>+9.2f}%")

    print("\n" + "=" * 80)
    print("[4] Top 5 稳健档位 (按总收益 + MaxDD + 最差月份剥离 综合)")
    print("=" * 80)
    for r in valid:
        r["robust_score"] = r["yld"] / max(r["mdd"], 0.01)
    valid.sort(key=lambda x: x["robust_score"], reverse=True)
    print(f"  {'排名':<5} {'TP':<14} {'收益/MaxDD':>10} {'总收益':>10} {'MaxDD':>8} {'最差剥离':>10} {'Sharpe':>7}")
    print(f"  {'-'*70}")
    for i, r in enumerate(valid[:5], 1):
        print(f"  {i:<5} {r['tp']:<14} {r['robust_score']:>9.2f} "
              f"{r['yld']*100:>+9.2f}% {r['mdd']*100:>7.2f}% "
              f"{r['worst_m_excl']*100:>+9.2f}% {r['sharpe']:>6.2f}")

    print("\n" + "=" * 80)
    print("[5] TP 区间推荐")
    print("=" * 80)

    by_yield = sorted(valid, key=lambda x: x["yld"], reverse=True)
    top_yield = by_yield[0]
    by_robust = sorted(valid, key=lambda x: x["robust_score"], reverse=True)
    top_robust = by_robust[0]

    bucket_ranges = {
        "<1%": [r for r in valid if r["tp_pct"] < 0.01],
        "1%-3%": [r for r in valid if 0.01 <= r["tp_pct"] < 0.03],
        "3%-5%": [r for r in valid if 0.03 <= r["tp_pct"] < 0.05],
        "5%-7%": [r for r in valid if 0.05 <= r["tp_pct"] < 0.07],
        "7%-10%": [r for r in valid if 0.07 <= r["tp_pct"] < 0.10],
        ">=10%": [r for r in valid if r["tp_pct"] >= 0.10],
    }

    print(f"\n  {'区间':<10} {'档位':<35} {'平均收益':>10} {'平均MaxDD':>10} {'平均Sharpe':>10}")
    print(f"  {'-'*80}")
    best_range = None
    best_range_score = -1
    for label, items in bucket_ranges.items():
        if not items:
            continue
        avg_yld = np.mean([r["yld"] for r in items])
        avg_mdd = np.mean([r["mdd"] for r in items])
        avg_sharpe = np.mean([r["sharpe"] for r in items])
        score = avg_yld / max(avg_mdd, 0.01)
        if score > best_range_score:
            best_range_score = score
            best_range = label
        members = ", ".join(r["tp"] for r in items)
        print(f"  {label:<10} {members:<35} {avg_yld*100:>+9.2f}% "
              f"{avg_mdd*100:>9.2f}% {avg_sharpe:>9.2f}")

    print(f"\n  >>> 综合最佳区间: {best_range} (收益/MaxDD={best_range_score:.2f})")

    # 保存结果
    output = {
        "scan": "v33_tp_buckets",
        "signal_pool": len(signals),
        "results": [
            {k: v for k, v in r.items() if k != "trades"}
            for r in results
        ],
        "top_by_yield": [
            {"tp": r["tp"], "yld": r["yld"], "sharpe": r["sharpe"],
             "mdd": r["mdd"], "worst_m_excl": r["worst_m_excl"]}
            for r in by_yield[:5]
        ],
        "top_by_robust": [
            {"tp": r["tp"], "yld": r["yld"], "mdd": r["mdd"],
             "robust_score": r["robust_score"], "sharpe": r["sharpe"]}
            for r in by_robust[:5]
        ],
        "best_range": best_range,
        "best_range_score": best_range_score,
    }
    output_path = OUTPUT_DIR / "tp_bucket_scan_v33.json"
    with open(output_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {output_path}")


if __name__ == "__main__":
    main()
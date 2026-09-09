"""
v33 (柱转红) 全量沪深主板回测 — TP=6% / SL=5% / Time=30

改动: 仅替换股票池 ——
- 原 strategy_v33_final.py: 排除沪深300 + 中证500 + 金融 → 4883 只
- 本脚本: 沪深主板 (60/000/001/002/003 开头) → 3195 只, 不再排除任何行业/指数

策略逻辑完全不变:
- close < MA60
- up_streak ∈ [3, 10]
- pct_chg ∈ [2%, 6%]
- macd_bar < 0 (柱转红)
- am60 ∈ [3e7, 3e8]

回测区间: 2025-09-01 ~ 2026-09-01
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import duckdb

DB_PATH = "/Users/holeon/Library/Application Support/hithink-finance/data/market.duckdb"
OUTPUT_DIR = Path(__file__).parent / "results"

# === 策略参数 (与 v33 一致) ===
INITIAL_CAPITAL = 1.0
TP_PCT = 0.06
SL_PCT = 0.05
MAX_HOLD = 30
UP_STREAK_RANGE = (3, 10)
PCT_CHG_RANGE = (0.02, 0.06)
LIQUIDITY_MIN = 30_000_000
LIQUIDITY_MAX = 3e8
BACKTEST_START = "2025-09-01"
BACKTEST_END = "2026-09-01"

# === 主板定义 ===
SH_MAIN_PREFIXES = ("60", "601", "603", "605")
SZ_MAIN_PREFIXES = ("000", "001", "002", "003")
MAIN_BOARD_SUFFIXES = (".SH", ".SZ")


def is_main_board(code: str) -> bool:
    """沪深主板: SH (60/601/603/605 开头) + SZ (000/001/002/003 开头). 排除创业板/科创板/北交所."""
    if code.endswith(".SH"):
        return any(code.startswith(p) for p in SH_MAIN_PREFIXES)
    if code.endswith(".SZ"):
        return any(code.startswith(p) for p in SZ_MAIN_PREFIXES)
    return False


def main():
    con = duckdb.connect(DB_PATH, read_only=True)

    print("=" * 90)
    print("v33 (柱转红) — 全量沪深主板回测 (无 HS300/中证500/金融 排除)")
    print(f"TP={TP_PCT*100:.0f}% / SL={SL_PCT*100:.0f}% / Time={MAX_HOLD} / 区间 {BACKTEST_START} ~ {BACKTEST_END}")
    print("=" * 90)

    # ===== 1. 加载数据 =====
    sql = """
    SELECT thscode, date, open, high, low, close, amount
    FROM v_daily
    WHERE date BETWEEN '2024-01-01' AND '2026-09-30'
      AND thscode IN (SELECT thscode FROM dim_symbol WHERE asset_type='a-share' AND exchange IN ('SH','SZ'))
    ORDER BY thscode, date
    """
    raw = con.execute(sql).fetchdf()
    raw["date"] = pd.to_datetime(raw["date"])

    print(f"\n[1] 加载全 A 股: {len(raw)} 条 × {raw['thscode'].nunique()} 只")

    # ===== 2. 仅保留主板 =====
    raw = raw[raw["thscode"].apply(is_main_board)].reset_index(drop=True)
    print(f"[2] 仅保留沪深主板后: {len(raw)} 条 × {raw['thscode'].nunique()} 只")
    print(f"    (SH 主板: 60/601/603/605 开头; SZ 主板: 000/001/002/003 开头)")
    print(f"    排除: 创业板 (300/301), 科创板 (688/689), 北交所")

    raw = raw.sort_values(["thscode", "date"]).reset_index(drop=True)

    # ===== 3. 计算特征 =====
    print("\n[3] 计算特征 (MA20/MA60/EMA12/EMA26/DIF/DEA/MACD柱/连阳/涨幅/流动性)...")
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

    prices_map = {t: g.reset_index(drop=True) for t, g in raw.groupby("thscode")}

    # ===== 4. 生成信号池 (策略不变) =====
    print("\n[4] 生成 v33 信号池 (与原策略一致)...")
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
    print(f"    信号池: {len(signals)} 笔")

    # ===== 5. 回测 =====
    print("\n[5] 回测中...")
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
            "entry_price": float(entry),
            "exit_date": exit_date,
            "exit_price": float(exit_price),
            "exit_reason": exit_reason,
            "exit_day": int(exit_day),
            "pnl": float(pnl),
            "capital_after": float(capital),
        })
        busy_until_date = exit_date + pd.Timedelta(days=1)

    print(f"    实际成交易: {len(trades)} 笔")

    # ===== 6. 指标计算 =====
    final_capital = capital
    total_yield = final_capital - 1.0
    n = len(trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    win_rate = wins / n if n > 0 else 0
    avg_pnl = np.mean([t["pnl"] for t in trades]) if trades else 0
    avg_hold = np.mean([t["exit_day"] for t in trades]) if trades else 0
    pnls = [t["pnl"] for t in trades]
    sharpe = (np.mean(pnls) / np.std(pnls, ddof=1) * math.sqrt(n)) if n > 1 else 0

    tp_n = sum(1 for t in trades if t["exit_reason"] == "TP")
    sl_n = sum(1 for t in trades if t["exit_reason"] == "SL")
    time_n = sum(1 for t in trades if t["exit_reason"] == "time")

    # MaxDD
    peak = INITIAL_CAPITAL
    md = 0.0
    for t in trades:
        if t["capital_after"] > peak:
            peak = t["capital_after"]
        dd = (peak - t["capital_after"]) / peak
        if dd > md:
            md = dd

    # ===== 7. 月度剥离 =====
    df_trades = pd.DataFrame([
        {"pnl": t["pnl"], "m": t["sig_date"].to_period("M")}
        for t in trades
    ])
    months_in_data = sorted(df_trades["m"].astype(str).unique()) if not df_trades.empty else []
    worst_m_excl_yield = 0.0
    worst_m_excl_label = "-"
    for excl in months_in_data:
        sub = df_trades[df_trades["m"].astype(str) != excl]
        if len(sub) == 0:
            continue
        cap = 1.0
        for _, row in sub.iterrows():
            cap *= (1 + row["pnl"])
        yld = cap - 1.0
        if yld < worst_m_excl_yield:
            worst_m_excl_yield = yld
            worst_m_excl_label = excl

    # ===== 8. 输出 =====
    print("\n" + "=" * 90)
    print("[回测结果]")
    print("=" * 90)
    print(f"  信号池: {len(signals)} 笔")
    print(f"  成交易: {n} 笔")
    print(f"  胜率: {win_rate*100:.1f}% ({wins}/{n})")
    print(f"  笔均: {avg_pnl*100:+.2f}%")
    print(f"  最终资金: {final_capital:.4f}")
    print(f"  总收益: {total_yield*100:+.2f}%")
    print(f"  Sharpe: {sharpe:.2f}")
    print(f"  MaxDD: {md*100:.2f}%")
    print(f"  平均持仓: {avg_hold:.1f} 天")
    print(f"  出场: TP {tp_n} / SL {sl_n} / time {time_n}")
    print(f"  最差月份剥离: {worst_m_excl_label} → {worst_m_excl_yield*100:+.2f}%")

    # 月度明细
    print("\n[月度明细]")
    print(f"  {'月份':<10} {'笔数':>5} {'胜率':>7} {'笔均':>8} {'月末资金':>10} {'累计收益':>10}")
    print("  " + "-" * 60)
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
    for m in sorted(monthly.keys()):
        st = monthly[m]
        wr = st["wins"] / st["n"] * 100
        print(f"  {m:<10} {st['n']:>5} {wr:>6.1f}% {st['pnl_sum']/st['n']*100:>+7.2f}% "
              f"{st['cap_end']:>10.4f} {(st['cap_end']-1)*100:>+9.2f}%")

    # 月度剥离表
    print("\n[月度剥离稳健性]")
    print(f"  {'剔除月':<10} {'剩余笔数':>8} {'胜率':>7} {'最终资金':>10} {'收益':>10} {'状态':>6}")
    print("  " + "-" * 60)
    for excl in months_in_data:
        sub = df_trades[df_trades["m"].astype(str) != excl]
        if len(sub) == 0:
            continue
        cap = 1.0
        for _, row in sub.iterrows():
            cap *= (1 + row["pnl"])
        n_sub = len(sub)
        wr = (sub["pnl"] > 0).sum() / n_sub * 100
        ok = "✓" if cap > 1.0 else "✗"
        print(f"  {excl:<10} {n_sub:>8} {wr:>6.1f}% {cap:>10.4f} {(cap-1)*100:>+9.2f}% {ok:>6}")

    # ===== 9. 与原 32 笔对比 =====
    print("\n" + "=" * 90)
    print("[对比原结果 (排除 HS300/中证500/金融, 4883 只股票池)]")
    print("=" * 90)
    print(f"  {'指标':<14} {'原结果':>14} {'本次 (全量主板)':>18} {'差异':>14}")
    print("  " + "-" * 70)
    compare_rows = [
        ("笔数", 32, n, f"{n-32:+d}"),
        ("胜率", "65.6%", f"{win_rate*100:.1f}%", f"{(win_rate-0.656)*100:+.1f}%"),
        ("总收益", "+97.15%", f"{total_yield*100:+.2f}%", f"{(total_yield-0.9715)*100:+.2f}%"),
        ("MaxDD", "14.26%", f"{md*100:.2f}%", f"{(md-0.1426)*100:+.2f}%"),
        ("平均持仓", "4.6d", f"{avg_hold:.1f}d", f"{avg_hold-4.6:+.1f}d"),
    ]
    for label, old, new, diff in compare_rows:
        print(f"  {label:<14} {str(old):>14} {str(new):>18} {str(diff):>14}")

    # ===== 10. 保存 =====
    output = {
        "version": "v33_mainboard_tp6",
        "universe": "沪深主板 (60/000/001/002/003, 共 3195 只), 不再排除 HS300/中证500/金融",
        "tp_pct": TP_PCT, "sl_pct": SL_PCT, "max_hold": MAX_HOLD,
        "strategy_unchanged": True,
        "metrics": {
            "trades": n,
            "win_rate": win_rate,
            "total_yield": total_yield,
            "max_dd": md,
            "sharpe": sharpe,
            "avg_pnl": avg_pnl,
            "avg_hold": avg_hold,
            "tp_n": tp_n, "sl_n": sl_n, "time_n": time_n,
            "worst_m_excl_label": worst_m_excl_label,
            "worst_m_excl_yield": worst_m_excl_yield,
        },
        "trades": trades,
    }
    out_path = OUTPUT_DIR / "backtest_v33_mainboard_tp6.json"
    with open(out_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果已保存: {out_path}")

    con.close()


if __name__ == "__main__":
    main()

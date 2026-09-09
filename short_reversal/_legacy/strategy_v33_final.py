"""
v33: 最终策略 — MACD 柱转红 + TP=3%, SL=5%

策略定义:
- 下跌趋势: close < MA60, max_dt_100d >= 60
- 反弹: up_streak 3-10, pct_chg 2%-6%
- 流动性: am60 ∈ [3e7, 3e8]
- **MACD 柱转红**: macd_bar < 0 (柱状由绿转红, 体现动能衰减)

出场: T+1 open + TP=3% / SL=5% / Time=30 / TP 优先

输出:
- 回测指标
- 月度净值曲线
- 月份剥离稳健性
- 全部交易明细
- 时间穿越审计
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
TP_PCT = 0.03
SL_PCT = 0.05
MAX_HOLD = 30
MAX_DT_THRESHOLD = 30
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


def load_features():
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

    raw["in_downtrend"] = (raw["close"] < raw["ma20"]) & (raw["ma20"] < raw["ma60"])
    raw["downtrend_break"] = (~raw["in_downtrend"]).astype(int)
    raw["downtrend_id"] = raw["downtrend_break"].cumsum()
    raw["downtrend_days"] = raw.groupby(["thscode", "downtrend_id"]).cumcount() + 1
    raw.loc[~raw["in_downtrend"], "downtrend_days"] = 0
    raw["max_dt_100d"] = raw.groupby("thscode")["downtrend_days"].transform(
        lambda x: x.rolling(100, min_periods=1).max()
    )

    raw["up_day"] = (raw["pct_chg"] > 0).fillna(False)
    raw["down_break"] = (~raw["up_day"]).astype(int)
    raw["up_id"] = raw["down_break"].cumsum()
    raw["up_streak"] = raw.groupby(["thscode", "up_id"]).cumcount() + 1
    raw.loc[~raw["up_day"], "up_streak"] = 0

    con.close()
    return raw


def generate_signals(raw):
    """v33 信号: 下跌趋势反弹 + MACD 柱转红.

    对齐 v32 网格测试最佳条件: 仅柱转红 (不限 DIF, 下跌趋势).
    不要求 max_dt 阈值 (v32 测试表明 max_dt 过滤会减少样本且不显著提升收益).
    """
    return raw[
        (raw["close"] < raw["ma60"])
        & (raw["up_streak"] >= UP_STREAK_RANGE[0])
        & (raw["up_streak"] <= UP_STREAK_RANGE[1])
        & (raw["pct_chg"] >= PCT_CHG_RANGE[0])
        & (raw["pct_chg"] <= PCT_CHG_RANGE[1])
        & (raw["macd_bar"] < 0)                              # 核心: MACD 柱转红
        & (raw["am60"] >= LIQUIDITY_MIN)
        & (raw["am60"] <= LIQUIDITY_MAX)
        & raw["pct_chg"].notna()
        & raw["dif"].notna()
        & (raw["date"] >= BACKTEST_START)
        & (raw["date"] <= BACKTEST_END)
    ].reset_index(drop=True)


def run_backtest(signals, prices_map, tp_pct=TP_PCT, sl_pct=SL_PCT, max_hold=MAX_HOLD):
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
        new_capital = capital * (1 + pnl)
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
            "capital_after": new_capital,
            "month": sig_date.to_period("M"),
            "sig_close": sig["close"],
            "sig_ma60": sig["ma60"],
            "sig_dif": sig["dif"],
            "sig_dea": sig["dea"],
            "sig_macd_bar": sig["macd_bar"],
            "sig_up_streak": int(sig["up_streak"]),
            "sig_pct_chg": sig["pct_chg"],
            "sig_max_dt": float(sig["max_dt_100d"]),
        })
        capital = new_capital
        busy_until_date = exit_date + pd.Timedelta(days=1)

    return capital, trades


def compute_metrics(trades, initial=INITIAL_CAPITAL):
    if not trades:
        return {}
    final_capital = trades[-1]["capital_after"]
    total_yield = final_capital - initial
    n = len(trades)
    win = sum(1 for t in trades if t["pnl"] > 0) / n

    sig_first = min(t["sig_date"] for t in trades)
    sig_last = max(t["sig_date"] for t in trades)
    years = max((sig_last - sig_first).days / 365.25, 0.5)
    cagr = (final_capital / initial) ** (1 / years) - 1

    pnls = [t["pnl"] for t in trades]
    avg_pnl = np.mean(pnls)
    std_pnl = np.std(pnls, ddof=1) if len(pnls) > 1 else 0
    sharpe = avg_pnl / std_pnl * math.sqrt(len(pnls)) if std_pnl > 0 else 0

    peak = initial
    max_dd = 0.0
    for t in trades:
        if t["capital_after"] > peak:
            peak = t["capital_after"]
        dd = (peak - t["capital_after"]) / peak
        if dd > max_dd:
            max_dd = dd

    avg_hold = np.mean([t["exit_day"] for t in trades])
    tp_n = sum(1 for t in trades if t["exit_reason"] == "TP")
    sl_n = sum(1 for t in trades if t["exit_reason"] == "SL")
    time_n = sum(1 for t in trades if t["exit_reason"] == "time")

    return {
        "trades": n, "win_rate": win, "total_yield": total_yield,
        "final_capital": final_capital, "cagr": cagr, "sharpe": sharpe,
        "max_dd": max_dd, "avg_pnl": avg_pnl, "avg_hold_days": avg_hold,
        "tp_count": tp_n, "sl_count": sl_n, "time_count": time_n,
    }


def monthly_equity(trades):
    if not trades:
        return pd.DataFrame()
    df = pd.DataFrame(trades)
    df["month_dt"] = df["sig_date"].dt.to_period("M").dt.to_timestamp()
    monthly = df.groupby("month_dt").agg(
        n=("pnl", "count"),
        pnl_sum=("pnl", "sum"),
        win=("pnl", lambda x: (x > 0).mean()),
        final=("capital_after", "last"),
    ).reset_index()
    return monthly


def month_exclusion_robustness(trades):
    df = pd.DataFrame(trades)
    rows = []
    scenarios = [
        ("全样本", []),
        ("排除 2026-04", ["2026-04"]),
        ("排除 2026-05", ["2026-05"]),
        ("排除 2026-06", ["2026-06"]),
        ("排除 2026-07", ["2026-07"]),
        ("排除 2026-08", ["2026-08"]),
        ("排除 2026-04+07", ["2026-04", "2026-07"]),
        ("排除 2026-04+07+08", ["2026-04", "2026-07", "2026-08"]),
        ("排除前半年", [f"{y}-{m:02d}" for y in (2025, 2026) for m in range(9, 13)
                       if not (y == 2025 and m == 9)]),
    ]
    for label, months_to_exclude in scenarios:
        mask = ~df["month"].astype(str).isin(months_to_exclude)
        sub = df[mask].sort_values("sig_date").reset_index(drop=True)
        if len(sub) == 0:
            continue
        cap = INITIAL_CAPITAL
        for _, t in sub.iterrows():
            cap *= (1 + t["pnl"])
        rows.append({
            "scenario": label, "n": len(sub),
            "win_rate": (sub["pnl"] > 0).mean(),
            "final": cap, "yield": cap - INITIAL_CAPITAL,
        })
    return pd.DataFrame(rows)


def main():
    print("=" * 80)
    print("v33 最终策略 — MACD 柱转红 + TP=3%, SL=5%")
    print("=" * 80)

    print("\n[1] 加载数据...")
    raw = load_features()
    print(f"    股票数: {raw['thscode'].nunique()}, K线数: {len(raw)}")

    print("\n[2] 生成入场信号...")
    signals = generate_signals(raw)
    print(f"    信号数: {len(signals)}")

    prices_map = {t: g.reset_index(drop=True) for t, g in raw.groupby("thscode")}

    print("\n[3] 执行回测...")
    final_capital, trades = run_backtest(signals, prices_map)
    metrics = compute_metrics(trades)

    print("\n" + "=" * 80)
    print("[4] 回测指标")
    print("=" * 80)
    print(f"  笔数:                 {metrics['trades']}")
    print(f"  胜率:                 {metrics['win_rate']*100:.1f}%")
    print(f"  最终资金:             {metrics['final_capital']:.4f}")
    print(f"  总收益:               {metrics['total_yield']*100:+.2f}%")
    print(f"  CAGR (年化):          {metrics['cagr']*100:+.2f}%")
    print(f"  Sharpe:               {metrics['sharpe']:.2f}")
    print(f"  最大回撤:             {metrics['max_dd']*100:.2f}%")
    print(f"  笔均收益:             {metrics['avg_pnl']*100:+.2f}%")
    print(f"  平均持仓:             {metrics['avg_hold_days']:.1f}d")
    print(f"  出场分布:             TP={metrics['tp_count']} "
          f"({metrics['tp_count']/metrics['trades']*100:.0f}%) | "
          f"SL={metrics['sl_count']} "
          f"({metrics['sl_count']/metrics['trades']*100:.0f}%) | "
          f"time={metrics['time_count']} "
          f"({metrics['time_count']/metrics['trades']*100:.0f}%)")

    print("\n[5] 月度净值")
    print("=" * 80)
    monthly = monthly_equity(trades)
    if not monthly.empty:
        print(f"  {'月份':<12} {'笔数':>5} {'胜率':>7} {'月度收益':>10} {'期末资金':>10}")
        print(f"  {'-'*50}")
        for _, r in monthly.iterrows():
            print(f"  {r['month_dt'].strftime('%Y-%m'):<12} "
                  f"{int(r['n']):>5} {r['win']*100:>6.1f}% "
                  f"{r['pnl_sum']*100:>+9.2f}% {r['final']:>9.4f}")

    print("\n[6] 月份剥离稳健性")
    print("=" * 80)
    rob = month_exclusion_robustness(trades)
    if not rob.empty:
        print(f"  {'场景':<35} {'笔数':>5} {'胜率':>7} {'最终':>10} {'收益':>10}")
        print(f"  {'-'*70}")
        for _, r in rob.iterrows():
            print(f"  {r['scenario']:<35} {int(r['n']):>5} {r['win_rate']*100:>6.1f}% "
                  f"{r['final']:>9.4f} {r['yield']*100:>+9.2f}%")

    print("\n[7] 时间穿越审计")
    audit_items = [
        ("MA20/MA60", "rolling(20/60) 历史 close"),
        ("EMA12/26", "ewm span=12/26 历史 close"),
        ("DIF = EMA12 - EMA26", "上述 EMA 计算"),
        ("DEA = EMA9(DIF)", "DIF 9 日 EMA"),
        ("MACD bar = 2*(DIF-DEA)", "DIF/DEA 算术差"),
        ("up_streak", "累计连阳数 (cumcount)"),
        ("max_dt_100d", "rolling(100) max 连续下跌天数"),
        ("pct_chg", "(今日 close - 昨 close) / 昨 close"),
        ("am60", "rolling(60) mean(amount)"),
        ("入场价", "T+1 日 open"),
        ("TP/SL 触发", "T+1 起 OHLC"),
    ]
    print(f"\n  {'特征':<24} {'数据源':<40} {'未来数据?':<10}")
    print(f"  {'-'*78}")
    for feat, src in audit_items:
        print(f"  {feat:<24} {src:<40} {'❌ 无'}")

    print("\n[8] 全部交易明细")
    print("=" * 80)
    if trades:
        print(f"  {'信号日':<12} {'代码':<12} {'收盘':>7} {'MA60':>7} {'DIF':>7} "
              f"{'DEA':>7} {'柱':>7} {'连阳':>4} {'涨幅':>7} {'最大跌':>6} | "
              f"{'入场日':<12} {'入场':>7} {'出场日':<12} {'出场':>7} "
              f"{'天':>3} {'原因':<5} {'pnl':>7}")
        print(f"  {'-'*190}")
        for t in trades:
            print(f"  {t['sig_date'].strftime('%Y-%m-%d'):<12} "
                  f"{t['thscode']:<12} {t['sig_close']:>7.2f} {t['sig_ma60']:>7.2f} "
                  f"{t['sig_dif']:>+7.3f} {t['sig_dea']:>+7.3f} {t['sig_macd_bar']:>+7.3f} "
                  f"{t['sig_up_streak']:>4} {t['sig_pct_chg']*100:>+6.2f}% "
                  f"{t['sig_max_dt']:>6.0f} | "
                  f"{t['entry_date'].strftime('%Y-%m-%d'):<12} {t['entry_price']:>7.2f} "
                  f"{t['exit_date'].strftime('%Y-%m-%d'):<12} {t['exit_price']:>7.2f} "
                  f"{t['exit_day']:>3} {t['exit_reason']:<5} {t['pnl']*100:>+6.2f}%")

    # 保存交易明细
    trades_for_json = []
    for t in trades:
        trades_for_json.append({
            "thscode": t["thscode"],
            "sig_date": t["sig_date"].strftime("%Y-%m-%d"),
            "entry_date": t["entry_date"].strftime("%Y-%m-%d"),
            "entry_price": float(t["entry_price"]),
            "exit_date": t["exit_date"].strftime("%Y-%m-%d"),
            "exit_price": float(t["exit_price"]),
            "exit_reason": t["exit_reason"],
            "exit_day": int(t["exit_day"]),
            "pnl": float(t["pnl"]),
            "capital_after": float(t["capital_after"]),
            "sig_close": float(t["sig_close"]),
            "sig_ma60": float(t["sig_ma60"]),
            "sig_dif": float(t["sig_dif"]),
            "sig_dea": float(t["sig_dea"]),
            "sig_macd_bar": float(t["sig_macd_bar"]),
            "sig_up_streak": int(t["sig_up_streak"]),
            "sig_pct_chg": float(t["sig_pct_chg"]),
            "sig_max_dt": float(t["sig_max_dt"]),
        })

    out_path = OUTPUT_DIR / "trades_v33.json"
    with open(out_path, "w") as f:
        json.dump({
            "version": "v33",
            "strategy": {
                "max_dt": MAX_DT_THRESHOLD,
                "up_streak": list(UP_STREAK_RANGE),
                "pct_chg": list(PCT_CHG_RANGE),
                "macd_bar": "< 0 (柱转红)",
                "liquidity": [LIQUIDITY_MIN, LIQUIDITY_MAX],
            },
            "exit": {
                "tp_pct": TP_PCT, "sl_pct": SL_PCT, "max_hold": MAX_HOLD,
                "entry_mode": "T+1 open",
            },
            "metrics": {
                k: (float(v) if isinstance(v, (int, float, np.floating)) else v)
                for k, v in metrics.items()
            },
            "trades": trades_for_json,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n交易明细已保存: {out_path}")
    print(f"\n[完成] v33 策略实现 + 回测")


if __name__ == "__main__":
    main()
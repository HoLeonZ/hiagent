"""
v33 TP=6% 数据完整性审计

逐笔检查项:
1. 信号日收盘价 close
2. 入场价 = T+1 日 open
3. 出场价: TP=entry*0.94, SL=entry*1.05, time=signal后第N天close
4. 出场原因: T+1..T+N 的 high/low 是否触发 TP/SL
5. pnl = (entry - exit_price) / entry
6. MACD 特征: DIF/DEA/macd_bar
7. 连阳数 / 涨幅 / close<MA60

最终资金: 逐笔复利相乘

输出: 每笔交易 audit 结果 + 错误汇总
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
    print("=" * 90)
    print("v33 TP=6% 数据完整性审计 — 逐笔逐数字")
    print("=" * 90)

    con = duckdb.connect(DB_PATH, read_only=True)
    hs300, zhongtou, finance = load_filters()

    # ===== 加载原始数据并重算所有特征 =====
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
    raw["pc"] = raw.groupby("thscode")["close"].shift(1)
    raw["pct_chg"] = (raw["close"] - raw["pc"]) / raw["pc"]
    raw["am60"] = raw.groupby("thscode")["amount"].transform(lambda x: x.rolling(60, min_periods=60).mean())
    raw["up_day"] = (raw["pct_chg"] > 0).fillna(False)
    raw["down_break"] = (~raw["up_day"]).astype(int)
    raw["up_id"] = raw["down_break"].cumsum()
    raw["up_streak"] = raw.groupby(["thscode", "up_id"]).cumcount() + 1
    raw.loc[~raw["up_day"], "up_streak"] = 0

    # 生成 v33 信号池
    signals = raw[
        (raw["close"] < raw["ma60"])
        & (raw["up_streak"] >= 3) & (raw["up_streak"] <= 10)
        & (raw["pct_chg"] >= 0.02) & (raw["pct_chg"] <= 0.06)
        & (raw["macd_bar"] < 0)
        & (raw["am60"] >= 30_000_000) & (raw["am60"] <= 3e8)
        & raw["pct_chg"].notna() & raw["dif"].notna()
        & (raw["date"] >= "2025-09-01") & (raw["date"] <= "2026-09-01")
    ].reset_index(drop=True)

    signals = signals.sort_values("date").reset_index(drop=True)
    prices_map = {t: g.reset_index(drop=True) for t, g in raw.groupby("thscode")}

    # ===== 独立重算回测 =====
    capital = INITIAL_CAPITAL
    recomputed_trades = []
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
        future2 = future.iloc[1:].reset_index(drop=True)
        if future2.empty:
            continue

        sl_p = entry * (1 + SL_PCT)
        tp_p = entry * (1 - TP_PCT)

        exit_price = exit_reason = exit_date = exit_day = None
        for i, row in future2.iterrows():
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
            k = min(MAX_HOLD - 1, len(future2) - 1)
            if k < 0:
                continue
            exit_price = future2.iloc[k]["close"]
            exit_reason = "time"
            exit_date = future2.iloc[k]["date"]
            exit_day = k + 1

        pnl = (entry - exit_price) / entry
        capital *= (1 + pnl)
        recomputed_trades.append({
            "thscode": sig["thscode"],
            "sig_date": sig_date,
            "sig_close": float(sig["close"]),
            "sig_dif": float(sig["dif"]),
            "sig_dea": float(sig["dea"]),
            "sig_macd_bar": float(sig["macd_bar"]),
            "sig_up_streak": int(sig["up_streak"]),
            "sig_pct_chg": float(sig["pct_chg"]),
            "sig_ma60": float(sig["ma60"]),
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

    # ===== 加载输出文件 =====
    with open(OUTPUT_DIR / "chart_data_v33_tp6.json") as f:
        output_data = json.load(f)
    with open(OUTPUT_DIR / "trades_v33_tp6_meta.json") as f:
        meta = json.load(f)

    print(f"\n[数据加载] 独立重算: {len(recomputed_trades)} 笔 | 输出文件: {len(output_data)} 笔")
    assert len(recomputed_trades) == len(output_data), "笔数不一致!"
    print(f"[✓] 笔数一致: {len(recomputed_trades)}")

    # ===== 逐笔对比 =====
    print("\n" + "=" * 90)
    print("[逐笔审计]")
    print("=" * 90)
    print(f"  {'#':>3} {'代码':<10} {'信号日':<12} {'项目':<14} {'独立重算':>14} {'输出文件':>14} {'匹配':>6}")
    print("  " + "-" * 90)

    errors = []
    tolerance_pct = 0.0001  # 价格容差
    tolerance_diff = 0.0005  # DIF/DEA 容差

    for i, (rt, ot) in enumerate(zip(recomputed_trades, output_data), 1):
        # 每笔的字段对比
        checks = [
            ("信号日", rt["sig_date"].strftime("%Y-%m-%d"), ot["sig_date"]),
            ("代码", rt["thscode"], ot["thscode"]),
            ("sig_close", rt["sig_close"], ot["sig_close"]),
            ("sig_dif", rt["sig_dif"], ot["sig_dif"]),
            ("sig_dea", rt["sig_dea"], ot["sig_dea"]),
            ("sig_macd_bar", rt["sig_macd_bar"], ot["sig_macd_bar"]),
            ("sig_up_streak", rt["sig_up_streak"], ot["sig_up_streak"]),
            ("sig_pct_chg", rt["sig_pct_chg"] * 100, ot["sig_pct_chg"]),
            ("sig_ma60", rt["sig_ma60"], ot["sig_ma60"]),
            ("entry_date", rt["entry_date"].strftime("%Y-%m-%d"), ot["entry_date"]),
            ("entry_price", rt["entry_price"], ot["entry_price"]),
            ("exit_date", rt["exit_date"].strftime("%Y-%m-%d"), ot["exit_date"]),
            ("exit_price", rt["exit_price"], ot["exit_price"]),
            ("exit_reason", rt["exit_reason"], ot["exit_reason"]),
            ("exit_day", rt["exit_day"], ot["exit_day"]),
            ("pnl", rt["pnl"] * 100, ot["pnl"] * 100),
            ("capital_after", rt["capital_after"], ot["capital_after"]),
        ]

        trade_errors = []
        for label, recomputed, recorded in checks:
            if isinstance(recomputed, (int, float)) and isinstance(recorded, (int, float)):
                diff = abs(recomputed - recorded)
                if label in ("sig_dif", "sig_dea", "sig_macd_bar"):
                    tol = tolerance_diff
                else:
                    tol = tolerance_pct * max(abs(recomputed), abs(recorded), 1.0)
                ok = diff <= tol
            else:
                ok = recomputed == recorded

            if not ok:
                trade_errors.append((label, recomputed, recorded))

        # 打印每笔汇总
        if not trade_errors:
            print(f"  {i:>3} {rt['thscode']:<10} {rt['sig_date'].strftime('%Y-%m-%d'):<12} "
                  f"{'全部字段':<14} {'OK':>14} {'OK':>14} {'✓':>6}")
        else:
            print(f"  {i:>3} {rt['thscode']:<10} {rt['sig_date'].strftime('%Y-%m-%d'):<12} "
                  f"{'错误项':<14} {'':>14} {'':>14} {'✗':>6}")
            for label, recomputed, recorded in trade_errors:
                print(f"      {' ':>3} {' ':<10} {' ':<12} {label:<14} "
                      f"{recomputed!s:>14} {recorded!s:>14} {'✗':>6}")
                errors.append({
                    "trade_idx": i, "thscode": rt["thscode"],
                    "sig_date": rt["sig_date"].strftime("%Y-%m-%d"),
                    "field": label, "recomputed": recomputed,
                    "recorded": recorded,
                })

    # ===== 指标对比 =====
    print("\n" + "=" * 90)
    print("[最终资金复利验证]")
    print("=" * 90)

    final_capital = INITIAL_CAPITAL
    for t in recomputed_trades:
        final_capital *= (1 + t["pnl"])

    print(f"  独立复利最终资金: {final_capital:.10f}")
    print(f"  最后笔 capital_after: {recomputed_trades[-1]['capital_after']:.10f}")
    print(f"  输出文件报告最终: {meta['metrics']['total_yield']*100:+.2f}% (即资金 {meta['metrics']['total_yield'] + 1.0:.4f})")

    # 复利相乘 vs 累加验证
    sum_pnl = sum(t["pnl"] for t in recomputed_trades)
    compound_yield = final_capital - 1.0
    additive_yield = sum_pnl
    print(f"\n  复利收益: {compound_yield*100:+.4f}%")
    print(f"  累加收益 (仅参考, 非真实收益): {additive_yield*100:+.4f}%")

    # 月份剥离
    print("\n" + "=" * 90)
    print("[月份剥离复算]")
    print("=" * 90)
    df = pd.DataFrame([
        {"pnl": t["pnl"], "m": t["sig_date"].to_period("M")}
        for t in recomputed_trades
    ])

    months_to_test = ["2025-09", "2025-10", "2025-11", "2025-12",
                      "2026-01", "2026-02", "2026-03", "2026-04",
                      "2026-05", "2026-06", "2026-07", "2026-08"]
    print(f"  {'排除月份':<12} {'剩余笔数':>8} {'胜率':>8} {'最终资金':>12} {'收益':>10}")
    print("  " + "-" * 60)
    for excl in months_to_test:
        sub = df[df["m"].astype(str) != excl]
        if len(sub) == 0:
            print(f"  {excl:<12} {0:>8} -        -            -")
            continue
        cap = INITIAL_CAPITAL
        for _, row in sub.iterrows():
            cap *= (1 + row["pnl"])
        n = len(sub)
        win = (sub["pnl"] > 0).sum() / n
        print(f"  {excl:<12} {n:>8} {win*100:>7.1f}% {cap:>11.4f} {(cap-1)*100:>+9.2f}%")

    # 出场原因分布
    print("\n" + "=" * 90)
    print("[出场原因分布 + 平均持仓 + 单笔明细]")
    print("=" * 90)
    print(f"  {'#':>3} {'代码':<10} {'信号日':<12} {'入场日':<12} {'入场':>8} {'出场日':<12} {'出场':>8} "
          f"{'天数':>4} {'原因':<5} {'pnl%':>7} {'复利资金':>10}")
    print("  " + "-" * 110)
    cap2 = INITIAL_CAPITAL
    for i, t in enumerate(recomputed_trades, 1):
        cap2 *= (1 + t["pnl"])
        print(f"  {i:>3} {t['thscode']:<10} {t['sig_date'].strftime('%Y-%m-%d'):<12} "
              f"{t['entry_date'].strftime('%Y-%m-%d'):<12} {t['entry_price']:>8.2f} "
              f"{t['exit_date'].strftime('%Y-%m-%d'):<12} {t['exit_price']:>8.2f} "
              f"{t['exit_day']:>4} {t['exit_reason']:<5} {t['pnl']*100:>+6.2f}% {cap2:>10.4f}")

    # ===== 总结 =====
    print("\n" + "=" * 90)
    print("[审计结论]")
    print("=" * 90)
    if not errors:
        print(f"  ✅ 全部 {len(recomputed_trades)} 笔 × 17 个字段, 无差异")
    else:
        print(f"  ❌ 发现 {len(errors)} 处差异:")
        for e in errors:
            print(f"      #{e['trade_idx']} {e['thscode']} @ {e['sig_date']}: "
                  f"{e['field']} 独立={e['recomputed']} vs 输出={e['recorded']}")

    # TP/SL/time 统计
    from collections import Counter
    rc = Counter(t["exit_reason"] for t in recomputed_trades)
    wins = sum(1 for t in recomputed_trades if t["pnl"] > 0)
    print(f"\n  出场分布: {dict(rc)}")
    print(f"  胜率: {wins/len(recomputed_trades)*100:.1f}% ({wins}/{len(recomputed_trades)})")
    print(f"  MaxDD: ", end="")
    peak = INITIAL_CAPITAL
    md = 0.0
    for t in recomputed_trades:
        if t["capital_after"] > peak:
            peak = t["capital_after"]
        dd = (peak - t["capital_after"]) / peak
        if dd > md:
            md = dd
    print(f"{md*100:.4f}%")
    print(f"  最终资金: {final_capital:.6f} (总收益 {compound_yield*100:+.4f}%)")

    con.close()


if __name__ == "__main__":
    main()
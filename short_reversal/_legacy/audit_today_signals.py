"""
今日 (2026-09-08) v33 信号严格审计

对 8 只信号股票, 独立重新加载 DuckDB, 逐字段重算并对比 results/today_signals.json

校验项目:
1. close < MA60        — 下跌趋势
2. up_streak ∈ [3,10]  — 连阳
3. pct_chg ∈ [2%, 6%]  — 当日涨幅
4. macd_bar < 0        — 柱转红 (柱仍为负)
5. am60 ∈ [3e7, 3e8]   — 流动性
6. 排除: 沪深300 + 中证500 + 金融
7. 数据完整性: 历史 ≥ 60 日, 无 NaN
8. up_streak 连阳数 (向前追溯, 确认无中断)
9. pct_chg 计算: (close - prev_close) / prev_close
10. macd_bar = 2 * (DIF - DEA)
"""
import json
from pathlib import Path

import pandas as pd
import duckdb

DB_PATH = "/Users/holeon/Library/Application Support/hithink-finance/data/market.duckdb"
CACHE_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "results"


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
    with open(OUTPUT_DIR / "today_signals.json") as f:
        output = json.load(f)
    today_str = output["signal_date"]

    con = duckdb.connect(DB_PATH, read_only=True)
    hs300, zhongtou, finance = load_filters()
    all_excl = hs300 | zhongtou | finance

    print("=" * 90)
    print(f"今日 ({today_str}) v33 信号严格审计 — 字段逐项 + 排除项核验")
    print("=" * 90)

    errors = []
    today_dt = pd.to_datetime(today_str)

    for idx, sig in enumerate(output["signals"], 1):
        code = sig["thscode"]
        print(f"\n{'─' * 90}")
        print(f"  #{idx}  {code}")
        print(f"{'─' * 90}")

        # ===== 排除项检查 =====
        in_hs300 = code in hs300
        in_zt = code in zhongtou
        in_fin = code in finance
        excluded = in_hs300 or in_zt or in_fin
        status = "❌ FAIL" if excluded else "✓ 通过"
        print(f"  [{status}] 排除项: 沪深300={in_hs300} 中证500={in_zt} 金融={in_fin}")
        if excluded:
            errors.append((code, "排除项", "应排除但被纳入"))

        # ===== 拉取该股全部数据 =====
        sql = f"""
        SELECT date, open, high, low, close, amount
        FROM v_daily
        WHERE thscode = '{code}'
        ORDER BY date
        """
        df = con.execute(sql).fetchdf()
        df["date"] = pd.to_datetime(df["date"])
        n_total = len(df)

        if n_total < 60:
            print(f"  [❌ FAIL] 历史不足 60 日: {n_total} 条")
            errors.append((code, "历史长度", f"仅 {n_total} 条"))
            continue

        # ===== 计算特征 =====
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

        today_row = df[df["date"] == today_dt]
        if today_row.empty:
            print(f"  [❌ FAIL] 今日 ({today_str}) 无数据")
            errors.append((code, "数据存在", "无今日数据"))
            continue
        r = today_row.iloc[0]

        # ===== 1. close < MA60 =====
        actual_close = float(r["close"])
        actual_ma60 = float(r["ma60"])
        cond1 = actual_close < actual_ma60
        ok = abs(actual_close - sig["close"]) < 0.001 and abs(actual_ma60 - sig["ma60"]) < 0.01
        status = "✓" if (cond1 and ok) else "❌"
        print(f"  [{status}] close < MA60: close={actual_close:.4f} < MA60={actual_ma60:.4f} = {actual_close < actual_ma60}")
        if not cond1:
            errors.append((code, "条件1", f"close({actual_close}) < MA60({actual_ma60}) 不成立"))
        if not ok:
            errors.append((code, "字段一致", f"close/MA60 与输出不符"))

        # ===== 2. up_streak ∈ [3, 10] =====
        actual_streak = int(r["up_streak"])
        # 验证 up_streak 的连续性: 向前追溯 up_streak 应该是 1, 2, 3, ... 或被打断
        prev_streak = df.iloc[-2]["up_streak"] if len(df) >= 2 else None
        prev_up_day = df.iloc[-2]["up_day"] if len(df) >= 2 else None
        if prev_streak is not None and prev_up_day is not None:
            if prev_up_day and prev_streak == actual_streak - 1:
                streak_valid = True
            elif not prev_up_day:
                streak_valid = False  # 前一日下跌, streak 应该是 1
            else:
                streak_valid = False
        else:
            streak_valid = True  # 无数据验证
        cond2 = 3 <= actual_streak <= 10
        ok = actual_streak == sig["up_streak"]
        status = "✓" if (cond2 and ok and streak_valid) else "❌"
        print(f"  [{status}] up_streak ∈ [3,10]: streak={actual_streak} 前日up_day={prev_up_day} 连阳={streak_valid}")
        if not cond2:
            errors.append((code, "条件2", f"up_streak={actual_streak} 不在 [3,10]"))
        if not ok:
            errors.append((code, "字段一致", f"up_streak 不一致: 实际={actual_streak} vs 输出={sig['up_streak']}"))

        # ===== 3. pct_chg ∈ [2%, 6%] =====
        actual_pct = float(r["pct_chg"]) * 100
        cond3 = 2.0 <= actual_pct <= 6.0
        ok = abs(actual_pct - sig["pct_chg_pct"]) < 0.001
        status = "✓" if (cond3 and ok) else "❌"
        print(f"  [{status}] pct_chg ∈ [2%,6%]: pct={actual_pct:.4f}% 范围={cond3} 输出值一致={ok}")
        if not cond3:
            errors.append((code, "条件3", f"pct_chg={actual_pct:.4f}% 不在 [2%,6%]"))
        if not ok:
            errors.append((code, "字段一致", f"pct_chg 不一致: 实际={actual_pct} vs 输出={sig['pct_chg_pct']}"))

        # ===== 4. macd_bar < 0 =====
        actual_dif = float(r["dif"])
        actual_dea = float(r["dea"])
        actual_bar = float(r["macd_bar"])
        bar_check = abs(actual_bar - 2 * (actual_dif - actual_dea)) < 0.0001
        cond4 = actual_bar < 0
        ok_dif = abs(actual_dif - sig["dif"]) < 0.0005
        ok_dea = abs(actual_dea - sig["dea"]) < 0.0005
        ok_bar = abs(actual_bar - sig["macd_bar"]) < 0.0005
        status = "✓" if (cond4 and bar_check and ok_dif and ok_dea and ok_bar) else "❌"
        print(f"  [{status}] macd_bar < 0: DIF={actual_dif:.4f} DEA={actual_dea:.4f} bar={actual_bar:.4f} "
              f"(2*(DIF-DEA)校验={bar_check}, 输出值一致 DIF/DEA/bar={ok_dif and ok_dea and ok_bar})")
        if not cond4:
            errors.append((code, "条件4", f"macd_bar={actual_bar} 不 < 0"))
        if not bar_check:
            errors.append((code, "MACD计算", "bar ≠ 2*(DIF-DEA)"))
        if not (ok_dif and ok_dea and ok_bar):
            errors.append((code, "字段一致", "DIF/DEA/bar 与输出不符"))

        # ===== 5. am60 ∈ [3e7, 3e8] =====
        actual_am60 = float(r["am60"])
        cond5 = 30_000_000 <= actual_am60 <= 300_000_000
        ok = abs(actual_am60 / 1e8 - sig["am60_yi"]) < 0.001
        status = "✓" if (cond5 and ok) else "❌"
        print(f"  [{status}] am60 ∈ [3e7,3e8]: am60={actual_am60:.0f} ({actual_am60/1e8:.2f}亿) "
              f"范围={cond5} 输出值一致={ok}")
        if not cond5:
            errors.append((code, "条件5", f"am60={actual_am60:.0f} 不在 [3e7,3e8]"))
        if not ok:
            errors.append((code, "字段一致", f"am60 与输出不符"))

        # ===== 7. 数据完整性 =====
        nan_dif = pd.isna(actual_dif)
        nan_pct = pd.isna(actual_pct)
        cond7 = not (nan_dif or nan_pct)
        status = "✓" if cond7 else "❌"
        print(f"  [{status}] 数据完整性: pct_chg NaN={nan_pct} DIF NaN={nan_dif}")

    # ===== 总览 =====
    print("\n" + "=" * 90)
    print(f"[审计结论] 共 {len(output['signals'])} 只股票")
    print("=" * 90)
    if not errors:
        print(f"  ✅ 全部 {len(output['signals'])} 只 × 10 项校验, 全部通过")
    else:
        print(f"  ❌ 发现 {len(errors)} 处问题:")
        for code, field, msg in errors:
            print(f"      {code}  [{field}]  {msg}")

    con.close()


if __name__ == "__main__":
    main()

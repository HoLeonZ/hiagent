"""
v33 (柱转红) + TP=6% 信号扫描 — 今日 (2026-09-08) 触发 → 明日 (2026-09-09) 开盘做空

用法: python3 scan_today_signals.py

输出: 控制台 + results/today_signals.json
"""
import json
from pathlib import Path

import pandas as pd
import duckdb

DB_PATH = "/Users/holeon/Library/Application Support/hithink-finance/data/market.duckdb"
CACHE_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "results"

# v33 信号参数
UP_STREAK_RANGE = (3, 10)
PCT_CHG_RANGE = (0.02, 0.06)
LIQUIDITY_MIN = 30_000_000
LIQUIDITY_MAX = 3e8
TP_PCT = 0.06
SL_PCT = 0.05


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
    con = duckdb.connect(DB_PATH, read_only=True)

    # 确认最新数据日期
    max_date_row = con.execute("SELECT MAX(date) FROM v_daily").fetchone()
    today_str = str(max_date_row[0])
    print("=" * 80)
    print(f"v33 (柱转红) + TP={TP_PCT*100:.0f}% 今日信号扫描")
    print(f"今日 (信号日) = {today_str}")
    print(f"明日 (开盘做空) = {pd.to_datetime(today_str) + pd.Timedelta(days=1):%Y-%m-%d} (实际开盘日)")
    print("=" * 80)

    # 拉取 a-股全部股票数据 (数据已含到今日收盘)
    sql = """
    SELECT thscode, date, open, high, low, close, amount
    FROM v_daily
    WHERE thscode IN (SELECT thscode FROM dim_symbol WHERE asset_type='a-share' AND exchange IN ('SH','SZ'))
    ORDER BY thscode, date
    """
    raw = con.execute(sql).fetchdf()
    raw["date"] = pd.to_datetime(raw["date"])

    # 排除沪深300 + 中证500 + 金融板块
    hs300, zhongtou, finance = load_filters()
    all_excl = hs300 | zhongtou | finance
    raw = raw[~raw["thscode"].isin(all_excl)].reset_index(drop=True)
    raw = raw.sort_values(["thscode", "date"]).reset_index(drop=True)

    print(f"\n[1] 加载 {len(raw)} 条记录 × {raw['thscode'].nunique()} 只股票")
    print(f"    排除后可用股票池: {raw['thscode'].nunique()} 只")

    # 计算特征
    print("\n[2] 计算技术特征 (MA20/MA60/EMA12/EMA26/DIF/DEA/MACD柱/连阳/涨幅/流动性)...")
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

    print("[3] 应用 v33 信号条件 (今日触发)...")
    # v33 核心: close<MA60 + up_streak∈[3,10] + pct_chg∈[2%,6%] + macd_bar<0 + am60∈[3e7,3e8]
    today_signals = raw[
        (raw["date"] == pd.to_datetime(today_str))
        & (raw["close"] < raw["ma60"])
        & (raw["up_streak"] >= UP_STREAK_RANGE[0])
        & (raw["up_streak"] <= UP_STREAK_RANGE[1])
        & (raw["pct_chg"] >= PCT_CHG_RANGE[0])
        & (raw["pct_chg"] <= PCT_CHG_RANGE[1])
        & (raw["macd_bar"] < 0)
        & (raw["am60"] >= LIQUIDITY_MIN)
        & (raw["am60"] <= LIQUIDITY_MAX)
        & raw["pct_chg"].notna()
        & raw["dif"].notna()
    ].copy().reset_index(drop=True)

    print("\n" + "=" * 80)
    print(f"[结果] 今日 ({today_str}) 触发 v33 信号: {len(today_signals)} 只")
    print("=" * 80)

    if len(today_signals) == 0:
        print("\n>>> 今日无任何股票触发 v33 信号. 明日无操作. <<<\n")
        # 仍保存空结果
        with open(OUTPUT_DIR / "today_signals.json", "w") as f:
            json.dump({
                "signal_date": today_str,
                "next_trade_date": str(pd.to_datetime(today_str) + pd.Timedelta(days=1)),
                "tp_pct": TP_PCT,
                "sl_pct": SL_PCT,
                "count": 0,
                "signals": [],
            }, f, ensure_ascii=False, indent=2)
        return

    # 计算明日 (T+1) 开盘价对应的 TP/SL 目标位
    today_signals["entry_price_est"] = today_signals["close"]  # 估算用今日收盘; 实际成交价是明日开盘
    today_signals["tp_target"] = today_signals["entry_price_est"] * (1 - TP_PCT)
    today_signals["sl_target"] = today_signals["entry_price_est"] * (1 + SL_PCT)
    today_signals["tp_target_from_close"] = today_signals["tp_target"]
    today_signals["sl_target_from_close"] = today_signals["sl_target"]

    # 按 pct_chg 降序排列 (反弹越强, 信号越典型)
    today_signals = today_signals.sort_values("pct_chg", ascending=False).reset_index(drop=True)

    print(f"\n{'#':>3} {'代码':<10} {'今日涨幅':>8} {'连阳':>5} "
          f"{'close':>8} {'MA60':>8} {'DIF':>8} {'DEA':>8} {'MACD柱':>8} {'am60(亿)':>9} "
          f"{'预估开仓价':>10} {'TP目标':>8} {'SL止损':>8}")
    print("-" * 130)

    out_signals = []
    for i, row in today_signals.iterrows():
        idx = i + 1
        print(f"{idx:>3} {row['thscode']:<10} "
              f"{row['pct_chg']*100:>+7.2f}% {int(row['up_streak']):>5} "
              f"{row['close']:>8.2f} {row['ma60']:>8.2f} "
              f"{row['dif']:>8.4f} {row['dea']:>8.4f} {row['macd_bar']:>8.4f} "
              f"{row['am60']/1e8:>9.2f} "
              f"{row['entry_price_est']:>10.2f} {row['tp_target']:>8.2f} {row['sl_target']:>8.2f}")
        out_signals.append({
            "thscode": row["thscode"],
            "signal_date": today_str,
            "close": float(row["close"]),
            "ma60": float(row["ma60"]),
            "pct_chg_pct": float(row["pct_chg"] * 100),
            "up_streak": int(row["up_streak"]),
            "dif": float(row["dif"]),
            "dea": float(row["dea"]),
            "macd_bar": float(row["macd_bar"]),
            "am60_yi": float(row["am60"] / 1e8),
            "tp_target_est_from_close": float(row["tp_target"]),
            "sl_target_est_from_close": float(row["sl_target"]),
        })

    # 计算明日实际开盘日 (跳过周末)
    next_day = pd.to_datetime(today_str) + pd.Timedelta(days=1)
    while next_day.weekday() >= 5:  # 周六=5, 周日=6
        next_day += pd.Timedelta(days=1)
    next_str = next_day.strftime("%Y-%m-%d")

    print(f"\n>>> 共 {len(today_signals)} 只股票触发 v33 信号")
    print(f">>> 明日 ({next_str}) 开盘价做空, TP={TP_PCT*100:.0f}% / SL={SL_PCT*100:.0f}%")
    print(f">>> 注意: 实际成交价 = 明日开盘价, 上述 TP/SL 是基于今日收盘价的估算")
    print(f">>> 真实 TP/SL 应在明日开盘后立即挂单: TP=开仓价×0.94, SL=开仓价×1.05 <<<\n")

    # 保存 JSON
    output = {
        "strategy": "v33 (MACD柱转红) + TP=6%",
        "signal_date": today_str,
        "next_trade_date_open": next_str,
        "tp_pct": TP_PCT,
        "sl_pct": SL_PCT,
        "max_hold": 30,
        "data_source": "hithink-finance DuckDB (2026-09-08 收盘)",
        "excluded": ["沪深300", "中证500", "金融板块"],
        "count": len(out_signals),
        "signals": out_signals,
        "note": "TP/SL 目标基于今日收盘价估算; 实际成交按明日开盘价计算 TP=开仓价×0.94, SL=开仓价×1.05",
    }
    output_path = OUTPUT_DIR / "today_signals.json"
    with open(output_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"信号清单已保存: {output_path}")

    con.close()


if __name__ == "__main__":
    main()

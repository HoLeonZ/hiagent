"""向量化信号扫描 — 直接在 DuckDB+pandas 上重算策略 5 条件,秒级出结果。

策略的 5 条件 (replay_strategy_v3.Phase3V3Strategy._all_conditions):
  E 流动性: am60 ∈ [3e7, 3e8]
  A V1:    close < ma60 AND below_ma60_ratio_60 ≥ 0.6
         (V5 cascade_price 在我们的 preset 里不用)
  B 连阳:   up_streak ∈ [3, 10]
  C 涨跌幅: pct_chg ∈ [pct_chg_low, pct_chg_high]
  D MACD:   dif < 0 AND dea < 0 AND |bar| < |prev_bar|

回测引擎 (run_backtest_v3) 是 per-stock cerebro 单跑,这里向量化版本
只对 T 日 close 这一行做 5 条件,所以不重复 warmup 逻辑、也不进出场。
结果与策略 100% 等价(LAHEAD-001 信号层 vs 执行层已经解耦)。
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from hiagent_config import DB_PATH

from short_reversal.presets import get_preset

logger = logging.getLogger(__name__)


def _load_panel(db_path: Path, signal_date: str, lookback_days: int = 400) -> pd.DataFrame:
    start = (pd.Timestamp(signal_date) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute(
            "SELECT thscode, date, open, high, low, close, amount, volume "
            "FROM v_daily "
            "WHERE date BETWEEN ? AND ? "
            "ORDER BY thscode, date",
            [start, signal_date],
        ).fetchdf()
    finally:
        con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


def _compute_indicators(panel: pd.DataFrame) -> pd.DataFrame:
    """按 thscode 分组计算全部 5 条件需要的指标。"""
    df = panel.sort_values(["thscode", "date"]).reset_index(drop=True)
    g = df.groupby("thscode", group_keys=False)

    # MA family
    df["ma5"] = g["close"].transform(lambda s: s.rolling(5, min_periods=5).mean())
    df["ma10"] = g["close"].transform(lambda s: s.rolling(10, min_periods=10).mean())
    df["ma20"] = g["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["ma60"] = g["close"].transform(lambda s: s.rolling(60, min_periods=60).mean())

    # A: below_ma60_ratio_60
    df["below_ma60"] = (df["close"] < df["ma60"]).astype(float)
    df["below_ma60_ratio_60"] = g["below_ma60"].transform(
        lambda s: s.rolling(60, min_periods=60).mean()
    )

    # C: pct_chg
    df["pct_chg"] = g["close"].pct_change()

    # E: am60 (60-day rolling mean of amount)
    df["am60"] = g["amount"].transform(lambda s: s.rolling(60, min_periods=60).mean())

    # D: MACD dif / dea / bar
    ema12 = g["close"].transform(lambda s: s.ewm(span=12, adjust=False).mean())
    ema26 = g["close"].transform(lambda s: s.ewm(span=26, adjust=False).mean())
    df["dif"] = ema12 - ema26
    df["dea"] = g["dif"].transform(lambda s: s.ewm(span=9, adjust=False).mean())
    df["bar"] = df["dif"] - df["dea"]
    df["prev_bar"] = g["bar"].shift(1)

    # B: up_streak (per-stock counter)
    def _streak(s: pd.Series) -> pd.Series:
        up = (s > s.shift(1)).astype(int)
        # 首个 bar 强制 0
        up.iloc[0] = 0
        # 连续累加;一旦 0/NaN 重置
        out = []
        cur = 0
        for v in up:
            if v == 1:
                cur += 1
            else:
                cur = 0
            out.append(cur)
        return pd.Series(out, index=s.index)

    df["up_streak"] = g["close"].transform(_streak)
    return df


def _filter_signals(df: pd.DataFrame, preset: dict, signal_date: str) -> pd.DataFrame:
    """取 T 日最后一行,按 5 条件过滤。"""
    cfg = preset
    tp = cfg["tp_pct"]
    sl = cfg["sl_pct"]
    mh = cfg["max_hold"]
    pc_low = cfg.get("pct_chg_low", 0.02)
    pc_high = cfg.get("pct_chg_high", 0.06)
    a_cond = cfg.get("a_condition", "default")

    # T-day row = 各 thscode 的最后一行
    last_g = df.groupby("thscode").tail(1).reset_index(drop=True)

    # 5 条件
    # E: 流动性
    cond_e = (last_g["am60"] >= 3e7) & (last_g["am60"] <= 3e8)
    # A: 默认 V1 (close < ma60 AND below_ratio ≥ 0.6)
    if a_cond == "cascade_price":
        cond_a = (
            (last_g["ma5"] < last_g["ma10"])
            & (last_g["ma10"] < last_g["ma20"])
            & (last_g["ma20"] < last_g["ma60"])
            & (last_g["close"] < last_g["ma20"])
        )
    else:
        cond_a = (
            (last_g["close"] < last_g["ma60"])
            & (last_g["below_ma60_ratio_60"] >= 0.6)
        )
    # B: 连阳
    cond_b = (last_g["up_streak"] >= 3) & (last_g["up_streak"] <= 10)
    # C: 涨跌幅
    cond_c = (last_g["pct_chg"] >= pc_low) & (last_g["pct_chg"] <= pc_high)
    # D: MACD
    cond_d = (
        (last_g["dif"] < 0)
        & (last_g["dea"] < 0)
        & (last_g["bar"].abs() < last_g["prev_bar"].abs())
    )

    mask = cond_e & cond_a & cond_b & cond_c & cond_d
    out = last_g.loc[mask, ["thscode", "date", "close", "amount"]].copy()
    out = out.rename(columns={"date": "signal_date", "close": "last_close"})
    out["signal_date"] = out["signal_date"].dt.strftime("%Y-%m-%d")
    out = out.sort_values("last_close").reset_index(drop=True)
    return out


def _scan_preset(
    preset_name: str,
    signal_date: str,
    db_path: Path,
    exclude_st: bool = True,
) -> tuple[pd.DataFrame, list[dict]]:
    """返回 (signals, st_excluded) — 第二个元素是被 ST 过滤掉的票,供报告用。"""
    cfg = get_preset(preset_name)
    # 必须先按 preset 自己的 universe 过滤,否则会把科创板/创业板/北交所塞进结果。
    from short_reversal.universe import load_universe_asof
    universe = set(load_universe_asof(cfg["universe"], signal_date, db_path))
    panel = _load_panel(db_path, signal_date)
    if panel.empty:
        return pd.DataFrame(), []
    panel = panel[panel["thscode"].isin(universe)].reset_index(drop=True)

    df = _compute_indicators(panel)
    sig = _filter_signals(df, cfg, signal_date)
    sig.insert(0, "preset", preset_name)

    # ST 启发式过滤:只在 5 条件命中后调用,避免对全 universe 拉名称 (5k+ 次慢)。
    # ST 状态是时变的,启发式只是兜底 — 真正下单前还需要券商 app 二次确认融券资格。
    st_excluded: list[dict] = []
    if exclude_st and not sig.empty:
        from short_reversal.st_filter import filter_signal_codes_for_st
        sig, st_excluded = filter_signal_codes_for_st(sig, signal_date)

    return sig, st_excluded


def main() -> int:
    ap = argparse.ArgumentParser(description="向量化短反转信号扫描")
    ap.add_argument(
        "--preset", action="append", default=None,
        help="preset 名,可重复传;默认 = 两个内置 preset 都跑",
    )
    ap.add_argument("--signal-date", default=None,
                    help="信号日 (T 日 close). 默认 DuckDB 最新交易日")
    ap.add_argument("--entry-date", default=None,
                    help="T+1 开盘成交日 (仅展示用)")
    ap.add_argument("--db-path", default=str(DB_PATH))
    ap.add_argument("--include-st", action="store_true",
                    help="保留 ST/*ST 票 (默认剔除)")
    args = ap.parse_args()

    db_path = Path(args.db_path)
    signal_date = args.signal_date or pd.Timestamp.now().strftime("%Y-%m-%d")
    if signal_date == pd.Timestamp.now().strftime("%Y-%m-%d"):
        # fallback to DB latest
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            row = con.execute("SELECT MAX(date) FROM v_daily").fetchone()
        finally:
            con.close()
        signal_date = str(row[0])
    entry_date = args.entry_date or "T+1"

    presets = args.preset or [
        "v33_mainboard_tp6_sl005_mh5_realistic",
        "v33_mainboard_tp2_sl05_dneg",
    ]

    print(f"=== short_reversal 向量化信号扫描 ===")
    print(f"信号日 (T)    : {signal_date}  (close 时满足 A/B/C/D/E 5 条件)")
    print(f"预计成交 (T+1): {entry_date}")
    print(f"presets       : {presets}")
    print()

    by_preset: dict[str, pd.DataFrame] = {}
    st_excluded_global: list[dict] = []
    for preset_name in presets:
        cfg = get_preset(preset_name)
        print(f"[scan] preset={preset_name} "
              f"(tp={cfg['tp_pct']*100:.2f}% sl={cfg['sl_pct']*100:.4f}% "
              f"mh={cfg['max_hold']} pc=[{cfg.get('pct_chg_low', 0.02)*100:.1f}%, "
              f"{cfg.get('pct_chg_high', 0.06)*100:.1f}%]) universe={cfg['universe']}")
        sig, st_excl = _scan_preset(
            preset_name, signal_date, db_path, exclude_st=not args.include_st,
        )
        by_preset[preset_name] = sig
        for r in st_excl:
            st_excluded_global.append(r)
        print(f"  → {len(sig)} 个信号"
              + (f" (剔除 {len(st_excl)} 只 ST)" if st_excl else ""))
        print()

    for preset_name, sig in by_preset.items():
        cfg = get_preset(preset_name)
        print(f"=== {preset_name} ({len(sig)} 个信号) ===")
        if sig.empty:
            print("  (空)")
            print()
            continue
        print(f"  {'thscode':<12}{'signal_date':<14}{'last_close':>12}{'amount':>16}")
        print("  " + "-" * 60)
        for _, r in sig.iterrows():
            print(f"  {r['thscode']:<12}{r['signal_date']:<14}"
                  f"{r['last_close']:>12.2f}{r['amount']:>16.0f}")
        print()

    all_codes = set()
    for sig in by_preset.values():
        all_codes.update(sig["thscode"])
    intersect = set.intersection(*[set(s["thscode"] for _, s in sig.iterrows()) for sig in by_preset.values()]) \
        if all(len(sig) > 0 for sig in by_preset.values()) else set()

    print(f"=== 跨 preset 对比 ===")
    print(f"  至少一个 preset 触发: {len(all_codes)} 只")
    if len(by_preset) > 1:
        print(f"  全部 preset 同时触发: {len(intersect)} 只")
        if intersect:
            print(f"  重叠标的: {sorted(intersect)}")
        # 差异标的
        for name, sig in by_preset.items():
            others = set()
            for n2, s2 in by_preset.items():
                if n2 != name:
                    others.update(s2["thscode"])
            only = set(sig["thscode"]) - others
            if only:
                print(f"  仅有 {name} 触发 ({len(only)} 只): {sorted(only)[:10]}"
                      + (f" ... (+{len(only)-10} more)" if len(only) > 10 else ""))
    print()

    if st_excluded_global:
        print(f"=== ST/*ST 剔除报告 (启发式: 命名前缀) ===")
        seen = set()
        for r in sorted(st_excluded_global, key=lambda r: r["thscode"]):
            if r["thscode"] in seen:
                continue
            seen.add(r["thscode"])
            print(f"  {r['thscode']:<12} {r['name']}")
        print(f"  提示: 启发式只在命名前缀做兜底, 改名窗口期 / 摘帽初期可能滞后。")
        print(f"        下单前请到券商 app 二次确认两融资格与风险警示状态。")
        print()

    if not all_codes:
        print("❌ 今日所有 preset 均无信号")
        return 0

    # 落盘 CSV
    out_dir = Path("short_reversal/results/scan_signals")
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, sig in by_preset.items():
        out_path = out_dir / f"{signal_date}_{name}.csv"
        sig.to_csv(out_path, index=False)
        print(f"  saved: {out_path}")

    print()
    print("⚠️  重要提示:")
    print("  1. 信号在 T 日 close 产生, T+1 open 才会成交; 实际成交价以 T+1 09:30 open 为准")
    print("  2. 策略代码无法判断借券可行性 (券源属于券商风控层), 下单前必须在券商 app 查")
    print("     两融标的的实时券池, 切勿按本表直接打满仓位")
    print("  3. 上述信号是基于历史 close 的条件复现, 不构成投资建议")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

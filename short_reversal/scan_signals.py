"""实时信号扫描：列出 T 日 close 满足 5 条件 → T+1 open 可成交做空的标的。

用法:
    python3 -m short_reversal.scan_signals \\
        --preset v33_mainboard_tp6_sl005_mh5_realistic \\
        --signal-date 2026-09-18 \\
        --entry-date  2026-09-21

参数:
    --preset: PRESETS 里任一 preset 名
    --signal-date: 产生 close 信号的日期 (默认 DuckDB 内最新交易日)
    --entry-date:  T+1 成交的预期日期 (仅展示用,策略不知道也不关心这个日期)
    --db-path:     DuckDB 路径 (默认 hiagent_config.DB_PATH)

实现说明:
    - 拉每只票的全序列到 --signal-date,灌进独立 cerebro 实例
    - 复用 Phase3V3Strategy (与 v3 回测引擎同一份代码,零复刻风险)
    - 跑完后读 strategy.pending_entries → 即「T+1 open 会下成交单」的标的集合
    - 对每只候选拉 09-21 当日的最新价,展示预期 entry price
"""
from __future__ import annotations

import argparse
from pathlib import Path

import backtrader as bt
import duckdb
import pandas as pd

from short_reversal.engine import (
    COMMISSION_RATE,
    INITIAL_CAPITAL,
    MARGIN_RATE,
    STAMP_DUTY_RATE,
)
from short_reversal.feed_bt import AShareData
from short_reversal.presets import get_preset
from short_reversal.replay_strategy_v3 import Phase3V3Strategy
from short_reversal.universe import load_universe_asof

from hiagent_config import DB_PATH as DEFAULT_DB


def _latest_trade_date(db_path: Path) -> str:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute("SELECT MAX(date) FROM v_daily").fetchone()
    finally:
        con.close()
    return str(row[0])


def _load_panel_for_codes(
    db_path: Path, codes: list[str], end_date: str, lookback_days: int = 250
) -> pd.DataFrame:
    """按代码拉面板,留 250 日 lookback 让 MA60/Am60/ratio 都充分 warmup."""
    start = (pd.Timestamp(end_date) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute(
            "SELECT thscode, date, open, high, low, close, amount, volume "
            "FROM v_daily "
            "WHERE date BETWEEN ? AND ? AND thscode = ANY(?) "
            "ORDER BY thscode, date",
            [start, end_date, codes],
        ).fetchdf()
    finally:
        con.close()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df


def _scan_preset(
    preset: dict,
    signal_date: str,
    db_path: Path,
    min_bars: int = 150,
    exclude_st: bool = True,
) -> tuple[list[dict], list[dict]]:
    """跑回测引擎到 signal_date,读出 pending_entries。

    返回 (signals, st_excluded) — 第二个元素是被 ST 过滤掉的票,供报告用。
    min_bars: 至少需要的 bar 数,默认 150(策略指标 NaN gate 兜底)。
    """
    universe = load_universe_asof(preset["universe"], signal_date, db_path)
    panel = _load_panel_for_codes(db_path, universe, signal_date)
    if panel.empty:
        return [], []

    # ST 启发式过滤放在 5 条件命中之后做 (与 fast 版一致),
    # 避免对全 universe 拉名称 (5k+ 次 search 慢到不可接受)。
    st_excluded: list[dict] = []

    results: list[dict] = []
    # 按代码切片,每只票跑一次迷你 cerebro。批量策略在 ~5000 只票上内存吃紧
    # 且 indicator 互相独立,所以单只跑最稳。
    for code in universe:
        sub = panel[panel["thscode"] == code].sort_values("date").reset_index(drop=True)
        if len(sub) < min_bars:
            continue

        cerebro = bt.Cerebro(stdstats=False)
        cerebro.broker.setcash(INITIAL_CAPITAL)
        cerebro.broker.setcommission(commission=0.0)
        holder: dict = {"cash": INITIAL_CAPITAL, "trades": [], "max_dd": 0.0}
        cerebro.adddata(AShareData(dataname=sub, plot=False), name=code)
        cerebro.addstrategy(
            Phase3V3Strategy,
            tp_pct=preset["tp_pct"],
            sl_pct=preset["sl_pct"],
            max_hold=preset["max_hold"],
            position_fraction=1.0,
            pct_chg_low=preset.get("pct_chg_low", 0.02),
            pct_chg_high=preset.get("pct_chg_high", 0.06),
            a_condition=preset.get("a_condition", "default"),
            margin_rate=MARGIN_RATE,
            commission_rate=COMMISSION_RATE,
            stamp_duty_rate=STAMP_DUTY_RATE,
            initial_capital=INITIAL_CAPITAL,
            lot_size=100,
            result_holder=holder,
        )
        try:
            strategies = cerebro.run()
        except Exception as e:
            # 单只票失败不影响其他 — 跳过,日志稍后聚合
            print(f"WARN {code}: cerebro.run failed: {e}")
            continue
        strategy = strategies[0]
        if code in strategy.pending_entries:
            results.append({
                "thscode": code,
                "last_close": float(sub["close"].iloc[-1]),
                "last_date": sub["date"].iloc[-1].strftime("%Y-%m-%d"),
            })

    # ST 启发式过滤 (只对命中票做, 不扫全 universe)
    if exclude_st and results:
        from short_reversal.st_filter import filter_signal_codes_for_st
        results_df = pd.DataFrame(results)
        keep_df, st_excluded = filter_signal_codes_for_st(
            results_df, signal_date
        )
        results = keep_df.to_dict("records")

    return results, st_excluded


def main() -> int:
    ap = argparse.ArgumentParser(description="短反转实时信号扫描")
    ap.add_argument(
        "--preset", action="append", default=None,
        help="preset 名,可重复传(--preset a --preset b);默认 = 两个内置 preset 都跑",
    )
    ap.add_argument("--signal-date", default=None,
                    help="信号日 (T 日 close). 默认 DuckDB 最新交易日")
    ap.add_argument("--entry-date", default=None,
                    help="T+1 开盘成交日 (仅展示用)")
    ap.add_argument("--db-path", default=str(DEFAULT_DB))
    ap.add_argument("--min-bars", type=int, default=150)
    ap.add_argument("--include-st", action="store_true",
                    help="保留 ST/*ST 票 (默认剔除)")
    args = ap.parse_args()

    db_path = Path(args.db_path)
    signal_date = args.signal_date or _latest_trade_date(db_path)
    entry_date = args.entry_date or "T+1"

    presets = args.preset or [
        "v33_mainboard_tp6_sl005_mh5_realistic",
        "v33_mainboard_tp2_sl05_dneg",
    ]

    print(f"=== short_reversal 信号扫描 ===")
    print(f"信号日 (T)    : {signal_date}  (close 时满足 A/B/C/D/E 5 条件)")
    print(f"预计成交 (T+1): {entry_date}  (open 时按信号买入做空)")
    print(f"presets       : {presets}")
    print(f"min_bars      : {args.min_bars}")
    print()

    # 跑每个 preset,记录结果
    by_preset: dict[str, list[dict]] = {}
    st_excluded_global: list[dict] = []
    for preset_name in presets:
        cfg = dict(get_preset(preset_name))
        cfg["_name"] = preset_name
        print(f"[scan] preset={preset_name} "
              f"(tp={cfg['tp_pct']*100:.2f}% sl={cfg['sl_pct']*100:.4f}% "
              f"mh={cfg['max_hold']} pc=[{cfg.get('pct_chg_low', 0.02)*100:.1f}%, "
              f"{cfg.get('pct_chg_high', 0.06)*100:.1f}%]) universe={cfg['universe']}")
        signals, st_excl = _scan_preset(
            cfg, signal_date, db_path,
            min_bars=args.min_bars, exclude_st=not args.include_st,
        )
        signals.sort(key=lambda r: r["last_close"])
        by_preset[preset_name] = signals
        for r in st_excl:
            st_excluded_global.append(r)
        print(f"  → {len(signals)} 个信号"
              + (f" (剔除 {len(st_excl)} 只 ST)" if st_excl else ""))
        print()

    # 输出每个 preset 单独的列表
    for preset_name, signals in by_preset.items():
        cfg = get_preset(preset_name)
        print(f"=== {preset_name} ({len(signals)} 个信号) ===")
        if not signals:
            print("  (空)")
            print()
            continue
        print(f"  {'thscode':<12}{'signal_date':<14}{'last_close':>12}  notes")
        print("  " + "-" * 60)
        for s in signals:
            print(f"  {s['thscode']:<12}{s['last_date']:<14}{s['last_close']:>12.2f}  "
                  f"T+1 open 成交 (需券商券源)")
        print()

    # 跨 preset 的并集与交集
    all_codes = set()
    for signals in by_preset.values():
        all_codes.update(s["thscode"] for s in signals)
    intersect = set.intersection(*[set(s["thscode"] for s in sigs) for sigs in by_preset.values()]) \
        if all(len(sigs) > 0 for sigs in by_preset.values()) else set()

    print(f"=== 跨 preset 对比 ===")
    print(f"  至少一个 preset 触发: {len(all_codes)} 只")
    if len(by_preset) > 1:
        print(f"  全部 preset 同时触发: {len(intersect)} 只")
        if intersect:
            print(f"  重叠标的: {sorted(intersect)}")
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

    print("⚠️  重要提示:")
    print("  1. 信号在 T 日 close 产生, T+1 open 才会成交; 实际成交价以 T+1 09:30 open 为准")
    print("  2. 策略代码无法判断借券可行性 (券源属于券商风控层), 下单前必须在券商 app 查")
    print("     两融标的的实时券池, 切勿按本表直接打满仓位")
    print("  3. 上述信号是基于历史 close 的条件复现, 不构成投资建议")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
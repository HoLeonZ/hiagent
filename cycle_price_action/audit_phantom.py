"""cycle_price_action Layout C 代码级 phantom audit (CLAUDE.md §3).

Layout C 是单价格域 (structurally phantom-free): exit path 走
`extract_execution_bar(LAYOUT_CYCLE_PRICE)`,entry/exit 同源 — 没有
raw/adj split,无 phantom 来源。

由于 cycle_price_action backtest 在真实 panel 上反复触发 fail-fast 数据缺口
(000695.SZ@2025-04-30 / 多次股票数据 NULL),trade-level 审计需要先打通数据
ETL。本次 commit 用代码检查锁定 Layout C 结构性不变量 — 任何 engine 回归
引入 raw/adj split 都会触发 RED。

用法:
    python cycle_price_action/audit_phantom.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def audit_cycle_price_action_invariants() -> dict:
    """锁定 cycle_price_action Layout C 结构性 phantom-free 契约.

    Returns:
        dict with check names → bool (True = pass)
    """
    checks: dict[str, bool] = {}

    # ----- Check 1: backtrader_engine.py 接入 core.dual_price
    engine_text = (ROOT / "cycle_price_action" / "backtrader_engine.py").read_text()
    checks["engine_imports_extract_execution_bar"] = (
        "from core.dual_price import" in engine_text
        and "extract_execution_bar" in engine_text
    )
    checks["engine_uses_LAYOUT_CYCLE_PRICE"] = "LAYOUT_CYCLE_PRICE" in engine_text

    # ----- Check 2: Layout C 是单价格域,无 raw_*/adj_* split
    checks["engine_no_raw_column_access"] = (
        "raw_open" not in engine_text and "adj_open" not in engine_text
    )

    # ----- Check 3: exit path 通过 bar_exec.* (extract_execution_bar 的输出)
    #              而不是 self.datas[0].open[0] 等原始列
    checks["engine_exit_path_uses_bar_exec"] = (
        "bar_exec.open" in engine_text
        and "bar_exec.high" in engine_text
        and "bar_exec.low" in engine_text
        and "bar_exec.close" in engine_text
    )

    # ----- Check 4: portfolio.py try_exit_with_intraday_check 必须保留 SL-first
    portfolio_text = (ROOT / "cycle_price_action" / "portfolio.py").read_text()
    checks["portfolio_has_intraday_sl_first"] = (
        "try_exit_with_intraday_check" in portfolio_text
    )
    # SL-first 顺序必须先 SL 后 TP (CLAUDE.md §4 worst-case)
    sl_first_section = portfolio_text.split("try_exit_with_intraday_check", 1)
    if len(sl_first_section) > 1:
        body = sl_first_section[1].split("def ", 1)[0]
        sl_pos = body.find('open <= sl_p')  # SL @ open (gap-down)
        tp_pos = body.find('open >= tp_p')  # TP @ open (gap-up)
        # 同一函数内,SL gap-down 判断必须在 TP gap-up 判断之前 (CLAUDE.md §4)
        checks["sl_first_in_intraday_check"] = (
            sl_pos > 0 and tp_pos > 0 and sl_pos < tp_pos
        )
    else:
        checks["sl_first_in_intraday_check"] = False

    # ----- Check 5: presets.py 必须声明 price_source intent (Layout C intent
    # 是单价格域,未必显式引用 LAYOUT_CYCLE_PRICE 常量;但必须声明 signal/exec
    # 价格源,证明 Layout 漂移可控)
    presets_text = (ROOT / "cycle_price_action" / "presets.py").read_text()
    sys.path.insert(0, str(ROOT / "cycle_price_action"))
    from cycle_price_action import presets as cpa_presets

    checks["preset_declares_price_source_intent"] = (
        "price_source_for_signal" in presets_text
        and "price_source_for_execution" in presets_text
    )

    # ----- Check 6: 每个 preset 声明 price_source_for_execution="raw_close"
    # cycle_price_action 当前只有 PRESET_V1 (Layout C declared 但未完全 V3a 实现)
    preset_names = [n for n in dir(cpa_presets) if n.startswith("PRESET_")]
    preset_execution_raw = []
    for preset_name in preset_names:
        p = getattr(cpa_presets, preset_name)
        if isinstance(p, dict):
            preset_execution_raw.append(
                p.get("price_source_for_execution") == "raw_close"
            )
    checks["all_presets_execution_raw_close"] = all(preset_execution_raw) and bool(
        preset_execution_raw
    )

    # ----- Check 7: data_feed.py 用 v_daily (单 close),无 raw_*/adj_* 列
    data_feed_text = (ROOT / "cycle_price_action" / "data_feed.py").read_text()
    checks["data_feed_uses_v_daily"] = "v_daily" in data_feed_text
    checks["data_feed_no_raw_adj_split"] = (
        "raw_" not in data_feed_text.replace("raw_close", "")  # 容许 layout 注释提及
        .replace("adj_close", "")
        and "adj_" not in data_feed_text.replace("adj_close", "")
    )

    # ----- Check 8: replay_broker.py fail-fast 数据缺口 (CLAUDE.md §0)
    broker_text = (ROOT / "cycle_price_action" / "replay_broker.py").read_text()
    checks["replay_broker_fail_fast"] = "RuntimeError" in broker_text

    return checks


def main():
    """打印 cycle_price_action Layout C 结构性 phantom-free 审计结果."""
    checks = audit_cycle_price_action_invariants()

    print("cycle_price_action Layout C 结构性 phantom audit (CLAUDE.md §3):")
    print("=" * 70)
    print("注: Layout C 是单价格域, 结构性 phantom-free。")
    print("    trade-level audit 待数据 ETL 修复 (000695.SZ@2025-04-30 等缺口)。")
    print()

    n_pass = 0
    n_fail = 0
    for name, ok in checks.items():
        marker = "✓" if ok else "✗"
        print(f"  [{marker}] {name}")
        n_pass += int(ok)
        n_fail += int(not ok)

    print("=" * 70)
    print(f"总计: {n_pass} pass, {n_fail} fail (out of {len(checks)})")

    if n_fail:
        print()
        print("⚠️  Layout C 结构性契约被破坏 — 引入 raw/adj split 或 SL-first 顺序错位。")
        return 1
    print("✓  Layout C 结构性 phantom-free — 无 phantom 来源。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
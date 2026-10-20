"""cycle_price_action Layout C 代码级 phantom audit (CLAUDE.md §3).

Layout C 是单价格域 (structurally phantom-free): exit path 走
`extract_execution_bar(LAYOUT_CYCLE_PRICE)`,entry/exit 同源 — 没有
raw/adj split,无 phantom 来源。

**2026-10-18 更正(附五十七)**:原文写「trade-level 审计需要先打通数据 ETL
(000695.SZ@2025-04-30 / 多次股票数据 NULL)」—— 该前提**已不成立**,实测:

  * `v_daily` 全表 **10,364,755 行,OHLC 为 NULL 的行 = 0**(不是"多次 NULL");
  * `000695.SZ` 在 2025-04-30 **没有行**(04-29 与 05-06 都有)—— 那是**缺 bar
    = 停牌**,属 §1 的合法市场状态,引擎按设计处理(不成交、持仓顺延),不是数据
    完整性问题;
  * trade-level 审计**已经在跑**:`tests/golden/cycle_v1_baseline.json`(492 笔
    成交的哈希基线,每次套件都重算比对),以及 2026-01-01..2026-09-01 的 5,715 笔
    端到端回测。

故「因数据问题不能做 trade-level 审计」这条理由删除。本工具只做**结构性**检查,
**不是** trade-level 审计的替代品;权威门禁是
`tests/test_cycle_price_action_layout_c_invariants.py`(含本工具没有的行为断言)。

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
    # 附五十七 更正:原判据是「源码里不得出现 'raw_' / 'adj_' 词」(只挖掉
    # raw_close/adj_close 两个词)。那是**词法**判据,同时误伤两件合法且**必需**的
    # 东西:表名 `raw_adjustment_events`(§3 事件源)、以及散文里的 `raw_only`。
    # 更要紧的是它想要的与审计的修复**相反**:审计 P2-10b 恰恰要求 feed
    # LEFT JOIN `v_daily_hfq`,把 `adj_close` 交给信号层(§3「指标必须用复权价」),
    # 而这条判据会把那个修复判成 Layout C 违约。故它长期是 ✗,只是**没人跑这个
    # 工具**所以没人看见。
    # 真实属性:**执行域**不得出现 raw_*/adj_* 的价格列;信号域用 adj_close
    # 是允许且必需的。故改为按**列名**精确判定。
    _FORBIDDEN_EXEC_COLUMNS = (
        "raw_open", "raw_high", "raw_low", "raw_close", "raw_prev_close",
        "adj_open", "adj_high", "adj_low", "adj_prev_close",
    )
    checks["data_feed_reads_no_raw_or_adj_execution_columns"] = not any(
        c in data_feed_text for c in _FORBIDDEN_EXEC_COLUMNS
    )

    # ----- Check 8 (§0 数据缺口 fail-fast)—— 附五十七 更正:
    # 原实现在 `replay_broker.py` 里找词 "RuntimeError",而该文件**没有**
    # `raise RuntimeError`(仅有的两处都在**注释**里)⇒ 盯错文件 + 判词不判行为,
    # 恒绿。真正的 fail-fast 在 `data_feed.ReplayDataProvider.open_price`:
    # 库中**完全无 bar** 的标的抛错,而已知标的当日缺 bar(停牌)返回 None ——
    # 两者由 `has_any_bar` 区分。行为证据在同名测试文件的
    # `test_data_gap_fail_fast_versus_suspension_is_distinguished`。
    # 判据必须**精确到函数体**:第一次写的是 `"raise RuntimeError" in data_feed_text`,
    # 而同一文件里 `next_trading_date` 也有一处 `raise RuntimeError` —— 于是把
    # open_price 的 fail-fast 整个删掉,这条检查**仍然为真**(实测)。
    # 与上面 sl_first_in_intraday_check 同法:切出函数体再判。
    _op_body = data_feed_text.split("def open_price", 1)
    _op_body = _op_body[1].split("\n    def ", 1)[0] if len(_op_body) > 1 else ""
    checks["data_provider_fail_fast_on_unknown_symbol"] = (
        "raise RuntimeError" in _op_body and "has_any_bar" in _op_body
    )

    return checks


def main():
    """打印 cycle_price_action Layout C 结构性 phantom-free 审计结果."""
    checks = audit_cycle_price_action_invariants()

    print("cycle_price_action Layout C 结构性 phantom audit (CLAUDE.md §3):")
    print("=" * 70)
    print("注: Layout C 的**执行**域单一(结构上 phantom-free);信号域用 adj_close")
    print("    是 §3 要求的,不算 Layout 漂移(见 data_feed_reads_no_raw_or_adj_...)。")
    print("    本工具只做结构性检查;trade-level 由 tests/golden 基线与端到端回测覆盖。")
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
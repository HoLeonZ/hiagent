"""§6 对拍:快速扫描器与**真引擎路径**必须给同一个信号集。

## 为什么要有这一条

`附三十一` 把快速扫描器的"与策略 100% 等价"改成 fail-fast(不等价即拒答),并在
`附三十八` 让它**读 preset 声明的参数**。但"读对了参数"只解决了**一半**:
剩下那一半是"两处实现的**公式**是否真的一致"(am60 是不是 60 日均量、
below_ma60_ratio_60 是不是 60 日窗、up_streak 的计数口径、MACD 与 backtrader 的
`macd/signal` 是否同一个量)。这些**假设**从扫描器诞生起就存在,却从未被对拍过。

对拍的对象是 `scan_signals._scan_preset` —— 它**逐股构造真实
`Phase3V3Strategy` 跑 cerebro**,即回测引擎本身,所以它就是"真值路径"。

## 顺带发现的真缺陷(见附三十八)

写这条对拍时,第一次调用真值路径就**崩了**:

    §2: nav_gate_ratio 必须由 Control Plane 从 preset 声明解析后注入

`scan_signals` 手抄了一个**参数子集**构造策略(12 项),既漏了 `nav_gate_ratio`
(⇒ 直接崩),又漏了 F/G/H/I/J/K 与 max_positions / signal_price_domain 等开关
(⇒ 即便补上崩溃项,信号集也会比回测**宽**)。**实时扫描工具给的名单是要下单用的。**
修法是把策略构造抽成 `engine.strategy_kwargs` 单源,两处共用。

所以本文件同时是**实时扫描路径的回归守卫**:上面那个崩溃,本文件第一次调用就会红。
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: 2026-09-18:六个候选 preset 在快扫描器上都有命中(3~32 只),对拍不会空转。
_DATE = "2026-09-18"
_PRESETS = [
    "v35_agg_pctchg_04_09",   # d_mode=strict(旧硬编码口径)
    "v36_d_converge",         # d_mode=converge_strict
    "v44_ratio02_buf07",      # below_ratio_60 + close_ma60_buffer
    "v71_liqwide",            # liq_low/high 放宽
    "v76_cascade",            # a_condition=cascade_price
    "v77_b_narrow",           # up_streak 收窄
]
_SAMPLE_SIZE = 300  # 真值路径逐股跑 cerebro;300 只约 10s


def _db() -> Path:
    from hiagent_config import get_db_path

    return Path(get_db_path())


_NEEDS_DB = pytest.mark.skipif(
    not _db().exists() or _db().stat().st_size == 0,
    reason="local DuckDB 不可用 — 按 CLAUDE.md §6 skip 而非 error",
)


def _fast_hits(preset: str, panel) -> list[str]:
    """快扫描器在**该 preset 的 universe** 上的命中。

    ⚠️ 必须像 `scan_signals_fast.main()` 那样先按 preset 的 universe 过滤面板 ——
    否则会把科创板/创业板/北交所塞进结果(本文件第一版就踩了这个:对拍报出
    301187.SZ / 688816.SH / 920036.BJ 三只非主板票,那是**测试**的错,不是扫描器的)。
    """
    import short_reversal.scan_signals_fast as fast
    from short_reversal.presets import get_preset
    from short_reversal.universe import load_universe_asof

    cfg = get_preset(preset)
    universe = set(load_universe_asof(cfg["universe"], _DATE, _db()))
    preset_panel = panel[panel["thscode"].isin(universe)].reset_index(drop=True)
    df, _ = fast._scan_preset(preset, _DATE, preset_panel, exclude_st=False)
    return sorted(df["thscode"].tolist())


def _slow_hits(preset: str, subset: list[str]) -> list[str]:
    import short_reversal.scan_signals as slow
    from short_reversal.presets import get_preset

    original = slow.load_universe_asof
    slow.load_universe_asof = lambda mode, asof, p: subset  # noqa: ARG005
    try:
        cfg = dict(get_preset(preset))
        cfg["_name"] = preset
        sig, _ = slow._scan_preset(cfg, _DATE, _db(), min_bars=150, exclude_st=False)
    finally:
        slow.load_universe_asof = original
    return sorted(r["thscode"] for r in sig)


@_NEEDS_DB
@pytest.mark.parametrize("preset", _PRESETS)
def test_fast_scanner_matches_the_engine_path(preset: str) -> None:
    """同一个 preset、同一个信号日 ⇒ 两条路径的信号集必须**逐只相同**。

    子集 = 快扫描器的命中 ∪ 前 300 只(定序取样)—— 后者保证"快扫描器漏掉、
    真值路径选中"这个方向也在射程内(只比命中会是自证)。
    """
    from short_reversal._panel_loader import load_panel_for_signal

    panel = load_panel_for_signal(_db(), _DATE)
    fast_hits = _fast_hits(preset, panel)

    sample = sorted(panel["thscode"].unique())[:_SAMPLE_SIZE]
    subset = sorted(set(fast_hits) | set(sample))
    slow_hits = _slow_hits(preset, subset)

    assert fast_hits == slow_hits, (
        f"§6: 快速扫描器与真引擎路径在 {preset} @ {_DATE} 上不一致\n"
        f"  仅快扫描器有: {sorted(set(fast_hits) - set(slow_hits))[:8]}\n"
        f"  仅真引擎有  : {sorted(set(slow_hits) - set(fast_hits))[:8]}\n"
        "两处实现给不同结论 ⇒ 快速扫描器不得对该 preset 放行"
    )


@_NEEDS_DB
def test_the_comparison_is_not_vacuous() -> None:
    """对拍必须**有东西可比** —— 否则它只是两条空集相等的绿。

    这条独立断言"至少一个候选 preset 在该日期有命中",防止将来数据/日期变化后
    整个文件退化成空转(本仓库已有过"守卫悄悄失效"的先例)。
    """
    from short_reversal._panel_loader import load_panel_for_signal

    panel = load_panel_for_signal(_db(), _DATE)
    total = sum(len(_fast_hits(p, panel)) for p in _PRESETS)
    assert total > 0, (
        f"{_DATE} 上六个候选 preset 全无命中 —— 对拍退化成空转,请换日期或换 preset"
    )


def test_strategy_is_constructed_through_the_shared_helper() -> None:
    """§6 单源:两个构造点都必须走 `engine.strategy_kwargs`。

    这条守的是本轮修的缺陷形态 —— `scan_signals` 曾**手抄参数子集**,漏掉必填项
    导致运行期崩溃、漏掉开关导致信号集偏宽。
    """
    engine_src = (REPO_ROOT / "short_reversal" / "engine.py").read_text(encoding="utf-8")
    scan_src = (REPO_ROOT / "short_reversal" / "scan_signals.py").read_text(encoding="utf-8")

    assert "def strategy_kwargs(" in engine_src, "单源构造函数不见了"
    assert "**strategy_kwargs(" in engine_src, "回测入口没有走单源构造"
    assert "**strategy_kwargs(" in scan_src, "扫描工具没有走单源构造"
    # 反例:再出现手抄的 tp_pct=/sl_pct= 关键字构造,就是又开了第二处
    hand_written = [
        ln.strip() for ln in scan_src.splitlines()
        if ("tp_pct=" in ln or "sl_pct=" in ln) and "**" not in ln and "def " not in ln
    ]
    assert not hand_written, (
        "扫描工具又手抄策略参数了 —— 必须走 engine.strategy_kwargs:\n  "
        + "\n  ".join(hand_written)
    )

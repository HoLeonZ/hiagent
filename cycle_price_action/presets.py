"""Default parameter presets for cycle_price_action v1.

Compliance declaration (CLAUDE.md audit 2026-09-22):
  V5 (R8, 2026-09-21, CLAUDE.md §4) — Volume Participation Limit:
    Portfolio.try_enter accepts bar_volume; cap shares at Bar_Volume × 0.10.
    backtrader_engine.py:107-113 passes bar["volume"]. 单笔最大成交量 = Bar_Vol × 0.10。
  V6'' (2026-09-22, CLAUDE.md §4) — Intraday SL-first tiebreak:
    Portfolio.try_exit_with_intraday_check 落地 SL-first 优先级 (gap-down SL,
    gap-up TP, intraday SL-first, TP fallback, time fallback). 7 个 regression
    tests 覆盖全部 5 个分支 + P3 same-day guard。
    backtrader_engine.py:66-89 在持仓每个 bar 调用 intraday check, exit 触发
    reason ∈ {"SL", "TP", "time"}。max_hold time exit 保留为 P7 fallback。
"""
from __future__ import annotations

from core.preset_contract import PresetDeclarationMissing

# §4 (audit P1-B2, 2026-10-15): 滑点标定值必须由 preset 显式声明;缺声明
# fail-fast(core.dual_price.resolve_atr_slip_scale)。
# SLIP_NONE_ACKNOWLEDGED=0.0 是「已知 §4 缺口」的显式确认值。
SLIP_NONE_ACKNOWLEDGED = 0.0

#: `fuse_scores` 的三个维度名,与 resolve_score_weights 的返回顺序一一对应。
SCORE_WEIGHT_KEYS = ("weight_kline", "weight_cycle", "weight_calendar")


def resolve_score_weights(preset: dict, preset_name: str) -> tuple[float, float, float]:
    """§0: 把 preset 声明的三个维度权重映射成 `fuse_scores` 的 `weights`。

    审计 (2026-10-15) 把这里点名为**装饰性声明**:`signals.fuse_scores` 曾把
    `(1.0, 0.7, 0.5)` 写成**默认参数**,与 PRESET_V1 声明值恰好相同 —— 于是
    预设与代码看起来一致,而**改预设什么都不会发生**(缺口靠沉默存在)。
    现在权重只能来自声明,融合分数的三个系数由这一个函数单点映射。
    """
    missing = [k for k in SCORE_WEIGHT_KEYS if k not in preset]
    if missing:
        raise PresetDeclarationMissing(
            f"§0: preset {preset_name!r} 未声明评分权重 {missing} —— "
            "融合分数必须由声明驱动,不得退回硬编码默认值。"
        )
    return tuple(float(preset[k]) for k in SCORE_WEIGHT_KEYS)  # type: ignore[return-value]

PRESET_V1 = dict(
    atr_slip_scale=SLIP_NONE_ACKNOWLEDGED,
    threshold=2.0,
    min_dim=1.0,
    max_hold=5,
    atr_period=14,
    atr_sl_mult=1.5,
    # V3a (2026-09-22, CLAUDE.md §3): PIT universe declaration.
    # data_feed.py:140-225 load_universe_data hardcodes P8 + main-board
    # + liquidity filter. Declared here for compliance consistency with
    # chase_up / short_reversal / uptrend_pullback presets.
    universe="mainboard_only",
    tp_pct=0.06,
    # V6'' (2026-09-22, CLAUDE.md §4): SL fraction for intraday tiebreak.
    # Used by backtrader_engine to compute sl_p = entry × (1 - sl_pct)。
    # 0.05 = 5% stop, conservative for cycle strategy (vs chase_up 1.5-2.5%)。
    sl_pct=0.05,
    # V5 (R8, 2026-09-21, CLAUDE.md §4): Volume Participation Limit declaration。
    max_volume_participation=0.10,
    # V8 (2026-09-22, CLAUDE.md §4): SL-first tiebreak intraday 声明。
    # cycle_price_action/portfolio.py:209-216 已落地 (open<=sl_p 优先于 open>=tp_p,
    # lo<=sl_p 优先于 h>=tp_p)。
    intraday_tiebreak="sl_first",
    # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System 声明。
    # 当前 cycle 仍读 v_daily (单 close) 作为信号+执行共用价。
    # 完整 V3a 落地需: data_feed.py 改读 v_daily_dual (含 adj_*/raw_*),
    # k_line / phase / cycle score 用 adj_close, SL/TP+exit 用 raw_close。
    price_source_for_signal="adj_close",
    price_source_for_execution="raw_close",
    # V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor 声明。
    # cycle 单一 preset, 无 sweep; n_comparisons=1 (DSR→PSR)。
    # walkforward 输出走 dna_stats.walkforward_report.format_walkforward_stats
    # 自动套 DSR + Bonferroni 校正。
    n_comparisons=1,
    # §2 (2026-09-22, CLAUDE.md All-In Sizing Policy):
    # Engine `portfolio.py:65` hardcodes MAX_POSITION_PCT=1.0; 显式声明如下。
    position_sizing="all_in",
    max_positions=1,
    position_fraction=1.0,
    MAX_POSITION_PCT=1.0,
    weight_kline=1.0,
    weight_cycle=0.7,
    weight_calendar=0.5,
    periods=(3, 5, 8, 13, 21),
)

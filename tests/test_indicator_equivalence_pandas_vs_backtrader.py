"""§6 逐值对拍:指标的 pandas 对偶 vs 引擎的 backtrader 原件。

## 为什么需要它

快速扫描器(`scan_signals_fast`)必须用 pandas 重算 5 条件所需的指标,于是**同一批
定义在仓库里存在两份**(`indicators_bt.py` 的 `bt.Indicator` 子类,与扫描器里的
pandas 版本)。"两份等价"从扫描器诞生起就是**假设**,从未被验证过 —— 而它决定
实时扫描给出的名单是否与回测一致。

本文件把两份实现**在同一批代码、同一天**上逐值比较:

    engine 侧:逐股构造真实 `Phase3V3Strategy` 跑 cerebro,读其 `self.indi[code][k][0]`
               (最后一根 bar 的值 ⇒ 信号日 T 的值)
    pandas 侧:`indicators_bt.*_pandas()` 在同一份面板上算到同一行

## 覆盖

ma5/ma10/ma20/ma60(SMA)、pct_chg、am60、up_streak、below_ma60_ratio_60、
ma20_slope_5d、return_1m/3m/6m、amount_ratio、rsi。

`rsi` 需要 `require_rsi_oversold=True` 才会被引擎构建(见 replay_strategy_v3 的
Round 17 注释:backtrader 的 RSI 在完全无波动时会内部除零),故用 `v53_rsi_30` 跑。

## 校准口径

浮点路径不同(backtrader 增量式 vs pandas rolling),故用相对容差比较;
**容差不掩盖量级差** —— 若某指标的定义抄错(例如把 Wilder 平滑写成简单均值),
差异会是百分之几而不是 1e-6。预热段(NaN 区间)两边的 NaN 语义可能不同:
NaN ↔ NaN 视为一致,NaN ↔ 数值视为**不一致**并如实报出。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_DATE = "2026-09-18"
#: 用启用 I 条件的 preset —— 引擎只在 `require_rsi_oversold=True` 时构建 RSI。
_PRESET = "v53_rsi_30"
_N_CODES = 25
_RTOL = 1e-6
#: 全键统一容差。**不需要**逐指标放宽了(曾一度给 RSI 放宽到 1e-5,那是两侧吃了
#: 不同长度历史造成的假象;改用同一 loader 后 RSI 与其余指标一样精确到 1e-14)。

#: 引擎 `self.indi[code]` 的键 → 指标名(单线指标用 `[0]` 取值)
_SCALAR_KEYS = (
    "ma5", "ma10", "ma20", "ma60", "pct_chg", "am60", "up_streak",
    "below_ma60_ratio_60", "ma20_slope_5d", "return_1m", "return_3m",
    "return_6m", "amount_ratio", "rsi",
)


def _db() -> Path:
    from hiagent_config import get_db_path

    return Path(get_db_path())


_NEEDS_DB = pytest.mark.skipif(
    not _db().exists() or _db().stat().st_size == 0,
    reason="local DuckDB 不可用 — 按 CLAUDE.md §6 skip 而非 error",
)


def _codes() -> list[str]:
    from short_reversal._panel_loader import load_panel_for_signal

    panel = load_panel_for_signal(_db(), _DATE)
    return sorted(panel["thscode"].unique())[:_N_CODES]


def _panel_for(codes: list[str]) -> pd.DataFrame:
    """**引擎自己那个 loader** 取面板 —— 两侧必须吃同一份历史。

    起因(2026-10-17):先前 pandas 侧用 `load_panel_for_signal`,而引擎侧用
    `scan_signals._load_panel_for_codes`,两者给的**历史长度不同** ⇒ 只有
    **递归型**指标(RSI,Wilder 平滑依赖整条序列)出现 ~1e-6 的差,而窗口型指标
    (SMA/rolling)完全一致 —— 正是这个"只有递归型有差"的形态指明了成因是**输入不同**,
    而不是公式不同(隔离验证:同一序列上两者差 0 ~ 1.4e-14)。
    """
    from short_reversal import scan_signals as slow

    return slow._load_panel_for_codes(_db(), codes, _DATE)


def _engine_values(codes: list[str]) -> dict[str, dict[str, float]]:
    """跑真引擎到 `_DATE`,读每股最后一根 bar 的指标值。"""
    from short_reversal import scan_signals as slow
    from short_reversal.presets import get_preset
    from short_reversal.replay_strategy_v3 import Phase3V3Strategy

    captured: list = []
    real_init = Phase3V3Strategy.__init__

    def _spy(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        captured.append(self)

    Phase3V3Strategy.__init__ = _spy
    old_universe = slow.load_universe_asof
    slow.load_universe_asof = lambda mode, asof, p: codes  # noqa: ARG005
    try:
        cfg = dict(get_preset(_PRESET))
        cfg["_name"] = _PRESET
        slow._scan_preset(cfg, _DATE, _db(), min_bars=150, exclude_st=False)
    finally:
        Phase3V3Strategy.__init__ = real_init
        slow.load_universe_asof = old_universe

    out: dict[str, dict[str, float]] = {}
    for strat in captured:
        for code, indi in strat.indi.items():
            vals = {}
            for key in _SCALAR_KEYS:
                obj = indi.get(key)
                if obj is None:
                    continue
                try:
                    vals[key] = float(obj[0])
                except (TypeError, IndexError, ValueError):
                    continue
            out[code] = vals
    return out


def _pandas_values(panel: pd.DataFrame) -> dict[str, dict[str, float]]:
    """同一份面板上算 pandas 对偶,取 `_DATE` 那一行。"""
    from short_reversal.indicators_bt import (
        am60_pandas,
        amount_ratio_pandas,
        below_ma60_ratio_pandas,
        ma20_slope_pandas,
        pct_chg_pandas,
        return_n_pandas,
        rsi_pandas,
        sma_pandas,
        up_streak_pandas,
    )

    out: dict[str, dict[str, float]] = {}
    target = pd.Timestamp(_DATE)
    for code, sub in panel.groupby("thscode", sort=False):
        g = sub.sort_values("date")
        row = g[g["date"] == target]
        if row.empty:
            continue
        # §3 (2026-10-17): 信号域 = **复权价**(与引擎 signal_price_domain="adj" 一致)。
        # 此前这里取 `close`(raw),于是对拍只在**错误的口径**上验证了公式的等价性 ——
        # 它没能发现"扫描器整体算在 raw 上而引擎算在 adj 上"这个 94% 覆盖的域错误。
        close = (
            g["adj_close"].fillna(g["close"]).reset_index(drop=True)
            if "adj_close" in g.columns
            else g["close"].reset_index(drop=True)
        )
        ma20 = sma_pandas(close, 20)
        vals = {
            "ma5": float(sma_pandas(close, 5).iloc[-1]),
            "ma10": float(sma_pandas(close, 10).iloc[-1]),
            "ma20": float(ma20.iloc[-1]),
            "ma60": float(sma_pandas(close, 60).iloc[-1]),
            "pct_chg": float(pct_chg_pandas(close).iloc[-1]),
            "am60": float(am60_pandas(g["amount"].reset_index(drop=True), 60).iloc[-1]),
            "up_streak": float(up_streak_pandas(close).iloc[-1]),
            "below_ma60_ratio_60": float(
                below_ma60_ratio_pandas(close, sma_pandas(close, 60), 60).iloc[-1]
            ),
            "ma20_slope_5d": float(ma20_slope_pandas(ma20, 5).iloc[-1]),
            "return_1m": float(return_n_pandas(close, 21).iloc[-1]),
            "return_3m": float(return_n_pandas(close, 63).iloc[-1]),
            "return_6m": float(return_n_pandas(close, 126).iloc[-1]),
            "amount_ratio": float(
                amount_ratio_pandas(g["amount"].reset_index(drop=True), 5, 20).iloc[-1]
            ),
            "rsi": float(rsi_pandas(close, 14).iloc[-1]),
        }
        out[str(code)] = vals
    return out


@_NEEDS_DB
def test_pandas_indicators_match_the_engine_on_real_data() -> None:
    """同一批代码、同一天:每个指标的 pandas 对偶必须与引擎的 backtrader 值一致。

    不一致 ⇒ 扫描器与回测的条件在不同数据上成立,**实时扫描给出的名单不可信**
    (这正是附三十八 拒绝"凭感觉实现 F–K"的理由:要么有对拍,要么别声称等价)。
    """
    codes = _codes()
    panel = _panel_for(codes)

    engine = _engine_values(codes)
    pandas_vals = _pandas_values(panel)

    assert engine, "引擎侧一个指标都没取到 —— 对拍前提被破坏"
    assert pandas_vals, "pandas 侧一个指标都没取到"

    mismatches: list[str] = []
    compared = 0
    for code in sorted(set(engine) & set(pandas_vals)):
        for key in _SCALAR_KEYS:
            e = engine[code].get(key)
            p = pandas_vals[code].get(key)
            if e is None or p is None:
                continue
            both_nan = np.isnan(e) and np.isnan(p)
            if both_nan:
                continue
            if np.isnan(e) != np.isnan(p):
                mismatches.append(f"{code} {key}: engine={e!r} pandas={p!r}(NaN 语义不一致)")
                continue
            compared += 1
            if not np.isclose(e, p, rtol=_RTOL, atol=1e-9):
                mismatches.append(
                    f"{code} {key}: engine={e:.10g} pandas={p:.10g} "
                    f"(相对差 {abs(e - p) / max(abs(e), 1e-12):.2e})"
                )

    assert compared > 50, f"可比样本太少({compared})—— 对拍退化了"
    assert not mismatches, (
        "§6:pandas 对偶与 backtrader 原件不一致 —— 扫描器不得声称与引擎等价\n  "
        + "\n  ".join(mismatches[:20])
        + (f"\n  …共 {len(mismatches)} 处" if len(mismatches) > 20 else "")
    )

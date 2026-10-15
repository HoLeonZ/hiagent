"""§0/§7 守卫：运行产物必须是**严格合法**的 JSON（禁止 `NaN` / `Infinity`）。

`json.dumps(float("inf"))` 在 Python 里会写出 `Infinity`,`float("nan")` 写出 `NaN` ——
**两者都不是 RFC 8259 的合法值**。Python 自己的 `json.loads` 默认宽松地接受它们,
所以自家 round-trip 读得回来,**缺陷因此长期隐形**;而 JS 的 `JSON.parse`、Go、Rust、
`jq` 等一律拒绝 —— 也就是任何非 Python 的消费者都读不了这份产物。

实测(修复前):一个**全胜窗口**(无亏损笔数)下 `profit_factor = float("inf")`
→ `results/backtest.json` 整个文件是非法 JSON。

本文件钉三件事:
  1. 无亏损笔数时 `profit_factor` 是 `None`(与 `max_dd=None`/`cagr=None` 同口径,
     而不是 `inf`);
  2. 真实算出的指标字典能被 **`allow_nan=False`** 严格序列化,且不含任何非有限浮点;
  3. 四个引擎的产物写出点都带 `allow_nan=False` —— 将来再引入非有限值会在**写出时**
     失败,而不是悄悄产出一份读不了的产物(§0 fail-fast)。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

ENGINE_MAINS = {
    "chase_up": REPO_ROOT / "chase_up" / "main.py",
    "uptrend_pullback": REPO_ROOT / "uptrend_pullback" / "main.py",
    "short_reversal": REPO_ROOT / "short_reversal" / "main.py",
    "cycle_price_action": REPO_ROOT / "cycle_price_action" / "main.py",
}


def _equity(n: int = 30) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=n, freq="B"),
        "equity": np.linspace(1_000_000.0, 1_100_000.0, n),
        "holdings": np.full(n, 500_000.0),
    })


def _trades(pnl: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "net_pnl": pnl,
        "net_return": [p / 1_000_000.0 for p in pnl],
        "hold_days": [5] * len(pnl),
        "exit_reason": ["TP"] * len(pnl),
    })


def _assert_json_strict(payload: dict) -> None:
    """严格序列化必须成功 —— 这是"任何 JSON 解析器都读得动"的可执行定义。"""
    try:
        text = json.dumps(payload, allow_nan=False)
    except ValueError as exc:  # pragma: no cover - 失败路径
        pytest.fail(f"§0/§7 VIOLATION: 指标产物不是合法 JSON —— {exc}")
    # 再走一遍严格解析(拒绝 Infinity/NaN 常量)
    json.loads(text, parse_constant=lambda c: pytest.fail(
        f"§0/§7 VIOLATION: 产物含非 RFC 8259 常量 {c!r}"
    ))


def _assert_all_finite(payload: dict) -> None:
    bad = {k: v for k, v in payload.items()
           if isinstance(v, float) and not math.isfinite(v)}
    assert not bad, f"§0/§7 VIOLATION: 指标含非有限浮点 {bad}"


@pytest.mark.parametrize("module_path,fn_name", [
    ("chase_up.backtest", "compute_metrics"),
    ("uptrend_pullback.backtest", "compute_metrics"),
])
def test_no_loss_window_metrics_are_strictly_serializable(
    module_path: str, fn_name: str,
) -> None:
    """全胜窗口(无亏损笔数)是 `profit_factor` 分母为 0 的真实场景。"""
    import importlib

    compute_metrics = getattr(importlib.import_module(module_path), fn_name)
    m = compute_metrics(_trades([12_000.0, 8_000.0]), _equity())

    assert m["profit_factor"] is None, (
        "无亏损笔数时 profit_factor 无定义 → 必须是 None;"
        "`float('inf')` 会让整份产物变成非法 JSON。"
    )
    _assert_all_finite(m)
    _assert_json_strict(m)


@pytest.mark.parametrize("module_path,fn_name", [
    ("chase_up.backtest", "compute_metrics"),
    ("uptrend_pullback.backtest", "compute_metrics"),
])
def test_normal_window_metrics_are_strictly_serializable(
    module_path: str, fn_name: str,
) -> None:
    """有盈有亏的常规窗口 —— 顺带确认 `allow_nan=False` 不会误伤正常产物。"""
    import importlib

    compute_metrics = getattr(importlib.import_module(module_path), fn_name)
    m = compute_metrics(_trades([12_000.0, -3_000.0, 8_000.0]), _equity())

    assert isinstance(m["profit_factor"], float) and math.isfinite(m["profit_factor"])
    _assert_all_finite(m)
    _assert_json_strict(m)


@pytest.mark.parametrize("engine,path", sorted(ENGINE_MAINS.items()))
def test_engine_artifact_writers_forbid_non_finite(engine: str, path: Path) -> None:
    """§0 fail-fast:产物写出点必须禁掉非有限值。

    否则"引入一个 inf"的代价是**产出一份读不了的产物**(而且要等到非 Python 的
    消费者来读时才发现),而不是在写出那一刻失败。
    """
    src = path.read_text(encoding="utf-8")
    dumps_lines = [ln for ln in src.splitlines() if "json.dumps(" in ln]
    assert dumps_lines, f"{engine}: 预期 main.py 里有 json.dumps 写出点"
    offenders = [ln.strip() for ln in dumps_lines if "allow_nan=False" not in ln]
    assert not offenders, (
        f"§0/§7 VIOLATION: {engine} 的产物写出点未禁非有限值:\n  "
        + "\n  ".join(offenders)
    )

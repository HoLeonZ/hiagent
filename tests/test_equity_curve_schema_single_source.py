"""§6/§3: `EQUITY_CURVE_COLS` / `CASH_WALK_COLS` 必须**只有单一来源** (`core.trade_schema`)。

## 为什么需要这条 (2026-10-19, Iteration 119)
这两个元组此前在**三个引擎**的 `main.py` 里各有一份拷贝
(`short_reversal` / `uptrend_pullback` / `cycle_price_action`)。
实测确认**三份逐字节相同**, 所以上收**零结果漂移** —— 本测试随之钉住它。

**为什么"能跑就别动"在这里不成立**: 本循环已证 `core/` **有** `trade_schema.py`
(为 trades.csv 而设) 却**没有指标层**, 而那正是四引擎六处定义分岔的成因
(见 `docs/strategy_mining_log.md` §13.12/§13.13)。
**同一个形状 —— 同名 / 多份拷贝 / 无单一来源 —— 出现在 equity_curve 上时,
下一次分岔只差一次编辑, 而没有任何东西会拦住它。**

⇒ **判据不是"现在对不对", 而是"下一次会不会悄悄不对"。**

## 与"不擅自改结果"的界线 (本仓库反复出现的同一条线)
* 上收**已经相同**的东西 ⇒ **零漂移** ⇒ 直接做 (本文件);
* 上收**已经不同**的东西 (如 `cagr`/`sharpe`/`max_dd`/`win_rate`) ⇒ **结果变更** ⇒ 只登记不做。
  见 §13.12(e) 与 §13.13(f)。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
ENGINE_MAINS = (
    "short_reversal/main.py",
    "uptrend_pullback/main.py",
    "cycle_price_action/main.py",
)


def test_canonical_schema_module_exports_both_tuples() -> None:
    from core.trade_schema import CASH_WALK_COLS, EQUITY_CURVE_COLS

    assert EQUITY_CURVE_COLS == ("date", "cash", "position_value", "total_equity", "drawdown")
    assert CASH_WALK_COLS == (
        "date",
        "free_cash",
        "locked_margin",
        "settling_funds",
        "nav",
        "total_equity",
    )


@pytest.mark.parametrize("rel", ENGINE_MAINS)
def test_engine_main_does_not_redefine_the_canonical_tuples(rel: str) -> None:
    """引擎 main 里**不得**再出现 `XXX_COLS = (...)` 式的本地定义。

    结构性断言 (不需要 DB): 一旦有人把某个元组**抄回来改一列**, 本测试立刻红。
    """
    src = (ROOT / rel).read_text(encoding="utf-8")
    for name in ("EQUITY_CURVE_COLS", "CASH_WALK_COLS"):
        assert not re.search(rf"^\s*{name}\s*=\s*\(", src, re.M), (
            f"{rel} 里又出现了 `{name} = (...)` 的本地定义 —— "
            f"它必须 `from core.trade_schema import {name}` (单一来源)。"
            f"若这次改动是**有意的口径变更**, 那属**结果变更**, 需按 §13.12(e) 单独决策, "
            f"不是在这里抄一份新的。"
        )


@pytest.mark.parametrize("rel", ENGINE_MAINS)
def test_engine_main_imports_them_from_core(rel: str) -> None:
    """正面的那一半: 必须**确实**从 `core.trade_schema` 导入 (不能只是删掉了)。"""
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert re.search(r"from core\.trade_schema import .*EQUITY_CURVE_COLS", src), (
        f"{rel} 没有从 core.trade_schema 导入 EQUITY_CURVE_COLS"
    )
    assert re.search(r"from core\.trade_schema import .*CASH_WALK_COLS", src), (
        f"{rel} 没有从 core.trade_schema 导入 CASH_WALK_COLS"
    )

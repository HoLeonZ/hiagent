"""§4: `cycle_price_action` 的执行滑点**在架构上不可能生效** (§13.98, 2026-10-19)。

## 这一族与另三族**不同**: 另三族是"接线断了", 这一族是**接上去也没用**
本族有**两套并行的成本模型**:
| 模型 | 在哪 | 进不进现金 | 含滑点吗 |
|---|---|---|---|
| `Portfolio._buy_cost` / `_sell_proceeds` | `portfolio.py` | ✅ **是** | ⛔ 否 (存了 `self.atr_slip_scale`, **从不读**) |
| `ReplayBroker._fee` | `replay_broker.py` | ⛔ **否** (`TradeFill.fee` **零消费者**) | ✅ 是 |

**实测 (mutation test)**: `atr_slip_scale` 取 0 / 1 / **50** 三次回测, `total_pnl`
**逐位相同** (`-14367158.031782512`)。⇒ 无论系数多大都不改变任何数字。

**处置**: §0 明令 "Do not silently bypass" ⇒ 在策略构造时**拒绝** `atr_slip_scale > 0`
(与 §13 的 `COALESCE(...,1)` 同一精神: 拿不到正确模型时**拒绝**, 而不是返回一个
看起来合规的零)。

## 本文件的两条判据
1. **自失效守卫**: `TradeFill.fee` 目前**零消费者**。若哪天有人让成本模型真正接通了,
   这条会**红**, 要求: 删掉 fail-fast + 把滑点接进 `Portfolio` 的活跃成本模型。
   > 这是本册最有用的一种守卫形态 —— **它钉住的是"当前的权宜处置何时该被撤掉"**。
2. **fail-fast 在**: 构造时拒绝, 且拒绝理由是那两套模型, 不是一句泛泛的"未实现"。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG = REPO_ROOT / "cycle_price_action"
ENGINE = PKG / "backtrader_engine.py"


def _fee_readers() -> list[tuple[str, int]]:
    """在 `cycle_price_action/` 里找出**读** `TradeFill.fee` 的位置。

    判据用 AST 的 `Attribute` 节点, 名字为 `fee` —— 即 `x.fee` / `fill.fee` 形态。
    (`replay_broker.py` 自己**写** `fee=` 关键字参数与 dataclass 字段声明, 那些是
     `keyword` / `AnnAssign`, 不是属性读取 ⇒ 天然不入选。)
    """
    hits: list[tuple[str, int]] = []
    for p in sorted(PKG.rglob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr == "fee":
                hits.append((p.name, n.lineno))
    return hits


def test_the_broker_fee_model_is_still_discarded() -> None:
    """**自失效**: 一旦 `TradeFill.fee` 有了消费者, 本守卫变红。

    变红说明成本模型被接通了 ⇒ 那时**必须**: ① 删掉 `__init__` 里的 fail-fast;
    ② 把 ATR 滑点按 §4 接进 `Portfolio._buy_cost` / `_sell_proceeds`,
    并给出**零漂移证明** (系数为 0 时逐位不变) + 行为档守卫。
    """
    hits = _fee_readers()
    assert not hits, (
        f"§13.98: `TradeFill.fee` 现在**有消费者**了: {hits}。\n"
        f"⇒ 本族那条'成本模型被丢弃'的前提已经不成立 ⇒ **`backtrader_engine.__init__` "
        f"里的 `atr_slip_scale > 0` fail-fast 必须删掉**, 并按 §4 真正接线。\n"
        f"⚠️ 接线时仍须: 系数为 0 时**逐位零漂移** + 一条**行为档**守卫。"
    )


def test_cycle_rejects_a_nonzero_slippage_coefficient_at_construction() -> None:
    """fail-fast 必须在**构造时**就拒绝 (§0 要求 "throw immediately")。

    判据: 源码里 `__init__` 开头有对 `self.p.atr_slip_scale > 0` 的 `raise ValueError`,
    且理由**点名了那两套模型** (不是一句泛泛的"未实现")。
    """
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    init = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None)
    assert init is not None, "找不到 __init__"
    txt = ast.unparse(init)
    assert "atr_slip_scale" in txt and "raise" in txt, (
        "§13.98: `__init__` 里没有对 `atr_slip_scale > 0` 的 fail-fast ⇒ "
        "该旋钮会**静默无效** (§0 违规)。"
    )
    for token in ("Portfolio", "ReplayBroker", "零消费者"):
        assert token in txt, (
            f"§13.98: fail-fast 的理由必须**点名根因** ({token!r} 缺失) —— "
            f"一句泛泛的'未实现'会让下一个人以为只要接线就行。"
        )


def _db_available() -> bool:
    try:
        from hiagent_config import DB_PATH
    except Exception:
        return False
    return Path(str(DB_PATH)).exists()


@pytest.mark.skipif(not _db_available(), reason="本地 DB 缺失")
def test_a_nonzero_coefficient_actually_raises_end_to_end() -> None:
    """行为档: 真的跑一次 —— fail-fast 必须在**第一只票构造时**就抛。

    它很便宜 (不跑完全窗口): 异常在 `__init__` 抛出, 而 `__init__` 在第一次
    `cerebro.run()` 时就执行。**若这条测试变慢**, 说明 fail-fast 被挪到了更晚的位置。
    """
    import datetime as dt

    from cycle_price_action.backtest import run_backtest
    from cycle_price_action.presets import PRESET_V1
    from hiagent_config import DB_PATH

    p = dict(PRESET_V1)
    p["atr_slip_scale"] = 1.0
    with pytest.raises((ValueError, RuntimeError)) as ei:
        run_backtest(str(DB_PATH), dt.date(2026, 1, 5), dt.date(2026, 1, 9), preset=p)
    assert "不可能生效" in str(ei.value), (
        f"§13.98: 抛错了别的异常 —— {ei.value!r}\n"
        f"本判据要的是**那条** fail-fast, 不是一个碰巧也炸的错。"
    )

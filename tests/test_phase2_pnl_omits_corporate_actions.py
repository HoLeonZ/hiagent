"""附一百零五 —— Phase-2 的逐笔回放**不建模公司行为**,而 `verify=True` 时报告的正是**它**的 PnL。

## 缺陷(逐处读码 + 数据实测)

`chase_up` / `uptrend_pullback` 的 `backtrader_engine.py` 是**两层**:

* **Phase 1** —— `portfolio.py::simulate_portfolio` 决定 slot / entry / exit 时机与价格,
  **并且**逐 bar 应用公司行为(`apply_corporate_action`:现金分红入 `Free_Cash`、送股调整股数);
* **Phase 2** —— 对 Phase 1 产生的每一笔 trade,**独立跑一次 backtrader 实例**复算
  退出价与净盈亏(`_verify_trade_with_backtrader`)。

而 `run_backtrader_backtest(..., verify: bool = True)` —— **默认就跑 Phase 2**,
且跑的时候返回的是 `trades_p2 / equity_p2`(**不是** Phase 1 那份)。

⇒ **报告出来的 `net_pnl` 是 Phase-2 回放算的,而那次回放没有分红/送股入参**
(`_verify_trade_with_backtrader(...)` 的实参里没有 `div_per_share` / `bonus_ratio`)。

**调用面(实测)**:`chase_up/main.py:166`(`verify=not args.no_verify`)、
`uptrend_pullback/main.py:157`、`uptrend_pullback/bt_compare_presets.py`、
`uptrend_pullback/verify_v33_long_reverse_v4.py` —— 都是**默认开**。

## 量级(用数据实测,不是估计)

| 量 | 实测 |
|---|---|
| 窗口 2025-09-19..2026-09-19:交易日 / 标的 / 除权事件 | 242 / 5565 / **4960** |
| 单只票单个交易日出除权的概率 | 3.68e-03 |
| **持仓 3 天跨到除权日的概率** | **1.105%**(10 天 3.68%、20 天 7.37%) |
| 平均每股分红 | 0.2630 元(以 10 元股价计 ≈ **2.63%** 持仓市值) |
| ⇒ **单笔期望漏计** | **≈ 0.029%**(持仓 3 天) |

⇒ **期望量级小(~0.03%/笔)**,但那 ~1.1% 跨到除权日的交易**每笔差 2.63% 的持仓市值**。
短持仓策略下它不影响结论,**但它是 §3 「Event-Sourced Corporate Actions」的契约违反**:
Phase 1 记了、Phase 2 没记,而**报告用的是后者**。

## 为什么本轮不改,只登记

两条修法都要人来定,而且**都会改结果**:

1. **把公司行为穿进 Phase-2 的回放**(改 backtrader feed + 记账)—— Phase-2 的职责本是
   "价格/退出时点的复核",让它承担现金记账是扩大职责;
2. **`verify=True` 时改报 Phase-1 的 `net_pnl`**(Phase-1 才是现金权威路径)——
   但这会改变"Phase 2 复核过"这件事的语义(复核的是价格,不是盈亏)。

**两句都要问过使用者。** 本文件只把**机制**钉住,并在它被修好时**变红**(登记表只应当变短)。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Phase-2 的"两层"关系:`verify=True` 是默认,且跑时返回的是 Phase-2 的那份 trades。
#: (若哪天改成默认返回 Phase-1 的盈亏,或把公司行为穿进回放,这两个常量与上面的登记都该更新。)
PHASE2_IS_DEFAULT = True
PHASE2_REPLAY_FEEDS_NO_DIVIDEND_INPUT = True

_CORPORATE_KEYS = {"div_per_share", "bonus_ratio", "rights_ratio"}


def _engine_src(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _replay_signature_params(src: str, func_name: str) -> set[str]:
    """`func_name` 的形参名集合(AST,不受注释干扰)。"""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            a = node.args
            names = {x.arg for x in (*a.args, *a.kwonlyargs, *a.posonlyargs)}
            if a.vararg:
                names.add(a.vararg.arg)
            if a.kwarg:
                names.add(a.kwarg.arg)
            return names
    raise AssertionError(f"找不到函数 {func_name}")


@pytest.mark.parametrize("rel", [
    "chase_up/backtrader_engine.py",
    "uptrend_pullback/backtrader_engine.py",
])
def test_phase2_replay_still_has_no_corporate_action_input(rel: str) -> None:
    """**登记项**:Phase-2 的逐笔回放不接受分红/送股入参。

    **这条红掉是好事** —— 它意味着有人把公司行为穿进了 Phase-2,那时应把本文件的
    docstring 与上一条登记一起更新(登记表只应当变短),而不是把断言删掉了事。
    """
    params = _replay_signature_params(_engine_src(rel), "_verify_trade_with_backtrader")
    fed = params & _CORPORATE_KEYS
    assert (not fed) == PHASE2_REPLAY_FEEDS_NO_DIVIDEND_INPUT, (
        f"{rel}: `_verify_trade_with_backtrader` 的公司行为入参 = {sorted(fed)} —— "
        f"与登记项({PHASE2_REPLAY_FEEDS_NO_DIVIDEND_INPUT})相反。"
        "若已把公司行为穿进 Phase-2,请更新本文件与附一百零五 的登记。"
    )


@pytest.mark.parametrize("rel", [
    "chase_up/backtrader_engine.py",
    "uptrend_pullback/backtrader_engine.py",
])
def test_phase2_is_what_gets_reported_when_verify_is_on(rel: str) -> None:
    """这条缺口**之所以重要**:`verify=True` 时返回的是 **Phase-2** 的那份 trades。

    (若哪天改成返回 Phase-1 的盈亏,缺口就只剩"复核没算分红"这一层 —— 那时本登记该更新。)
    """
    src = _engine_src(rel)
    assert "verify: bool = True" in src, (
        f"{rel}: `verify` 的默认值不再是 True —— 缺口的调用面变了,请复核附一百零五"
    )
    assert "trades_p2, equity_p2" in src, (
        f"{rel}: 找不到返回 Phase-2 结果的那条路径 —— 请复核附一百零五 的机制描述"
    )


def test_the_registration_is_not_vacuous() -> None:
    """**非空转**:两个引擎都得有 Phase-1(记账)/ Phase-2(复核)两层,登记才有对象。"""
    for rel in ("chase_up/backtrader_engine.py", "uptrend_pullback/backtrader_engine.py"):
        src = _engine_src(rel)
        assert "simulate_portfolio(" in src, f"{rel}: 找不到 Phase-1 调用 — 分层描述失效"
        assert "_verify_trade_with_backtrader(" in src, f"{rel}: 找不到 Phase-2 复算入口"

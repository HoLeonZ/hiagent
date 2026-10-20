"""附一百 —— 把矩阵的一行从"实现**在不在**"升级为"**四族算出来一样不一样**"。

## 为什么要再进一步

契约矩阵(附九十一~九十九)钉的是**存在性**:每条契约在四个引擎里各有一个落点。
但仓库自己早就写过一句警告(`test_preset_declarations_are_load_bearing.py` 开头):

> 往 `params = dict(weight_kline=1.0, …)` 里加一个默认值就能让审计变绿,而声明依然被忽略。

**四族各写一份"同一条契约"的实现,就是四次写错的机会。** 本文件挑矩阵里**最便宜可差分的那一行**
—— §2 成本模型 —— 把"存在"升级为"**数值一致**"。

## 实测结论:四族**逐值一致**,而且方向是对的

| 引擎 | 卖出侧的费 | 买入侧的费 |
|---|---|---|
| `chase_up` / `uptrend_pullback` | `max(n·r, m) + n·stamp` | `max(n·r, m)` |
| `cycle_price_action` | `max(MIN, n·R) + n·STAMP_TAX_SELL` | `max(MIN, n·R)` |
| `short_reversal` | **entry**(做空开仓 = **卖**)含印花税 | **exit**(买回平仓 = **买**)不含 |

**`short_reversal` 的入口/出口与多头引擎"名字相反":它的 entry 是卖、exit 是买。**
费用**跟着方向**走:卖出缴印花税、买入不缴。跨过这层名字,四族完全一致。

⇒ 本文件钉三件事:

1. **数值一致**:`chase_up` / `uptrend_pullback` 直接调 `buy_cost`/`sell_cost`;
   `cycle_price_action` 的接口是**现金差额**(`_buy_cost` 返回 `notional+comm`,
   `_sell_proceeds` 返回 `notional-comm-tax`),用差额还原费用;三者都必须在
   **小额(触发最低佣金 ¥5)与大额(触发费率)** 两个区间上与规范式逐值相等。
2. **方向正确**:`short_reversal` 的 entry 费**必须**含印花税、exit 费**必须**不含 ——
   用 AST 取赋值右侧来看,不受注释干扰。**若有人"顺手把印花税从 entry 挪到 exit"
   (以为 entry 是买),这一条会红。**
3. **单源**:四族的费率常量都必须等于 `core.dual_price` 的值(不许就地写数字)。

`short_reversal` 的费用是内联在 `next()` 里的,不能直接调 ⇒ 第 1 条对它不适用,
改用第 2 条的结构判据(方向),**如实说明这个覆盖差**。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from core.dual_price import COMMISSION_RATE, MIN_COMMISSION, STAMP_DUTY_RATE

REPO_ROOT = Path(__file__).resolve().parents[1]

#: 覆盖到**小额**(触发最低佣金)与**大额**(触发费率)两个区间,以及一个中间值。
NOTIONALS = (500.0, 10_000.0, 50_000.0, 1_000_000.0)


def canonical_buy(notional: float) -> float:
    return max(notional * COMMISSION_RATE, MIN_COMMISSION)


def canonical_sell(notional: float) -> float:
    return canonical_buy(notional) + notional * STAMP_DUTY_RATE


def _chase_uptrend():
    from chase_up.portfolio import Portfolio as CP
    from uptrend_pullback.portfolio import Portfolio as UP

    out = []
    for cls in (CP, UP):
        p = cls.__new__(cls)
        p.commission_rate = COMMISSION_RATE
        p.min_commission = MIN_COMMISSION
        p.stamp_duty_rate = STAMP_DUTY_RATE
        out.append((cls.__module__.split(".")[0], p))
    return out


def _cycle():
    from cycle_price_action.portfolio import Portfolio as YP

    return YP.__new__(YP)


@pytest.mark.parametrize("notional", NOTIONALS)
def test_long_engines_fee_functions_match_the_canonical_formula(notional: float) -> None:
    """§2 单源:三族的买卖两侧费用必须与规范式**逐值相等**。"""
    want_buy, want_sell = canonical_buy(notional), canonical_sell(notional)
    bad = []
    for name, p in _chase_uptrend():
        if p.buy_cost(notional) != pytest.approx(want_buy) or \
           p.sell_cost(notional) != pytest.approx(want_sell):
            bad.append(f"{name}: buy={p.buy_cost(notional)} sell={p.sell_cost(notional)}")
    y = _cycle()
    got_buy = y._buy_cost(notional, 1) - notional          # 接口是现金差额,不是费用
    got_sell = notional - y._sell_proceeds(notional, 1)
    if got_buy != pytest.approx(want_buy) or got_sell != pytest.approx(want_sell):
        bad.append(f"cycle: buy={got_buy} sell={got_sell}")
    assert not bad, (
        f"§2 VIOLATION: notional={notional} 时与规范式不符"
        f"(期望 buy={want_buy} sell={want_sell}):\n  " + "\n  ".join(bad)
    )


def test_the_two_long_engines_agree_with_each_other() -> None:
    """chase 与 uptrend 是**同源演化**的一对;它们必须逐值相同。

    (把这一条单列,是因为"三个都错了但要错得一样"比"一个错了"更难被发现 ——
     与 canon 比才算数,而这一条只是把"同源"这个事实钉住。)
    """
    (n1, a), (n2, b) = _chase_uptrend()
    for notional in NOTIONALS:
        assert a.buy_cost(notional) == b.buy_cost(notional), f"{n1} vs {n2} buy @ {notional}"
        assert a.sell_cost(notional) == b.sell_cost(notional), f"{n1} vs {n2} sell @ {notional}"


def _assigned_rhss(src: str, name: str) -> list[str]:
    """取**所有** `name = ...` 赋值右侧的源码(AST,不受注释干扰)。

    返回列表而不是第一个 —— 实测该文件里 `entry_fee` 另有赋值(`pos.get('entry_fee')`
    的读取),只取第一个会取到**不相干**的那处。
    """
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            out.append(ast.unparse(node.value))
    assert out, f"找不到赋值 {name} = ..."
    return out


def _fee_formula(src: str, name: str) -> str:
    """赋值右侧里**那一条费用公式**(以出现 `commission_rate` 为标志)。"""
    cands = [r for r in _assigned_rhss(src, name) if "commission_rate" in r]
    assert cands, f"{name} 的赋值里找不到含 commission_rate 的费用公式"
    return cands[0]


def test_short_engine_fees_follow_the_direction_not_the_name() -> None:
    """§4/§2:做空引擎的 entry 是**卖**(缴印花税)、exit 是**买**(不缴)。

    判据用 AST 取赋值右侧,所以注释里写"印花税"不会干扰。
    **这条会在有人"顺手把印花税从 entry 挪走"时红** —— 那看起来像是在修一个
    "多头引擎买入不缴税,怎么它缴"的不一致,实际是把方向搞反了。
    """
    src = (REPO_ROOT / "short_reversal" / "replay_strategy_v3.py").read_text(encoding="utf-8")
    entry_rhs, exit_rhs = _fee_formula(src, "entry_fee"), _fee_formula(src, "exit_fee")
    assert "stamp_duty_rate" in entry_rhs, (
        "§2: short_reversal 的 **entry 是做空开仓(= 卖出)**,必须计印花税;"
        f"实际右侧为 {entry_rhs}"
    )
    assert "stamp_duty_rate" not in exit_rhs, (
        "§2: short_reversal 的 **exit 是买回平仓(= 买入)**,不应计印花税;"
        f"实际右侧为 {exit_rhs}"
    )
    # 佣金项由 `_fee_formula` 的选择条件保证(它以 commission_rate 为标志)


@pytest.mark.parametrize("rel,names", [
    ("chase_up/portfolio.py", ("commission_rate", "min_commission", "stamp_duty_rate")),
    ("uptrend_pullback/portfolio.py", ("commission_rate", "min_commission", "stamp_duty_rate")),
    ("short_reversal/replay_strategy_v3.py", ("COMMISSION_RATE", "MIN_COMMISSION", "STAMP_DUTY_RATE")),
    ("cycle_price_action/portfolio.py", ("COMMISSION_RATE", "MIN_COMMISSION", "STAMP_TAX_SELL")),
])
def test_fee_constants_are_imported_not_redefined(rel: str, names: tuple[str, ...]) -> None:
    """§2:费率常量**只允许从 `core.dual_price` 取**,不许就地写一个数字。

    (`cycle` 的 `STAMP_TAX_SELL` 是它自己的类常量名 —— 名字不同,值必须来自 core;
     下面 `test_the_class_constants_equal_the_core_values` 钉住取值。)
    """
    src = (REPO_ROOT / rel).read_text(encoding="utf-8")
    for n in names:
        # 事故形态:NAME = <数字>
        assert not re.search(rf"^\s*{n}\s*=\s*[0-9]", src, re.M), (
            f"§2: {rel} 里 {n} 被就地写成了数字 —— 必须来自 core.dual_price"
        )


def test_the_class_constants_equal_the_core_values() -> None:
    """`cycle` 用类常量名承载同一批值 —— 逐值核对,防止改名改值时漂掉。"""
    from cycle_price_action.portfolio import Portfolio as YP

    assert YP.COMMISSION_RATE == pytest.approx(COMMISSION_RATE)
    assert YP.MIN_COMMISSION == pytest.approx(MIN_COMMISSION)
    assert YP.STAMP_TAX_SELL == pytest.approx(STAMP_DUTY_RATE)


def test_the_differential_is_not_vacuous() -> None:
    """**非空转**:必须真的取到了三个引擎的费用函数并算出了非零费用。"""
    got = [(n, p.buy_cost(50_000.0)) for n, p in _chase_uptrend()]
    assert len(got) == 2 and all(v > 0 for _, v in got), f"夹具失效:{got}"
    y = _cycle()
    assert y._sell_proceeds(10.0, 1000) > 0, "夹具失效:cycle 的卖侧没算出东西"


def test_the_differential_has_teeth() -> None:
    """**牙齿**:把"卖出侧的印花税项"去掉,规范式比较必须不成立(纯函数层)。"""
    notional = 50_000.0
    broken = canonical_buy(notional)          # 漏掉印花税的"卖出费"
    assert broken != pytest.approx(canonical_sell(notional)), "夹具失效:两种口径竟然相等"

    src = (REPO_ROOT / "short_reversal" / "replay_strategy_v3.py").read_text(encoding="utf-8")
    assert "stamp_duty_rate" in _fee_formula(src, "entry_fee")
    # 合成一个"把税挪到 exit"的源码 ⇒ AST 判据应能认出
    fake = ('entry_fee = max(m, n * commission_rate)\n'
            'exit_fee = max(m, n * commission_rate) + n * stamp_duty_rate\n')
    assert "stamp_duty_rate" not in _fee_formula(fake, "entry_fee")
    assert "stamp_duty_rate" in _fee_formula(fake, "exit_fee")

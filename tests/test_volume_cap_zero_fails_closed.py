"""§4/§0 守卫:零成交 bar 必须**拒单**,不得"跳过量比约束"。

## 缺陷(审计 §3.3 的 MEDIUM×3,**本轮复核确认成立**)

四个引擎都把量比约束写成:

```python
if bar_vol > 0:                     # ← 这里
    max_fill = volume_cap_fill(bar_vol, pct, lot_size=100)
    if max_fill > 0 and size > max_fill:
        size = max_fill
```

`volume_cap_fill` 对 `bar_vol <= 0` **已经**返回 0(= §4 的
`MIN(Target, Bar_Volume × 0.10)`,零成交 ⇒ 零成交),而 `if bar_vol > 0` 让整段
**根本不执行** —— 于是零成交 bar 上的订单**不限量**。§0 verbatim:

  "**Pessimistic Default:** Always assume the worst-case scenario for market
   liquidity, execution price, and statistical significance."

零成交 / 成交量未知正是**最坏流动性**;跳过约束等于假设无限承接。

**"规则存在 ≠ 规则被应用"**:契约早有测试钉着
(`test_short_reversal_volume_cap.py:44`:`volume_cap_fill(0, …) == 0`),
缺的是**调用点照它执行**。

## 严重度(实测)

本机行情库 **10,364,755** 行 `v_daily` 中,`volume <= 0` 与 `volume IS NULL`
均为 **0 行** —— 故这是**潜在**缺陷(当前数据触发不到),不是正在发生的错误。
仍要修:分支的形状在原理上就是错的,而"触发不到"只是一份数据快照的巧合。

## 修法

零成交 ⇒ `volume_cap_fill` 返回 0 ⇒ 订单量归零 ⇒ 由各引擎既有的"过小即拒"
分支如实拒单。`None` / `NaN` 才是"面板无 volume 列"的**兼容**路径(且 helper
不能吃 NaN —— `int(nan)` 会抛 ValueError),两者不可混为一谈。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

CAP_SITES = {
    "chase_up/portfolio.py": "bar_vol",
    "uptrend_pullback/portfolio.py": "bar_vol",
    "short_reversal/replay_strategy_v3.py": "bar_vol",
    "cycle_price_action/portfolio.py": "bar_volume",
}


def _code(path: Path) -> str:
    return "\n".join(
        l for l in path.read_text(encoding="utf-8").splitlines()
        if not l.strip().startswith("#")
    )


@pytest.mark.parametrize("rel,var", sorted(CAP_SITES.items()))
def test_cap_is_not_gated_on_positive_volume(rel: str, var: str) -> None:
    """不得再用 `if <vol> > 0:` 把**量比约束调用**整段跳过(fail-open 形态)。

    判据刻意**只**针对 cap 调用点:同文件里还有 `if bar_vol > 0: participation = ...`
    这类**除法保护**(分母为 0 时落到 `participation = 0.0`),那是滑点模型的另一件事,
    不是本缺陷,不应被误伤。
    """
    lines = _code(REPO_ROOT / rel).splitlines()
    offenders = []
    for i, line in enumerate(lines):
        if "volume_cap_fill(" not in line:
            continue
        # 往回看 5 行,找包住这个调用的 `> 0` 门
        for back in range(1, 6):
            if i - back < 0:
                break
            prev = lines[i - back]
            if re.search(rf"if [^\n]*{var} > 0\s*:", prev):
                offenders.append(prev.strip())
                break
            if re.search(rf"{var} = ", prev):   # 越过赋值即停止回看
                break
    assert not offenders, (
        f"§4/§0: {rel} 把量比约束挂在 `{var} > 0` 上 —— 零成交 bar 会因此**不限量**。"
        f"零成交应走 helper 得到 0 后如实拒单。命中: {offenders}"
    )


@pytest.mark.parametrize("rel,var", sorted(CAP_SITES.items()))
def test_cap_still_calls_the_canonical_helper(rel: str, var: str) -> None:
    """约束本身仍必须走规范单源(修 fail-open 不等于可以去掉约束)。"""
    code = _code(REPO_ROOT / rel)
    assert "volume_cap_fill(" in code, f"{rel} 未调用规范 volume_cap_fill"


def test_helper_contract_for_zero_volume_is_zero() -> None:
    """§4 的算式本身:`MIN(Target, 0 × pct) = 0`(规则存在 —— 缺的是调用点遵从)。"""
    from core.dual_price import volume_cap_fill

    assert volume_cap_fill(0.0, 0.10, lot_size=100) == 0
    assert volume_cap_fill(-1.0, 0.10, lot_size=100) == 0


def test_chase_up_zero_volume_bar_produces_no_fill() -> None:
    """行为验证:零成交 bar 上**不产生成交**(而不是无上限地成交)。

    复用既有夹具(`test_volume_cap_low_bar`),只把 bar_vol 设成 0。
    """
    from chase_up.portfolio import simulate_portfolio

    from tests.test_volume_cap_low_bar import _build_entries, _build_low_vol_panel

    panel = _build_low_vol_panel(["ILLQ.SZ"], bar_vol=0.0)
    trades, _ = simulate_portfolio(
        _build_entries(["ILLQ.SZ"]), panel,
        tp_pct=0.10, sl_pct=0.05, max_hold=8, max_positions=1,
        start_date="2025-09-01", end_date="2025-09-15",
        initial_capital=100_000.0,
        position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
    )
    assert len(trades) == 0, (
        f"§4/§0: 零成交 bar 上产生了 {len(trades)} 笔成交 —— "
        "零成交意味着这个 bar 物理上承接不了任何订单。"
    )

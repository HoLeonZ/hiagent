"""§2 Single-Bullet Execution: **声明了 `max_positions > 1` 的族必须有并发计数闸门**。

## §2 原文
> **Single-Bullet Execution (单发子弹机制):** If concurrent signals are generated at time T,
> the engine MUST sort them by statistical conviction (or a predefined tie-breaker) and fill
> strictly in that order. **Capacity is bounded by the preset's `max_positions`**; signals
> beyond capacity at time T MUST BE IMMEDIATELY DISCARDED (no queueing into T+1).

## 2026-10-19 (§13.24): 这条契约**此前没有任何守卫** —— 而它确实被违反了
`max_positions` 在四个族里的含义**不一致**:

| 族 | 声明 N>1 的 preset | 并发计数闸门 | |
|---|---|---|---|
| `chase_up` | **0** (全 22 个都是 1) | ✅ `portfolio.py:491` `if len(positions) >= max_positions: break` | |
| `uptrend_pullback` | **0** (全 4 个都是 1) | ✅ `portfolio.py:458` 同上 | |
| `cycle_price_action` | 0 (`PRESET_V1` N=1) | ✅ `allocator.py` 显式容量层 + `n_rejected_capacity` | |
| `short_reversal` | **10 个** (N ∈ 2/3/4) | ❌ **全族 0 处** | ← 违反 |

> **注意这是"族内不对称"的**反向**形态**: 规则不是"在一个族里修了、忘了兄弟族",
> 而是**实现在不需要它的三个族里, 漏在唯一需要它的那一族。**
> 对 chase_up/uptrend 而言那行闸门**永远不会触发** (N 恒为 1), 所以它们**看起来**
> 已经满足契约; 而唯一会触发的 short_reversal **一行都没有**。

### 为什么这不是"命名问题" —— 语义被实测证伪
`short_reversal/replay_strategy_v3.py:774-775` 把 N 用作**每一笔的 sizing 除数**,
除的是**当前剩余** `free_cash`, 且填充循环内**没有计数判断**:
```python
if self.p.max_positions > 1:
    target_value = self.free_cash / self.p.max_positions   # 每次开仓都再除一次
```
后果 (实测 `v58_mp_2`, 2025-01-01..2025-09-30):
* 声明 `max_positions=2`, **实测最大并发 15**; **30.1% 的交易日**并发 > 2;
  (`v58_mp_4`: 声明 4, 实测 **29**, 20.2% 的交易日 > 4)
* 2025-04-22 同日 9 个信号, 成交规模**几何递减**:
  `48200, 53400, 14800, 5300, 4800, 3400, ... 300, 300, 100, 100` —— 一路衰到 1 手地板。
  ⇒ **"N 个等额仓位"这个语义从未成立**: 第一笔独占 47%, 其余是零头。
* 所以历史上"提高 `max_positions` (N=2/N=4)"这个方向 (§3.1) **测的不是它声称的东西**。

## 判据 (§6: 必须能失败)
**只有**声明了 N>1 的族才被要求有闸门 —— 这个"要求"本身是**从 preset 数据推导出来的**,
不是写死的: 若日后 chase_up 加一个 N=2 的 preset, 本测试立刻要求它也有闸门。

豁免是**登记的债**, 且**自失效**: 若 short_reversal 补上了闸门, 豁免断言会**立刻红**,
提示把豁免删掉 —— 不允许"修好了但债还挂着"。
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

# 并发计数闸门的形态 (静态; 不需要跑回测 ⇒ 零运行时成本)
GATE_PATTERNS = (
    r"len\(\s*positions\s*\)\s*>=",       # chase_up / uptrend 的写法
    r"n_rejected_capacity",                # cycle 的容量层
    r"len\(\s*self\.[a-z_]*positions\s*\)\s*>=",  # 引擎内 self.positions 变体
)

# ⛔ 登记的债 (§13.24): 这个族声明了 N>1 但没有闸门。**修好后必须删掉这一行**。
REGISTERED_DEBT = {
    "short_reversal": "§13.24 —— 10 个 preset 声明 N∈{2,3,4}, 而 replay_strategy_v3.py "
                      "把 max_positions 只当 sizing 除数用, 无并发计数闸门; "
                      "实测 v58_mp_2 并发峰值 15。修它属**结果变更**, 按授权只登记。",
}


def _families() -> list[str]:
    """发现式: 任何含 `presets.py` 的目录都是一个族 (§13.22/§13.23 的教训)。"""
    return sorted(p.parent.name for p in ROOT.glob("*/presets.py"))


def _declared_max_positions(fam: str) -> set[int]:
    """把该族 preset 模块里**所有** `max_positions` 取值收出来 (扁平/嵌套两种形状都认)。"""
    mod = importlib.import_module(f"{fam}.presets")
    vals: set[int] = set()

    def walk(o) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "max_positions" and isinstance(v, int):
                    vals.add(v)
                elif isinstance(v, dict):
                    walk(v)

    for name in dir(mod):
        if name.isupper():
            walk(getattr(mod, name))
    return vals


def _gate_hits(fam: str) -> list[str]:
    hits = []
    for p in sorted((ROOT / fam).rglob("*.py")):
        if "test" in p.parts:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if any(re.search(pat, line) for pat in GATE_PATTERNS):
                hits.append(f"{p.relative_to(ROOT)}:{i}")
    return hits


def test_families_are_discovered() -> None:
    """发现式扫描必须真的找到族 —— 否则下面的断言全是空的 (§13.19 的教训)。"""
    fams = _families()
    assert len(fams) >= 4, f"只发现 {len(fams)} 个族: {fams} —— 发现逻辑坏了"


@pytest.mark.parametrize("fam", _families())
def test_multi_slot_family_has_a_capacity_gate(fam: str) -> None:
    """声明了 N>1 的族必须真的有并发计数闸门 (§2 Single-Bullet)。"""
    vals = _declared_max_positions(fam)
    needs_gate = any(v > 1 for v in vals)
    hits = _gate_hits(fam)

    if not needs_gate:
        return  # 该族没有任何多槽 preset ⇒ §2 的容量条款对它无内容

    if fam in REGISTERED_DEBT:
        assert not hits, (
            f"{fam} 现在**已经有**闸门了 ({hits[:3]}) —— 说明 §13.24 那笔登记的债已经还清。\n"
            f"请把 REGISTERED_DEBT 里 `{fam}` 这一条删掉 (豁免不得继续挂着), "
            f"并在 docs/strategy_mining_log.md §13.24 记下结果漂移。"
            f"\n债的原文: {REGISTERED_DEBT[fam]}"
        )
        pytest.xfail(f"{fam}: 登记在案的 §2 违反 —— {REGISTERED_DEBT[fam]}")

    assert hits, (
        f"{fam} 的 preset 声明了 max_positions>1 ({sorted(vals)}), 但整个族里"
        f"**找不到任何并发计数闸门**。\n"
        f"§2 Single-Bullet Execution: \"Capacity is bounded by the preset's max_positions; "
        f"signals beyond capacity at time T MUST BE IMMEDIATELY DISCARDED\"。\n"
        f"⇒ 必须补一个 `len(positions) >= max_positions` 式的判断 (参照 "
        f"chase_up/portfolio.py:491 与 uptrend_pullback/portfolio.py:458 的写法)。"
    )


def test_all_four_families_are_covered() -> None:
    """四族必须都在被检查之列 —— 防止发现式扫描悄悄漏掉一族。"""
    fams = [f for f in _families() if (ROOT / f / "presets.py").exists()]
    for expected in ("short_reversal", "chase_up", "uptrend_pullback", "cycle_price_action"):
        assert expected in fams, f"{expected} 不在被扫描的族里 —— 守卫对它失明"

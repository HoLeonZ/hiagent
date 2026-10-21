"""§5: 被计数的 preset 必须是**互不相同**的试验 —— 等价类会把 `n_trials` 记虚。

## 2026-10-19 (§13.31) 的实测
在锁定窗口 (`2025-09-19..2026-09-19`) 上把 `chase_up` 全部 **22** 个 preset 各跑一次,
按 `trades.csv` 的 sha256 分组:

```
22 个 preset  ->  只有 17 个互不相同的成交列表
```

两个等价类:
| 哈希 | 笔数 | 成员 |
|---|---|---|
| `fc614dc1ae9e` | 12 | **`v13` / `v14` / `v15` / `v16` / `v17`** |
| `e78458f341dc` | 34 | `chase_v1_atr_tp4_sl1` / `chase_v2_atr_tp4_sl1_pos3` |

⇒ 区分它们的那些参数轴 (`atr035` / `mom10` / `mom11` / `ma60buf08` / `atr082` /
以及 v2 的 `_pos3`) 在**这段窗口上完全没有效果**。

## 为什么这与 §5 有关
§5 要求 `n_trials` 会计: 每次评估都要计入 (日志 §5: "新增一个候选 preset 时必须同时
加上本轮的试验数")。**但"22 个候选"里有 5 个其实是同一个** ⇒
拿 preset **名字**去数试验数会**记虚** —— 而 DSR / Bonferroni 的全部效力都建立在
"n 是真实试验数"之上。

⚠️ 反向的错也在: `chase_up` 的 22 个 preset 的 `n_comparisons` **全部等于 10**
(合计 220, 从 v1 到 v19 一模一样), 而 `uptrend_pullback` 是 19/100/121/162(逐轮递增)、
`short_reversal` 各不相同 ⇒ **`chase_up` 那个 10 是占位符, 不是累加结果**。
两个方向的错相反, 所以**不能推出净方向** —— 能说清的只有:
**该族记下的这个数不是一次会计。**

## 本文件的作用 (§6: 必须能失败, 且零运行时)
只用**已提交的基线** (`tests/golden/chase_v*_baseline.json`) 里锁定的哈希,
**不跑任何回测** ⇒ 毫秒级。判据: 这些哈希必须两两不同。
今天 **xfail**(5 个撞在一起), 且 `strict=True`:
一旦有人把某条轴真正做实、哈希分开了, 它会 **XPASS ⇒ 失败**, 逼着删掉标记。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
GOLDEN = ROOT / "tests" / "golden"


def _locked_hashes() -> dict[str, str]:
    """从已提交的 chase 基线里取 {preset: sha256} —— 零运行时。"""
    out = {}
    for p in sorted(GOLDEN.glob("chase_v*_baseline.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        h = d.get("trades_csv_sha256")
        if h:
            out[p.stem] = h
    return out


def test_golden_baselines_are_discoverable() -> None:
    """正向对照: 基线必须真的读得到 —— 否则下面的断言全是空的 (§13.19 的教训)。"""
    hs = _locked_hashes()
    assert len(hs) >= 8, f"只读到 {len(hs)} 份 chase 基线 —— 发现逻辑坏了"


@pytest.mark.xfail(
    strict=True,
    reason="§13.31: chase_up 的 22 个 preset 在锁定窗口上只产出 17 个互不相同的成交列表 "
           "—— v13/v14/v15/v16/v17 哈希完全相同 (12 笔), v1/v2 也完全相同 (34 笔)。"
           "⇒ 拿 preset 名字数 §5 的 n_trials 会记虚。"
           "修好后 (某条参数轴被做实) 本测试会 XPASS(strict) ⇒ 删掉此标记并登记。",
)
def test_locked_baseline_hashes_are_all_distinct() -> None:
    """被锁定/被计数的 preset 必须两两产出**不同**的成交列表 (§5 的 n_trials 前提)。"""
    hs = _locked_hashes()
    by_hash: dict[str, list[str]] = {}
    for name, h in hs.items():
        by_hash.setdefault(h, []).append(name)
    dupes = {h: ns for h, ns in by_hash.items() if len(ns) > 1}
    assert not dupes, (
        "这些 preset 在锁定窗口上产出**完全相同**的成交列表 ⇒ 它们是同一个试验, "
        "按名字计入 n_trials 会**记虚** (§5):\n"
        + "\n".join(f"  {h[:12]}…  ←  {ns}" for h, ns in dupes.items())
    )

"""preset 键必须**被读**; 未被读的键全部列入白名单并**双向棘轮** (§13.144)。

这补的是 handoff 第 (4) 节纪律 #7「**声明 ≠ 做到**」里**唯一没有门禁的那个洞**。

判据 (AST 级 —— **"出现在文件里"不算被读**)
--------------------------------------------
一个键算"被消费"当且仅当它在引擎包里以这三种形态之一出现:
  ① `obj.get("KEY")` / `obj.get("KEY", default)`
  ② `obj["KEY"]`
  ③ `**kw` 之外的关键字 (含 `params = dict(KEY=...)` / `addstrategy(..., KEY=...)`)

⚠️ **本判据的第一版是"键名出现在引擎源码里"** ⇒ 它把 `cycle_price_action/audit_phantom.py`
  里的一句**存在性检查**当成了消费 ⇒ 报"未被读的键 = 0 个"。
  而 AST 版才给出真相 (§13.144): **两个键被四族都声明、却没有任何引擎读**。
  ⇒ 这正是 handoff 纪律 #2「判据的单位与作用域弱于它声称的性质」的又一实例。

双向棘轮 (与 §13.120 同形)
--------------------------
* **新增**一个未被读的键 ⇒ 红 (提示:"又一个没人读的旋钮");
* **修掉**其中一个 (键从"未被读"变成"被读") ⇒ **也红** ⇒ 要求同步更新白名单,
  否则白名单会烂掉、并悄悄放过下一次新增。

用法: `python3 -m pytest tests/test_preset_keys_are_read.py`
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_ENGINE_DIRS = ("chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action")
# 诊断/审计脚本不是"消费方" —— 它们只检查键**在不在**, 不读它的值。
_SKIP_FILES = {"presets.py", "audit_phantom.py"}
# 结构性 / 元数据键, 不是引擎旋钮。
_META = {"n_comparisons", "METRICS_BASIS"}

# ── 已知「被声明但无人读」的键。**双向棘轮**: 增删都要改这里并说明。 ──
_UNREAD_ALLOWLIST: dict[str, str] = {
    "price_source_for_signal":
        "§13.128 —— 82/82 个 preset 声明它, 但**唯一真读者**是 `dna_data/dual_price_resolver.py`, "
        "而 §13.11 已核实**没有任何引擎 import dna_data**。今天**零暴露** (全部值 = `adj_close` = "
        "§3 的强制值) ⇒ 值本来就对。**接线 = 采用 dna_data = 数据层改造** ⇒ 只登记, 不擅自改。",
    "MAX_POSITION_PCT":
        "§13.144 —— 四族**全部**声明它, 而**没有任何引擎读它**。"
        "`cycle_price_action/portfolio.py` 另有一个**同名类常量** `MAX_POSITION_PCT = 1.0` "
        "(那是**定义**, 不是读 preset 的那个键) ⇒ 读者会以为 preset 控制它, 其实不会。"
        "§13.86 已记: 该键四族取值**完全一致 (1.0×)** ⇒ 今天零暴露。"
        "**接线 = 决定它该管什么 (口径选择)** ⇒ 只登记, 不擅自改。",
}


def _consumed_keys() -> dict[str, set[str]]:
    """键 → 哪些引擎文件**读**了它。"""
    got: dict[str, set[str]] = {}
    for d in _ENGINE_DIRS:
        for p in (ROOT / d).rglob("*.py"):
            if p.name in _SKIP_FILES:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for n in ast.walk(tree):
                if isinstance(n, ast.Call):
                    f = n.func
                    if isinstance(f, ast.Attribute) and f.attr == "get" and n.args:
                        a = n.args[0]
                        if isinstance(a, ast.Constant) and isinstance(a.value, str):
                            got.setdefault(a.value, set()).add(p.name)
                    for kw in n.keywords:
                        if kw.arg:
                            got.setdefault(kw.arg, set()).add(p.name)
                elif isinstance(n, ast.Subscript):
                    s = n.slice
                    if isinstance(s, ast.Constant) and isinstance(s.value, str):
                        got.setdefault(s.value, set()).add(p.name)
    return got


def _declared_keys() -> set[str]:
    from chase_up.presets import PRESETS as CP
    from cycle_price_action.presets import PRESET_V1 as CY
    from short_reversal.presets import PRESETS as SP
    from uptrend_pullback.presets import PRESETS as UP

    keys: set[str] = set()
    for P in (CP, UP, SP):
        for preset in P.values():
            keys |= set(preset)
    keys |= set(CY)
    return keys - _META


def test_no_new_preset_key_is_declared_but_unread() -> None:
    consumed = _consumed_keys()
    unread = sorted(k for k in _declared_keys() if k not in consumed)
    new = sorted(set(unread) - set(_UNREAD_ALLOWLIST))
    assert not new, (
        f"§13.144: 下列 preset 键**被声明但没有任何引擎读它**: {new}\n"
        f"⇒ 要么把它接上, 要么把它从 preset 里去掉; 若确属有意保留 (零暴露且改动属结果变更),\n"
        f"   请加进本文件的 `_UNREAD_ALLOWLIST` **并写明理由与暴露范围**。"
    )


def test_allowlist_entries_are_still_unread() -> None:
    """**反向棘轮**: 白名单里的键一旦被接上, 这条会红 ⇒ 强制同步更新白名单。

    否则白名单会烂掉, 并**悄悄放过下一次新增** (与 §13.120 的双向棘轮同形)。
    """
    consumed = _consumed_keys()
    fixed = sorted(k for k in _UNREAD_ALLOWLIST if k in consumed)
    assert not fixed, (
        f"§13.144: 白名单里的这些键**现在已经被读了**: {fixed}\n"
        f"⇒ 说明有人把它们接上了。请从 `_UNREAD_ALLOWLIST` 删掉对应条目并登记这次接线"
        f" (白名单不删就会烂掉, 并放过下一次新增的'没人读的键')。"
    )


def test_allowlist_entries_carry_reasons() -> None:
    for k, why in _UNREAD_ALLOWLIST.items():
        assert why and len(why) > 40, f"白名单条目 {k} 没写清理由与暴露范围"

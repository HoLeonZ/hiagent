"""附九十七 —— 重写这条守卫:它强制的是**已被标准删除**的条款,而现行条款**没人守**。

## 病史(从 git 史查清,不是猜的)

提交 `2260ba1`(2026-09-29)把 §4 的 Exit Thresholds 一条**整句换掉了**:

```
- **Exit Thresholds (TP/SL):** … They MAY be either fixed … or ATR-based … Both are valid;
-                              document the choice in the preset's compliance header.
+ **Exit Thresholds (TP/SL) & Target Projection:** … TP/SL and slippage must always be
+                              communicated from Strategy to Broker as **relative percentages**
+                              (e.g., `sl_pct = 0.05`), NEVER as absolute point differences
+                              derived from adjusted prices …
```

即:**"compliance header" 那条要求被删了**(新文本里根本没有这个概念 ——
`grep "compliance header" CLAUDE.md` 为空),**换成了"必须用相对百分比"**。

而本仓库后续的动作全都建立在**旧文本**上:

* `48fc309` 给 **45/81 个 preset 补加了 compliance header**(为满足旧条款的守卫);
* `tests/test_tp_sl_compliance_header_4engine.py` 与 `tests/test_tp_sl_compliance_header.py`
  至今把旧文本当作 **"CLAUDE.md §4 (verbatim)"** 逐字引用,并据此**强制每个 preset 必须有
  §4 退出阈值注释** —— 它们 enforce 的是一条**标准里已经不存在**的要求;
* 标准**新增**的那半("相对百分比,NEVER 绝对价差")**没有任何守卫**。

⇒ 这正是本会话反复出现的那个形态的另一面:不是"修复漏了",而是**守卫守着一句被删掉的话**。
后果不是崩溃,而是**不一致**:守卫的失败信息会逐字引用一句标准里不存在的话(实测该文件
第 224 行就是这么打印的),而真正的要求无人守。

## 重写后的判据(现行 §4)

对四个引擎的**每一个** preset:

1. **不得声明绝对价阈值** —— 键名形如 `tp_price` / `sl_price` / `stop_price` /
   `target_price` / `exit_price` 的一律拒绝;
2. `tp_pct` / `sl_pct`(若声明)必须是**相对分数**,取值 `(0, 1]`
   —— 上界取 `1.0` 而不是 `< 1.0`:`v73_nosl` 用 `sl_pct=1.0` 表达"不止损",
   那**仍然是相对量**(100% 的入场价),不是绝对价差;
3. `atr_tp_mult` / `atr_sl_mult`(若声明)必须为正 —— 它们乘的是 **ATR%**,同为相对量。

**被删掉的那条(compliance header)不再被强制**:45 个 preset 上的注释**保留为可选文档**
(删 45 条注释是纯 churn,而它们并无害处);本文件只如实记下"这条要求已不在标准里"。

## 实测(重写时的事实)

全库 **101 个 preset**:绝对价键 **0** 个;`tp_pct`/`sl_pct` 越界 **0** 个
(唯一的 `sl_pct=1.0` 是上述合法表达)⇒ **现行条款是成立的**,只是此前没人守。
"""
from __future__ import annotations

import re

import pytest

REPO_ROOT_PARTS = ("chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action")

_ABSOLUTE_KEY = re.compile(r"^(tp|sl|stop|target|exit)_price$", re.I)

_SPECS = (
    ("chase_up", "chase_up.presets", "PRESETS"),
    ("uptrend_pullback", "uptrend_pullback.presets", "PRESETS"),
    ("short_reversal", "short_reversal.presets", "PRESETS"),
    ("cycle_price_action", "cycle_price_action.presets", "PRESET_V1"),
)


def _presets() -> list[tuple[str, str, dict]]:
    out: list[tuple[str, str, dict]] = []
    for eng, mod_name, attr in _SPECS:
        import importlib

        mod = importlib.import_module(mod_name)
        reg = getattr(mod, attr)
        if isinstance(reg, dict) and any(isinstance(v, dict) for v in reg.values()):
            items = reg.items()
        else:
            items = [(attr, reg)]
        out.extend((eng, name, cfg) for name, cfg in items)
    return out


def absolute_threshold_keys(cfg: dict) -> list[str]:
    """preset 里**绝对价阈值**式的键(§4 明令禁止的那一类)。"""
    return sorted(k for k in cfg if _ABSOLUTE_KEY.match(str(k)))


def out_of_range_pct(cfg: dict) -> list[str]:
    """`tp_pct`/`sl_pct` 必须是**相对分数** `(0, 1]`。"""
    bad = []
    for k in ("tp_pct", "sl_pct"):
        v = cfg.get(k)
        if v is None:
            continue
        if not isinstance(v, (int, float)) or not (0 < float(v) <= 1.0):
            bad.append(f"{k}={v!r}")
    return bad


def test_no_preset_declares_an_absolute_price_threshold() -> None:
    """§4:TP/SL **NEVER** 用绝对价差 —— 声明层就不许出现绝对价阈值。"""
    bad = [f"{eng}/{name}: {absolute_threshold_keys(cfg)}"
           for eng, name, cfg in _presets() if absolute_threshold_keys(cfg)]
    assert not bad, (
        "§4 VIOLATION: 以下 preset 声明了**绝对价**式的退出阈值 —— §4 要求 TP/SL 以"
        "**相对百分比**在 Strategy 与 Broker 之间传递:\n  " + "\n  ".join(bad)
    )


def test_pct_thresholds_are_relative_fractions() -> None:
    """§4:`tp_pct`/`sl_pct` 是**相对分数**(`(0, 1]`),不是百分比数字、也不是价差。"""
    bad = [f"{eng}/{name}: {out_of_range_pct(cfg)}"
           for eng, name, cfg in _presets() if out_of_range_pct(cfg)]
    assert not bad, (
        "§4 VIOLATION: 以下 preset 的 TP/SL 不是合法的**相对分数**(应为 (0, 1]):\n  "
        + "\n  ".join(bad)
    )


def test_atr_multipliers_are_positive() -> None:
    """§4:ATR 式阈值(`atr_tp_mult`/`atr_sl_mult`)乘的是 **ATR%**,必须为正。"""
    bad = []
    for eng, name, cfg in _presets():
        for k in ("atr_tp_mult", "atr_sl_mult"):
            v = cfg.get(k)
            if v is not None and (not isinstance(v, (int, float)) or float(v) <= 0):
                bad.append(f"{eng}/{name}: {k}={v!r}")
    assert not bad, "§4: 以下 ATR 倍数不是正数:\n  " + "\n  ".join(bad)


def test_the_rule_is_not_vacuous() -> None:
    """**非空转**:必须真的扫到四个引擎的 preset(判据坏了会掉到 0)。"""
    rows = _presets()
    engines = {e for e, _, _ in rows}
    assert len(rows) >= 80 and engines == set(REPO_ROOT_PARTS), (
        f"只扫到 {len(rows)} 个 preset / 引擎 {sorted(engines)} —— 扫描面可能已失效"
    )


def test_the_rule_has_teeth() -> None:
    """**牙齿**:三种违例各判一次,合法形状不得误报。"""
    assert absolute_threshold_keys({"sl_price": 9.9}) == ["sl_price"]
    assert absolute_threshold_keys({"sl_pct": 0.05}) == []
    assert out_of_range_pct({"sl_pct": 0.05}) == []
    assert out_of_range_pct({"sl_pct": 1.0}) == []          # 「不止损」的合法表达
    assert out_of_range_pct({"sl_pct": 5.0}) != []          # 5.0 是百分比数字,不是分数
    assert out_of_range_pct({"sl_pct": -0.1}) != []


def test_the_retired_clause_is_not_quoted_as_a_standard() -> None:
    """**被删掉的那句话,不许再被当作标准的原文引用。**

    `2260ba1` 把 §4 那句整句换掉了。此前两个测试文件把它标成
    "CLAUDE.md §4 (verbatim)",而失败信息会**逐字引用一句标准里不存在的话** ——
    那把错误告诉了下一个人。两个旧守卫已删(它们 enforce 的正是那条被删的要求);
    本条钉住"不许再回来"。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    hits = []
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        src = p.read_text(encoding="utf-8")
        if "document the choice in the preset" not in src:
            continue
        # **允许引用,但必须带出处**:一段"病史"要能贴出被删的那句原话才有用。
        # 条件:同文件里出现它被删于哪个提交(`2260ba1`)或"已删除"字样。
        if "2260ba1" in src or "已删除" in src or "已被删除" in src:
            continue
        hits.append(str(p.relative_to(root)))
    assert not hits, (
        "§0: 以下文件引用了 §4 里**已被 2260ba1 删除**的那句话,却没有写明它已被删"
        "(常表现为把它标成 'verbatim' 当作现行标准):\n  " + "\n  ".join(hits)
    )


def test_the_retired_guards_are_gone() -> None:
    """两个守着**已删条款**的守卫应当已经不在了(它们的内容由本文件接管)。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    stale = [f for f in ("tests/test_tp_sl_compliance_header.py",
                         "tests/test_tp_sl_compliance_header_4engine.py")
             if (root / f).exists()]
    assert not stale, (
        "§0: 以下文件仍在强制 §4 里**已被 2260ba1 删除**的「compliance header」要求:\n  "
        + "\n  ".join(stale)
        + "\n它们的内容已由本文件的现行条款守卫接管。"
    )

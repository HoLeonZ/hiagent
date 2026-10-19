"""preset 的**名字**必须与它自己的取值一致 —— 一条**双向棘轮**门禁 (§13.160)。

为什么有这条
------------
`chase_up` 的 `DEFAULT` preset 叫 `chase_v19_pos2_equal_...`, 而它解析出来是
`max_positions=1, position_sizing='all_in'`。全族普查 (2026-10-20):

    chase_up            22 个 preset: 名里 `_posN_` 不符 **15**; 名里 `_equal` 不符 **14**
    uptrend_pullback     4 个: 0 / 0      short_reversal 55 个: 0 / 0
    cycle_price_action   1 个: 0 / 0

本册**知道**这次配置漂移 (V7: `equal`/pos2 → `all_in`/pos1), 但**名字从没跟着改**
⇒ 名字现在描述的是**转换前**的配置。

⇒ 这是「**声明 ≠ 做到**」的**第四个表面**:
① 注释 · ② preset 键 · ③ 键被同块代码覆盖 (§13.159) · **④ 标识符本身**。
而 ④ 最难自查 —— **没人会去核对一个名字**, 索引/按名筛选/读日志的人都会被误导。

为什么是**棘轮**而不是直接修
----------------------------
这些名字是 `tests/golden/*.json` 与 `tests/_regen_chase_baselines.py` 的**键**,
而 §6.1 明文要求 golden baseline "**先核实漂移再重生成**" ⇒ 改名会牵动那批**受门禁保护的产物**,
属**需单独决策**的改动 (改名对**结果零漂移**, 但爆炸半径落在受保护产物上)。
所以本守卫**先把现状钉住**:
* **新增**一处不符 ⇒ **红** (不许谎话再扩散);
* **修好**一处而没从清单里删 ⇒ **也红** (清单只许缩短, 不许僵化成"永久豁免")。

⚠️ 本守卫**不能**做什么: 它只比对**名字里的模式与取值**, 不知道哪个名字"听上去对" ——
   也不判断 `all_in`/`N=1` 本身是好是坏。它只保证**读名字的人不会被骗**。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_FAMILIES = ("chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action")


def _load(pkg: str) -> dict:
    m = __import__(f"{pkg}.presets", fromlist=["x"])
    if hasattr(m, "PRESETS"):
        return dict(m.PRESETS)
    if hasattr(m, "PRESET_V1"):
        return {"PRESET_V1": dict(m.PRESET_V1)}
    return {}


def _mismatch(name: str, p: dict) -> list[str]:
    """名字里声称的档位/仓位方式, 与它自己声明的取值对不上 ⇒ 列出不符项。"""
    out: list[str] = []
    m = re.search(r"_pos(\d+)_", name)
    if m and int(m.group(1)) != int(p.get("max_positions", -9)):
        out.append("posN")
    if "_equal" in name and p.get("position_sizing") != "equal":
        out.append("equal")
    # ⚠️ 排序: 判据是**集合**相等, 列表顺序无语义 (第一版两边一个 append 序、一个 sorted
    # ⇒ 集合完全相同却报"不符集合变了")。
    return sorted(out)


def _scan() -> tuple[dict, int]:
    got: dict = {}
    total = 0
    for pkg in _FAMILIES:
        for n, p in _load(pkg).items():
            total += 1
            k = _mismatch(n, p)
            if k:
                got.setdefault(pkg, {})[n] = k
    return got, total


_MISMATCH = {
    'chase_up': {
        'chase_v10_pos2_equal_atr_tp6_sl15_mh18_score16': ['equal', 'posN'],
        'chase_v11_pos2_equal_atr_tp6_sl15_mh18_score17': ['equal', 'posN'],
        'chase_v12_pos2_equal_atr_tp6_sl15_mh18_score17_atr035': ['equal', 'posN'],
        'chase_v13_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom10': ['equal', 'posN'],
        'chase_v14_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom11': ['equal', 'posN'],
        'chase_v15_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom11_ma60buf08': ['equal', 'posN'],
        'chase_v16_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom115_ma60buf08': ['equal', 'posN'],
        'chase_v17_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom115_ma60buf08_atr082': ['equal', 'posN'],
        'chase_v18_pos2_equal_atr_tp6_sl16_mh18_score17_atr035_mom115_ma60buf08_atr082': ['equal', 'posN'],
        'chase_v19_pos2_equal_atr_tp6_sl175_mh18_score17_atr035_mom115_ma60buf08_atr082': ['equal', 'posN'],
        'chase_v5_pos2_equal_atr_tp6_sl15_mh10': ['equal', 'posN'],
        'chase_v6_pos3_all_in_atr_tp6_sl15_mh15': ['posN'],
        'chase_v7_pos2_equal_atr_tp6_sl15_mh10_regime': ['equal', 'posN'],
        'chase_v8_pos2_equal_atr_tp6_sl15_mh18': ['equal', 'posN'],
        'chase_v9_pos2_equal_atr_tp6_sl15_mh18_score12': ['equal', 'posN'],
    },
}


def test_scan_is_not_vacuous() -> None:
    """反空转: 扫不到足够多的 preset ⇒ 下面的相等断言全是空的 (§13.147 的教训)。"""
    _, total = _scan()
    assert total >= 80, f"只扫到 {total} 个 preset —— 判据的扫描单位太窄, 这个绿是虚的"


def test_name_value_mismatch_set_is_pinned() -> None:
    """不符集合必须**恰好**等于基线 ⇒ 新增比红, 修好未更新也红 (双向棘轮)。"""
    got, _ = _scan()
    if got != _MISMATCH:
        added = {pk: {n: v for n, v in d.items() if _MISMATCH.get(pk, {}).get(n) != v}
                 for pk, d in got.items()}
        added = {pk: d for pk, d in added.items() if d}
        fixed = {pk: {n: v for n, v in d.items() if got.get(pk, {}).get(n) != v}
                 for pk, d in _MISMATCH.items()}
        fixed = {pk: d for pk, d in fixed.items() if d}
        raise AssertionError(
            f"§13.160: preset **名字与实际取值**的不符集合变了。\n"
            f"  ⛔ 新增/改变的不符 (= 谎话扩散): {added}\n"
            f"  ✅ 已修好但没从清单删 (= 请缩短 `_MISMATCH`): {fixed}\n"
            f"⇒ 修好就把该条从 `_MISMATCH` 删掉; 新增就要么改名字、要么明确写进清单并说明理由。"
        )

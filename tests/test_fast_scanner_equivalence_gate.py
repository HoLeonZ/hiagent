"""§6 守卫:快速扫描器**不得**对"它无法忠实复现的 preset"给出信号集。

## 缺陷(审计 §8 #7d,2026-10-16 复核确认)

`scan_signals_fast.py` 是引擎入场条件的**第二处实现**,它把 E/A/B/C/D 的**参数写死**
在代码里(3e7/3e8、3/10、0.6、`d_mode='strict'`),且**不实现**引擎会评估的
F/G/H/I/J/K 与市场宽度开关;也不评估多腿集成。而模块 docstring 当时宣称
**"结果与策略 100% 等价"**。

实测(75 个 preset):

| 偏离原因 | preset 数 |
|---|---|
| 启用本器未实现的入场开关 | 37 |
| 基础参数被写死(声明值不同) | 71 |
| 其中 `d_mode` | 70 |
| 其中 `below_ratio_60` / `close_ma60_buffer` | 各 70 |
| 其中 `up_streak_low/high` / `liq_low/high` | 各 2 |
| 其中 `a_condition` | 1 |
| **合计结论不可信** | **71 / 75** |

对**实时交易**工具而言,多报的信号就是要下单的票 —— 方向错误比不出结果更糟。
更关键的是:`sl_cooldown_days`(J)与市场宽度是**路径依赖**的,单行扫描**原理上**
无法复现,故这不是"实现漏了",而是"这条路径对它们永远不可能等价"。

## 修法

`_scan_preset` 在 `get_preset` 之后即调用 `_assert_fast_path_equivalent`:
不等价 ⇒ 抛 `FastScannerDivergence`,消息里逐条列出原因并指向
`python -m short_reversal.scan_signals`(构造真实 Phase3V3Strategy)。docstring 的
"100% 等价"声明同时改为精确范围。

## 为什么还要钉住"可信集合非空"

守卫最容易被写成"永远拒绝" —— 那种绿是**真空的绿**(附二十:"规则存在 ≠ 规则被应用"
的镜像:守卫存在 ≠ 它放行过任何东西)。故本文件既断言偏离者必须被拒,也断言
可信集合**恰好**是已知的那一份快照:它变空会让工具彻底无用,它变大则说明有人
扩大了适用范围而未在此处留痕。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from short_reversal.presets import PRESETS  # noqa: E402
from short_reversal.scan_signals_fast import (  # noqa: E402
    FastScannerDivergence,
    _scan_preset,
    fast_path_divergences,
)

#: 当前可信的 preset 快照(2026-10-17:参数化 + F/G/H/I/K 实现后 35 → 68;
#: 余 7 个 = J 冷静期 3 条 + 市场宽度 1 条 + ensemble 3 条,均原理上不可向量化)。
#: 它不是"期望值",而是"已知范围" —— 变更它必须是一次有意识的操作。
KNOWN_FAITHFUL = frozenset({
    "v35_agg_pctchg_04_09",
    "v36_d_converge",
    "v38_a_relaxed",
    "v39_pctchg_03_10",
    "v40_tp_07",
    "v40_tp_08",
    "v42_buf05",
    "v43_ratio03",
    "v44_ratio02_buf07",
    "v45_ratio01_buf10",
    "v46_sl_0002",
    "v50_mh6",
    "v50_slope",
    "v50_slope_strict",
    "v51_weak_1m",
    "v51_weak_3m",
    "v51_weak_6m",
    "v51_weak_combo",
    "v52_dryup_05",
    "v52_dryup_07",
    "v52_dryup_085",
    "v52_dryup_combo",
    "v53_rsi_25",
    "v53_rsi_30",
    "v53_rsi_30_slope",
    "v53_rsi_35",
    "v54_sl_005",
    "v54_sl_01",
    "v54_tp10_sl01",
    "v55_swap_1m",
    "v55_swap_3m",
    "v55_swap_6m",
    "v55_swap_combo",
    "v56_mh_03",
    "v56_mh_07",
    "v56_mh_10",
    "v58_mp_2",
    "v58_mp_3",
    "v61_k",
    "v61_kf",
    "v65_trailing",
    "v67_broad",
    "v68_conviction",
    "v69_donly",
    "v69_widec",
    "v70_lowratio",
    "v70_nob",
    "v71_buf15",
    "v71_liqwide",
    "v72_tp05",
    "v72_tp12",
    "v73_mh10",
    "v73_nosl",
    "v74_pc_hi",
    "v74_pc_lo",
    "v75_broad",
    "v76_cascade",
    "v76_dstrict",
    "v77_b_narrow",
    "v77_e_narrow",
    "v78_dryup",
    "v78_weak",
    "v80_conv",
    "v81_adj",
    "v82_buf12",
    "v82_ratio05",
    "v83_donly",
    "v83_widec",
})

_EMPTY = pd.DataFrame(columns=["thscode", "date", "close", "volume"])


def _raises(preset: str) -> str:
    with pytest.raises(FastScannerDivergence) as ei:
        _scan_preset(preset, "2026-01-05", _EMPTY)
    return str(ei.value)


# ---------------------------------------------------------------------------
# 偏离者必须被拒(两向有牙:删掉闸门 ⇒ 会静默返回空 DataFrame 而不是抛)
# ---------------------------------------------------------------------------


def test_conditions_implemented_in_this_round_are_now_supported() -> None:
    """附四十:F/G/H/I/K 已实现 ⇒ 启用它们的 preset **不再**被拒。

    此前这条断言的是"`v50_slope` 启用 F 会被拒"。F 实现之后(指标走
    `indicators_bt` 的 pandas 对偶、并逐值对拍、再经信号集端到端对拍),该拒绝
    正是应当消失的东西 —— 故改为钉住**新能力**,而不是删掉这条覆盖。
    """
    for preset in ("v50_slope", "v51_weak_1m", "v52_dryup_05", "v53_rsi_30", "v61_k"):
        assert fast_path_divergences(PRESETS[preset]) == [], (
            f"{preset} 又变成不可信了 —— 附四十 实现的条件之一是哪些?"
        )



def _func_node(path: Path, name: str) -> ast.FunctionDef:
    """取 `path` 里名为 `name` 的函数节点(按 AST;改名/搬家会**具名**报出)。"""
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError(f"找不到 `{name}` —— 它被改名或移动了")

def test_filter_signals_reads_declared_params() -> None:
    """§6: 五条件的参数必须**读 preset 声明**,不得再写死。

    此前 `_filter_signals` 把 liq(3e7/3e8)、up_streak(3/10)、below_ratio(0.6) 写死,
    且只实现 `d_mode='strict'`、不看 `close_ma60_buffer` ⇒ 70/75 个 preset 的结论与
    引擎不一致。2026-10-16 改为一律读声明,于是"参数被写死"这一条不再构成不等价理由
    (旧用例断言的正是这个已消失的拒绝类别,故一并替换)。

    **这条是写法级守卫**(按字面量判定),不是行为断言 —— 它的作用是把"又写死回去"
    挡在门口;真正的等价性证据是 `tests/test_fast_scanner_matches_engine.py`
    (在真实数据上与真引擎路径对拍)。
    """
    # ⚠️ 2026-10-22 (附一百八十九 收口后): 原判据用**双边界文本切片**取函数体 ——
    #     body = src[src.index("def _filter_signals("): src.index("def _scan_preset(")]
    # 两个标记任一个**改名或搬家** ⇒ `str.index` 抛 **ValueError**(用例在断言之前就炸);
    # 而断言本身是 `f'cfg.get("{key}"' in body` —— **字面量出现**就算过。
    # ⇒ 取 **AST 节点**,并改断三条真正的性质:① 七个参数都**经 `cfg.get("<key>"…)` 读声明**;
    #   ② 读出来的名字**真的进了比较式**(否则"读了但没用"与写死同效);
    #   ③ 两种非默认 `d_mode` 分支都在。
    fn = _func_node(REPO_ROOT / "short_reversal" / "scan_signals_fast.py", "_filter_signals")
    called = {
        a.args[0].value
        for a in ast.walk(fn)
        if isinstance(a, ast.Call) and isinstance(a.func, ast.Attribute)
        and a.func.attr == "get" and isinstance(a.func.value, ast.Name)
        and a.func.value.id == "cfg" and a.args
        and isinstance(a.args[0], ast.Constant) and isinstance(a.args[0].value, str)
    }
    missing = [k for k in ("liq_low", "liq_high", "up_streak_low", "up_streak_high",
                           "below_ratio_60", "close_ma60_buffer", "d_mode") if k not in called]
    assert not missing, (
        f"§6 VIOLATION: `_filter_signals` 没有经 `cfg.get` 读 preset 的 {missing} —— 又回到写死口径"
    )
    def _has_cmp(op_type: type, name: str) -> bool:
        """存在 `… <op> name` 或 `name <op> …` 这样的比较(运算符也要对)。"""
        for c in ast.walk(fn):
            if not isinstance(c, ast.Compare) or not any(isinstance(o, op_type) for o in c.ops):
                continue
            if any(isinstance(x, ast.Name) and x.id == name
                   for x in [c.left, *c.comparators]):
                return True
        return False

    # 读了必须**真的进比较式**(否则"读了但没用"与写死同效);运算符一并钉住。
    for op_type, var in ((ast.GtE, "liq_low"), (ast.LtE, "liq_high"), (ast.GtE, "us_low"),
                         (ast.LtE, "us_high"), (ast.GtE, "ratio_min")):
        assert _has_cmp(op_type, var), (
            f"§6 VIOLATION: 声明了参数却没有用于条件({op_type.__name__} {var})"
        )
    assert any(
        isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add)
        and isinstance(n.left, ast.Constant) and n.left.value == 1.0
        and isinstance(n.right, ast.Name) and n.right.id == "ma60_buf"
        for n in ast.walk(fn)
    ), "§6 VIOLATION: `1.0 + ma60_buf`(close_ma60_buffer 的用法)不见了"
    strs = {c.value for c in ast.walk(fn) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    for mode in ("d_only", "converge_strict"):
        assert mode in strs, f"§6 VIOLATION: 缺 `d_mode == {mode!r}` 分支(引擎 _all_conditions 的对应分支)"
    # 变量必须真的进了比较式(否则"读了但没用"—— 与写死同效)。
    # 注:`cfg.get(..., 3e7)` 里的字面量是**缺省兜底**,是合法的,故不禁止字面量本身。


def test_ensemble_preset_is_refused() -> None:
    """多腿集成:本器不评估 ensemble_substrategies。"""
    assert "ensemble" in _raises("v63_ensemble").lower()


def test_path_dependent_condition_is_named_as_such() -> None:
    """J(SL 冷静期)是路径依赖的 —— 拒绝理由必须点出它是原理性不可能。"""
    assert "sl_cooldown_days" in _raises("v57_cd_03")


def test_market_breadth_gate_is_refused() -> None:
    """市场宽度闸门同样路径依赖(取决于当日全市场宽度)。"""
    assert "require_market_breadth_bear" in _raises("v66_regime")


# ---------------------------------------------------------------------------
# 可信集合:非空、且恰为已知快照
# ---------------------------------------------------------------------------


def test_faithful_set_is_nonempty() -> None:
    """守卫不得退化成"永远拒绝" —— 那样它的绿是真空的绿。"""
    faithful = {n for n, p in PRESETS.items() if not fast_path_divergences(p)}
    assert faithful, "所有 preset 都被拒 ⇒ 快速扫描器已无任何适用范围"


def test_faithful_set_matches_the_recorded_snapshot() -> None:
    """可信集合变化必须是一次有意识的操作(新增/移除 preset 时更新本快照)。"""
    faithful = {n for n, p in PRESETS.items() if not fast_path_divergences(p)}
    assert faithful == set(KNOWN_FAITHFUL), (
        f"快速扫描器的可信 preset 集合发生变化:\n"
        f"  新增: {sorted(faithful - KNOWN_FAITHFUL)}\n"
        f"  移除: {sorted(KNOWN_FAITHFUL - faithful)}\n"
        "若确有变化,请核对新增者是否真的与引擎条件等价,再更新 KNOWN_FAITHFUL。"
    )


def test_faithful_preset_actually_scans() -> None:
    """正路径:可信 preset 必须真的跑得通(空面板 ⇒ 空信号,不抛)。"""
    sig, st_excluded = _scan_preset("v35_agg_pctchg_04_09", "2026-01-05", _EMPTY)
    assert len(sig) == 0 and st_excluded == []


def test_module_docstring_no_longer_claims_100_percent_equivalence() -> None:
    """§7/§0: 声明的口径必须与实际一致 —— 旧的"100% 等价"是错的。"""
    # ⚠️ 2026-10-22: 原判据用 `src[: src.index('"""', src.index('"""') + 3)]` 取模块 docstring ——
    # 三个引号的**算术**;散文里出现 `"""` 或首行不是 docstring 就会取错。
    # ⇒ 直接用 `ast.get_docstring`(它按 AST 找真正的 docstring 节点)。
    tree = ast.parse((REPO_ROOT / "short_reversal" / "scan_signals_fast.py").read_text(encoding="utf-8"))
    head = ast.get_docstring(tree) or ""
    assert "100% 等价" not in head, (
        "docstring 又宣称与策略 100% 等价 —— 实测 71/75 个 preset 不成立"
    )
    assert "fail-fast" in head, "docstring 必须写明不等价时会 fail-fast"

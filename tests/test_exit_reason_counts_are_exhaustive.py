"""§13.118: **出场原因必须穷尽** —— 代码能发出的每个 reason, metrics 里都要有计数器。

## 修之前
`short_reversal` 的 metrics 只数 `TP` / `SL` / `time`, 而它的 `_close` 还有一个
**第四个原因 `nav_gate_eod`** (NAV 闸门强制平仓)。
⇒ **`tp_count + sl_count + time_count` 可能少于 `trades`** —— 而且**是窗口依赖的**:
实测挑到的那个窗口恰好 0 次 nav_gate ⇒ 三条之和 49 = trades(**只是运气**), 不是构造保证。

**族内不对称**: `chase_up` / `uptrend_pullback` 都有 `eod_count` 覆盖它们的第四个原因 `"eod"`,
**只有 `short_reversal` 缺**。

**方向**: `nav_gate_eod` 是打在 NAV 下限上的**强制平仓**, 基本是亏损腿 ⇒
不数它, 读 `sl_count / trades` 的人会**低估止损占比**。

## 本文件的判据 (AST, 从**代码**推出判据, 不从文档)
1. 从每个引擎的 `_close` / `_close_position` **调用点**取出字面量 reason;
2. 从该引擎的 metrics 构造里取出它**实际计数**的 reason 集合;
3. **前者必须 ⊆ 后者** —— 否则就是"有一个出场原因没人数"。
加一条固定的: `SL` / `TP` / `time` 这三条**每一族都必须数**(它们由 `reason` 变量携带)。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_ENGINES = {
    "chase_up": ("chase_up/portfolio.py", "chase_up/backtest.py", "_close_position"),
    "uptrend_pullback": ("uptrend_pullback/portfolio.py", "uptrend_pullback/backtest.py", "_close_position"),
    "short_reversal": ("short_reversal/replay_strategy_v3.py", "short_reversal/engine.py", "_close"),
}

# 由 `reason` **变量**携带的三条 —— 代码里没有字面量, 但必须被计数。
_VARIABLE_CARRIED = {"SL", "TP", "time"}


def _literal_close_reasons(src: Path, fn_name: str) -> set[str]:
    """调用点传进去的**字面量** reason (字符串常量)。"""
    out: set[str] = set()
    for n in ast.walk(ast.parse(src.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
            if name == fn_name and n.args:
                last = n.args[-1]
                if isinstance(last, ast.Constant) and isinstance(last.value, str):
                    out.add(last.value)
    return out


def _is_exit_reason_cmp(n: ast.AST) -> str | None:
    """该节点是不是 `... ["exit_reason"] == "R"` ⇒ 返回 R。"""
    if isinstance(n, ast.Compare) and len(n.comparators) == 1:
        c = n.comparators[0]
        if isinstance(c, ast.Constant) and isinstance(c.value, str) and "exit_reason" in ast.unparse(n.left):
            return c.value
    return None


def _counted_reasons(src: Path) -> set[str]:
    """**真的被报出来的** reason 计数 —— 必须**同时**认两种写法。

    ⚠️⚠️ **本函数被注入证伪过两次, 而两次都是"判据的单位弱于它声称的性质"。**
    1. **第一版**: 只查"**有没有** `exit_reason == \"R\"` 这个比较式"。
       注入 = **只删 metrics dict 里的键**(计数那一行留着) ⇒ 守卫**仍然绿**。
       ⇒ 正是 §13.79 那一类: **「算了但不报」**。
    2. **第二版 (赋值 + 同名键)**: 只认 short_reversal 的写法
       (`x_count = sum(…); "x_count": x_count`) ⇒ **chase/uptrend 全红** ——
       而它们在**功能上是正确的**, 只是写法不同:
       ```python
       "tp_count": int((trades_df["exit_reason"] == "TP").sum()),   # ← 比较式**内联在 dict 值里**
       ```
       ⇒ **判据的形态假设错了, 把对的东西判成错的。**

    **现判据 (两种写法都认)**: 一个 reason 被计数, 当且仅当有一个 `exit_reason == "R"` 的比较式
    **要么**出现在某个 **dict 字面量的值**里 (chase/uptrend 形态),
    **要么**出现在一条赋值里、而该赋值的目标名是某个 dict 的**键** (short_reversal 形态)。
    """
    tree = ast.parse(src.read_text(encoding="utf-8"))
    # 形态 ①: 比较式直接落在 dict 值里
    inline: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            for v in n.values:
                for c in ast.walk(v):
                    r = _is_exit_reason_cmp(c)
                    if r:
                        inline.add(r)
    # 形态 ②: 先赋值, 再把该名字作为 dict 的**键**报出去
    name_to_reason: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
            for c in ast.walk(n):
                r = _is_exit_reason_cmp(c)
                if r:
                    name_to_reason[n.targets[0].id] = r
    dict_keys = {
        k.value for n in ast.walk(tree) if isinstance(n, ast.Dict)
        for k in n.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }
    via_assign = {r for nm, r in name_to_reason.items() if nm in dict_keys}
    return inline | via_assign


@pytest.mark.parametrize("fam", sorted(_ENGINES))
def test_every_emittable_exit_reason_has_a_counter(fam: str) -> None:
    """★ **代码能发出的每个 reason 都必须被计数** —— 判据来自代码, 不来自文档。"""
    portfolio, metrics, fn_name = _ENGINES[fam]
    emitted = _literal_close_reasons(REPO_ROOT / portfolio, fn_name)
    counted = _counted_reasons(REPO_ROOT / metrics)

    assert counted, f"{fam}: 在 {metrics} 里找不到任何 `exit_reason == \"...\"` 计数 —— 判据的扫描单位不存在"
    missing = emitted - counted
    assert not missing, (
        f"§13.118: {fam} 的 `{fn_name}` 能发出这些**出场原因**, 而 metrics 里**没人数**:\n"
        f"  {sorted(missing)}\n"
        f"⇒ `tp_count + sl_count + time_count (+eod_count)` 会**少于** `trades`, 而这是**窗口依赖**的 ——\n"
        f"   没有 nav_gate 的窗口看起来「对」, 有 nav_gate 的窗口**静默少计**。\n"
        f"已计数: {sorted(counted)}\n修法: 给每个 reason 加一个计数器 (加键是加法 ⇒ 对已有键零漂移)。"
    )


@pytest.mark.parametrize("fam", sorted(_ENGINES))
def test_the_three_variable_carried_reasons_are_counted(fam: str) -> None:
    """`SL` / `TP` / `time` 由 `reason` 变量携带 (代码里没有字面量) ⇒ 单独钉一次。"""
    _portfolio, metrics, _fn = _ENGINES[fam]
    counted = _counted_reasons(REPO_ROOT / metrics)
    missing = _VARIABLE_CARRIED - counted
    assert not missing, (
        f"§13.118: {fam} 的 metrics 没有数 {sorted(missing)} —— 它们由 `reason` 变量携带, "
        f"代码里搜不到字面量, 所以这条**必须单独钉**。"
    )


def test_the_scanner_finds_something_everywhere() -> None:
    """反空转: 三个族的字面量扫描都必须**真的抓到东西**, 否则上面的 ⊆ 是空集比空集。"""
    for fam, (portfolio, _m, fn_name) in _ENGINES.items():
        got = _literal_close_reasons(REPO_ROOT / portfolio, fn_name)
        assert got, (
            f"§13.118: 在 {portfolio} 的 `{fn_name}` 调用点**取不到任何字面量 reason** "
            f"⇒ 本判据对 {fam} 是空转。"
        )

"""§3 PIT Mandate: **全仓**每个 `load_universe()` 调用点都必须传 `asof_date`。

为什么另起一条 (且用 AST 而不是文本/行号)
----------------------------------------
已有两条同类守卫 (`test_pit_universe_call_site_propagation.py` 的
`test_chase_up_all_load_universe_calls_omit_asof_date` /
`test_uptrend_pullback_...`), 但它们有**三个洞**, §13.123 一起抓到:

1. **作用域**: 它们只查 `chase_up/` 与 `uptrend_pullback/` 两个包 ——
   `tools/preset_census.py` 与 `run_sizing_comparison.py`(仓库根)从不在扫描范围内。
   而**恰恰是这两个**在用 post-hoc 股票池建 panel 再喂给引擎。
2. **钉行号**: 它们把调用点写成 `(文件名, 期望行号)` 的硬编码表, 然后
   `if "load_universe(" not in lines[expected_line - 1]: continue` ——
   **文件一挪动就静默跳过**, 于是永远绿。这是 §13.122「死钉桩」的变体:
   守卫还在跑, 但已经不检查任何东西了。
3. **按行判 `asof_date`**: 跨行的调用 (`load_universe(\n  ..., asof_date=...\n)`)
   在第 1 行上看不到 `asof_date`。文本判据对**调用形态**敏感, 而这与要保的性质无关。

本条改用 **AST + 全仓发现式**, 无行号、无白名单(除下面显式列出的例外)。

⚠️ 为什么这件事重要: 引擎本身是 PIT 的 —— `run_backtest` 在 `panel_ind is None`
时才 `load_universe(..., asof_date=start)`。**任何自己预建 panel 再传 `panel_ind=`
的调用方, 等于静默地把引擎的 PIT 换成了自己的 post-hoc 池。** 实测 (§13.123) 影响
可达 ±18pp, 且**方向不一致** —— 它不是"乐观偏差", 是**另一个实验**。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# 只看**产品代码**: tests/ 下的合成夹具故意用 post-hoc 池, 不在此守卫范围。
SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", "tests",
    "results", "build", "dist", ".mypy_cache", ".ruff_cache",
}

# 显式例外 (路径 as posix → 理由)。当前只有一条, 且它是**故意的反事实臂**。
_EXEMPT: dict[str, str] = {
    "tools/attribute_uptrend_selection.py":
        "§13.123 —— 该脚本 `--ab` 那一路**故意**建一个 post-hoc 池, 用来把"
        "「静默绕过 PIT」的**幅度**量出来 (否则就没有对照)。这不是产品路径:"
        "它的输出永远与 PIT 一列并排显示、并标注为非 PIT 对照, 不得单独引用。\n"
        "⚠️ 本例外是**文件级**的, 会连带豁免该文件将来任何一处疏忽 —— "
        "收窄它需要按行豁免, 而按行豁免正是 §13.123(g) 刚批评过的『钉行号』形态。"
        "折中: 下面的 `test_exemptions_carry_reasons` 会断言**该文件确实还有**"
        "非 PIT 调用点, 于是例外一旦过期会自己报出来。",
}

_TARGETS = ("load_universe", "load_universe_data")


def _iter_py() -> list[Path]:
    out = []
    for p in ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts[:-1]):
            continue
        out.append(p)
    return sorted(out)


def _call_name(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _non_pit_call_sites() -> list[str]:
    """返回 ['path:line'] —— 调了 load_universe 却没给出 PIT 锚点的点。"""
    bad: list[str] = []
    for path in _iter_py():
        rel = path.relative_to(ROOT).as_posix()
        if rel in _EXEMPT:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node) not in _TARGETS:
                continue
            # ⚠️ `load_universe(..., **kw)` 里的 `**kw` 在 AST 里 `arg is None` ⇒
            # **判据看不见它里面有没有 asof_date**。实测: 我自己先写成 `**kw`,
            # 于是这条调用**无论如何判都是"非 PIT"** (假红), 而"把 kw 改成永远带
            # asof_date" 也修不掉它 —— 判据与缺陷脱钩了。
            # 处置: 单列一类, 要求**写成显式关键字**, 而不是猜。
            if any(k.arg is None for k in node.keywords):
                bad.append(
                    f"{rel}:{node.lineno} (**kwargs 解包 — 判据无法核对, 请写成显式关键字)"
                )
                continue
            # PIT 的判据 (AST 级, 与跨行/缩进无关):
            #   ① 关键字 asof_date / as_of_date 出现, 或
            #   ② 位置参数 ≥ 4 个 (各实现的 asof_date 都在第 4 位)
            kw = {k.arg for k in node.keywords if k.arg}
            if kw & {"asof_date", "as_of_date"}:
                continue
            if len(node.args) >= 4:
                continue
            bad.append(f"{rel}:{node.lineno}")
    return bad


def test_every_load_universe_call_site_is_pit() -> None:
    bad = _non_pit_call_sites()
    assert not bad, (
        "§3 PIT Mandate: 下列调用点建股票池时**没有给出时点锚点** ⇒ 拿到的是\n"
        "post-hoc 全集 (survivorship-biased)。若该调用方还要把 panel 传给\n"
        "`run_backtest(..., panel_ind=...)`, 那等于**静默绕过**引擎自己的 PIT 加载。\n"
        "  " + "\n  ".join(bad) + "\n"
        "修法: 传 `asof_date=<窗口起点>`; 若确属有意, 加进本文件 `_EXEMPT` 并写明理由。"
    )


def test_guard_scope_covers_every_top_level_that_calls_it() -> None:
    """反向: 判据必须**看得见全仓** —— 只扫两个包的旧守卫正是漏掉 tools/ 的原因。

    ⚠️ 本断言的第一版是 `len(seen) >= 3` **加**一句 `"tools" in seen or "(根)" in seen`。
    注入 (把 `tools` 塞进 SKIP_DIRS) **打不响** —— 因为那是个 **or**:
    仓库根的 `run_sizing_comparison.py` 已经贡献了 `"(根)"`, 于是"藏掉一整个包"
    照样通过。**"注入不响"又一次是判据的形态问题, 不是守卫有牙。**
    现改为: **独立地** (完全不套 SKIP_DIRS) 扫一遍真值, 要求覆盖 `seen` ⊇ 真值 − {tests}。
    藏掉任何一个含调用点的顶层包 ⇒ 红。
    """
    truth: set[str] = set()
    for path in ROOT.rglob("*.py"):
        parts = path.relative_to(ROOT).parts
        if any(p in {".git", ".venv", "venv", "__pycache__", "node_modules"} for p in parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        if any(
            isinstance(n, ast.Call) and _call_name(n) in _TARGETS
            for n in ast.walk(tree)
        ):
            truth.add(parts[0] if len(parts) > 1 else "(根)")
    truth.discard("tests")          # tests/ 是显式豁免的范围

    seen: set[str] = set()
    for path in _iter_py():
        rel = path.relative_to(ROOT)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        if any(
            isinstance(n, ast.Call) and _call_name(n) in _TARGETS
            for n in ast.walk(tree)
        ):
            seen.add(rel.parts[0] if len(rel.parts) > 1 else "(根)")

    missing = truth - seen
    assert not missing, (
        f"扫描范围漏掉了这些含调用点的顶层位置: {sorted(missing)}\n"
        f"  (真值 {sorted(truth)} / 实际 {sorted(seen)})\n"
        f"  这正是 §13.123 的成因: 旧守卫只扫两个包, 于是 tools/ 里的 post-hoc 池\n"
        f"  长期无人过问。放宽 `SKIP_DIRS` 前请先想清楚为什么。"
    )
    assert truth, "真值为空 —— 判据本身没在扫任何东西 (假绿)"


def test_exemptions_carry_reasons() -> None:
    """例外必须①有理由 ②文件仍在 ③**仍然确实需要** (否则是陈旧白名单)。"""
    for k, v in _EXEMPT.items():
        assert v and len(v) > 20, f"例外 {k} 没写清理由"
        assert (ROOT / k).exists(), f"例外 {k} 指向的文件不存在 (陈旧条目)"

    # ③ 陈旧的例外 = 一条无声的豁免: 文件里其实已经没有非 PIT 调用点了,
    # 却还被整个文件地豁免着 —— 将来那处疏忽会被它挡住。
    still_bad: set[str] = set()
    saved = dict(_EXEMPT)
    _EXEMPT.clear()
    try:
        for site in _non_pit_call_sites():
            still_bad.add(site.split(":")[0])
    finally:
        _EXEMPT.update(saved)
    for k in saved:
        assert k in still_bad, (
            f"例外 {k} 已过期: 该文件里**不再有**非 PIT 调用点, 请从 `_EXEMPT` 删掉 —— "
            f"留下它等于给这个文件一个无声的永久豁免。"
        )


if __name__ == "__main__":  # pragma: no cover - 便于手动普查
    for s in _non_pit_call_sites():
        print(s)
    raise SystemExit(0)

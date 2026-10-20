"""附八十一 —— 生产模块**不得引用未定义的名字**(潜在 `NameError`)—— 由普查工具当门禁。

## 起因(两条实缺陷,都是"从未被执行"的代码)

1. `short_reversal/walkforward.py` 的 §5 DSR 段调用 `get_preset(...)`,而该模块**没有 import 它**
   (引入调用的是 `4acfc2e`,加了调用没加 import;姊妹脚本 `wf_v*_focused.py` 都 import 了)。
   ⇒ **那段一执行就 NameError**,连它后面的 `--out` 落盘也永远走不到。
   顺带一个后果:**附六十 对那段的 T 口径分析,分析的是死代码**。
2. `cycle_price_action/replay_broker.py::_fee()` 在 `atr_slip_scale > 0` 的分支里调用
   `effective_slippage(...)`,同样**没有 import** ⇒ 一旦打开 ATR 滑点(§4 原则上有此要求,
   现为待决口径:全库 preset 的该值都是 0),broker 会在**第一笔成交**上 NameError。
3. `short_reversal/wf_v56_focused.py` 的摘要 f-string 打印裸名 `{n_trials}`,而它从未绑定
   (与其他 wf_* 不同:那些打印的是表达式)⇒ 摘要一打印就 NameError,脚本跑不完。

**共同点**:这些代码路径**从未被执行**,所以既不会被套件发现(这些脚本不进套件),
也不会在人工阅读时显形 —— 它们只在**真跑一次**的时候才崩。

## 为什么可以当门禁

普查工具 `tests/_census_undefined_names.py` 的判据保守(宁少报不多报):只有**完全没有绑定**的
名字才报告(导入名 / 模块级赋值 / 函数内绑定 / builtins 都算已定义;属性名不计)。
实测全库**只有上面 3 处**,全部是真缺陷、全部已修 ⇒ **0 命中**。
已知漏报(工具 docstring 里写明):动态导入、`globals()`、星号导入(本仓库无)。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _census():
    spec = importlib.util.spec_from_file_location(
        "census_undefined_names", REPO_ROOT / "tests" / "_census_undefined_names.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_production_module_references_an_undefined_name() -> None:
    """生产模块(排除 tests/)里不得有"引用了未定义名字"的函数。"""
    mod = _census()
    hits: list[str] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts or "tests" in path.relative_to(REPO_ROOT).parts:
            continue
        for fn, ln, name in mod.find_undefined_names(path):
            hits.append(f"{path.relative_to(REPO_ROOT)}:{ln} {fn}() -> {name!r}")
    assert not hits, (
        "§0: 以下位置引用了**未定义的名字**(执行到就会 NameError):\n  "
        + "\n  ".join(hits)
    )


def test_the_gate_has_teeth(tmp_path: Path) -> None:
    """**牙齿**:种一个真形状必须被认出来;种一个合法形状不得误报。

    (没有这条,"0 命中"就无法区分"代码干净"与"检查器坏了" —— 本会话里
     已经因为"检查器坏了"栽过不止一次,而探针是唯一可靠的区分手段。)
    """
    mod = _census()
    bad = tmp_path / "bad.py"
    bad.write_text(
        "def f():\n    return not_imported_anywhere(1)\n", encoding="utf-8"
    )
    hits = mod.find_undefined_names(bad)
    assert any(name == "not_imported_anywhere" for _, _, name in hits), f"没认出来:{hits}"

    good = tmp_path / "good.py"
    good.write_text(
        "import math\n"
        "K = 3\n"
        "def f(x, y=1):\n"
        "    for i in range(K):\n"
        "        x += math.sqrt(i) + y\n"
        "    with open(__file__) as fh:\n"
        "        y = len(fh.read())\n"
        "    return x + y\n",
        encoding="utf-8",
    )
    assert mod.find_undefined_names(good) == [], "合法形状被误报"

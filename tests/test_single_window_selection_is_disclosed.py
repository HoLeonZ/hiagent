"""附九十六 —— 单一窗口选优**必须自己说清楚**(§5);补上 附十七 只做了 2/9 的那一半。

## 缺陷(实测)

附十七 修过一件事:`chase_up/sweep.py` 与 `sweep_all.py` 在**单一窗口**上给一批配置排序并报
DSR,却**不声明这是样本内选择** —— 读者会把「挑出来的最好」当成「样本外验证过的最好」。
处置:两个脚本各加一段 in-sample 声明,并**指名**滚动窗口版本。

**但那次只覆盖了看到的那两个。** 实测全库:

| | 数 |
|---|---|
| 调用 `deflated_sharpe_ratio(` 的引擎脚本 | 28 |
| 其中含窗口遍历(真 WFV)⇒ 本就要不得声明 | 19 |
| **单窗选优 ⇒ 必须声明** | **9** |
| 其中**当时没有声明**的 | **7**(6 个 uptrend sweep + `short_reversal/grid_runner.py`) |

⇒ 与 附八十五(`walkforward.py` 落单)、附九十(同一句假声明在 6 处原样留着)
**是同一个形态**:修复只覆盖"我这次看到的那一份"。

## 判据

**推导,不手抄名单**:

* 家族 = 四个引擎包里**调用** `deflated_sharpe_ratio(` 的脚本
  (注意是**调用**不是**导入** —— `cycle_price_action/walkforward.py` 是个 19 行的再导出 shim,
  只 import 不调用,把它算进来会让家族的边界错位);
* 其中**含窗口遍历**(`windows` / `WINDOWS`,不分大小写)的是真 WFV ⇒ 免声明;
* 其余 = 单窗选优 ⇒ **必须**出现 `in-sample`(或`样本内`)字样。

**为什么用"有没有窗口遍历"而不是"有没有模块级 START/END"**:`chase_up/sweep.py` 的窗口来自
**CLI 参数**(`args.start`),没有模块常量,但它同样是单窗选优。按"有没有窗"划 PID 更贴语义。

## 两向覆盖

* **非空转**:必须至少找到 5 个"需要声明"的脚本 —— 判据坏了会掉到 0,而不是"看起来很干净";
* **牙齿**:种一个"调 DSR、无窗口遍历、无声明"的脚本必须被认出;
  种一个"有窗口遍历"的必须免检(不得误报)。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINES = ("chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action")

_DSR_CALL = "deflated_sharpe_ratio("
_WINDOWS = re.compile(r"\bwindows\b", re.I)
_DECLARED = re.compile(r"in-sample|样本内")


def needs_in_sample_disclosure(src: str) -> bool:
    """该脚本源码是否**应该**含 in-sample 声明(纯函数,便于种值测试)。"""
    if _DSR_CALL not in src:
        return False                 # 不报 DSR ⇒ 不适用(且**导入**不算,**调用**才算)
    if _WINDOWS.search(src):
        return False                 # 有窗口遍历 ⇒ 真 WFV ⇒ 免声明
    return True


def scripts_needing_disclosure() -> list[Path]:
    out: list[Path] = []
    for eng in ENGINES:
        for p in sorted((REPO_ROOT / eng).glob("*.py")):
            if needs_in_sample_disclosure(p.read_text(encoding="utf-8")):
                out.append(p)
    return out


def test_single_window_selection_is_disclosed() -> None:
    """§5:单窗选优的脚本必须声明"这是样本内选择"。"""
    bad = [str(p.relative_to(REPO_ROOT)) for p in scripts_needing_disclosure()
           if not _DECLARED.search(p.read_text(encoding="utf-8"))]
    assert not bad, (
        "§5 VIOLATION: 以下脚本在**单一窗口**上选优并报 DSR,却没有声明这是样本内选择 —— "
        "读者会把「挑出来的最好」当成「样本外验证过的最好」:\n  " + "\n  ".join(bad)
    )


def test_the_disclosure_names_a_walk_forward_sibling() -> None:
    """声明必须**指名**本仓库已有的滚动窗口版本 —— 否则读者不知道该往哪走。

    (与 `test_chase_up_sweep_discloses_in_sample.py` 里那条同型;那条只管 chase 的两个,
     本条覆盖全部 9 个。)
    """
    import re as _re

    bad = []
    for p in scripts_needing_disclosure():
        src = p.read_text(encoding="utf-8")
        # 声明块里必须出现一个"walk-forward 家族"的文件名
        if not _re.search(r"(wf_sweep_all|wfv_eval|walkforward)\.py", src):
            bad.append(str(p.relative_to(REPO_ROOT)))
    assert not bad, (
        "§5: 以下脚本有 in-sample 声明,却**没有指名**滚动窗口版本:\n  " + "\n  ".join(bad)
    )


def test_the_rule_is_not_vacuous() -> None:
    """**非空转**:必须至少找到 5 个"需要声明"的脚本。

    (判据坏了会掉到 0 —— 那时上一条恒真,看起来像"代码干净"。)
    """
    n = len(scripts_needing_disclosure())
    assert n >= 5, f"只找到 {n} 个需要声明的脚本 —— 判据可能已坏死"


def test_the_rule_has_teeth() -> None:
    """**牙齿**:三种形状各判一次。"""
    # ① 调 DSR + 无窗口遍历 + 无声明 ⇒ 需要声明
    assert needs_in_sample_disclosure('x = deflated_sharpe_ratio(a, b)\n')
    # ② 同上但**有**窗口遍历 ⇒ 免声明
    assert not needs_in_sample_disclosure('for s, e in WINDOWS:\n    deflated_sharpe_ratio(a, b)\n')
    # ③ 只 import、不调用 ⇒ 不适用(cycle_price_action/walkforward.py 那种再导出 shim)
    assert not needs_in_sample_disclosure(
        'from dna_stats.deflated import deflated_sharpe_ratio  # noqa: F401\n'
    )


@pytest.mark.parametrize("rel", [
    "chase_up/sweep.py",
    "uptrend_pullback/sweep_v33_long_v6.py",
    "short_reversal/grid_runner.py",
])
def test_known_single_window_scripts_are_in_the_family(rel: str) -> None:
    """三个**已知**的单窗脚本必须在家族里 —— 钉住判据的边界别往回收。

    (`chase_up/sweep.py` 的窗口来自 CLI 参数、没有模块常量;若哪天判据退化成
     "看有没有模块级 START/END",它会静默掉出家族。)
    """
    assert (REPO_ROOT / rel) in scripts_needing_disclosure(), f"{rel} 掉出了需要声明的家族"

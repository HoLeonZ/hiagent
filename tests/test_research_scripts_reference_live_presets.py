"""§5/§6 守卫:研究脚本引用的 preset 必须**仍然存在**。

**发现**(audit 2026-10-15):short_reversal 的 preset 列表在历史迭代中被大幅裁剪
(现在 75 个),但下游的研究脚本仍在引用被删掉的 preset 名。这些脚本在运行第一行就
`SystemExit("preset ... 不在 PRESETS")` —— 它们**跑不起来**:

  `wf_v34_focused.py` → `v34_mainboard_pctchg_tight`(v34 系列已全部不存在)
  `wf_v37_focused.py` → `v37_liq_3e7_5e8`       (v37 系列已全部不存在)
  `wf_v39_focused.py` → `v39_pctchg_04_09`      (只剩 v39_pctchg_03_10)
  `wf_v41_focused.py` → `v41_pctchg_04_10`      (v41 系列已全部不存在)

**为什么值得一条守卫**:这类失效是**静默积累**的 —— 删 preset 时不会有任何东西提示
"有 4 个脚本在引用它"。而它们正是 §5 的执行层(DSR / WFV / n_trials 都在这些脚本里),
跑不起来就等于那一段纪律**没有任何执行者**。

**如何处置这 4 个**:我没有改它们 —— 被删的 preset 没有留下可推断的重命名映射
(v34/v37/v41 系列**一个都不剩**),把名字改成某个"看起来像"的 preset 就是**编造
实验记录**。故采用"登记债务"的处置:
  · 本文件的 `KNOWN_DEAD_REFERENCES` 是**登记表**;
  · 实际集合必须**等于**登记表 —— 新增失效会失败(被抓住),修好一个而不同步删除登记项
    也会失败(防止登记表变成永久借口)。
"""
from __future__ import annotations

import glob
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

#: 已知失效引用(债务登记)。修好其中一个 → 必须同时从这里删掉。
KNOWN_DEAD_REFERENCES = {
    "short_reversal/wf_v34_focused.py": "v34_mainboard_pctchg_tight",
    "short_reversal/wf_v37_focused.py": "v37_liq_3e7_5e8",
    "short_reversal/wf_v39_focused.py": "v39_pctchg_04_09",
    "short_reversal/wf_v41_focused.py": "v41_pctchg_04_10",
}

#: 研究脚本(sweep / walk-forward / grid)。§5 的执行层就在这些文件里。
SCRIPT_GLOBS = {
    "short_reversal": ("short_reversal/wf_*.py", "short_reversal/grid*.py",
                       "short_reversal/sweep*.py"),
    "chase_up": ("chase_up/sweep*.py", "chase_up/wf_*.py"),
    "uptrend_pullback": ("uptrend_pullback/sweep*.py",),
    "cycle_price_action": ("cycle_price_action/sweep*.py",),
}

#: 显式把 preset 名交给回测/取 preset 的调用,以及模块级常量赋值。
_CALL = re.compile(r'(?:run_one|run_backtest_v3|run_backtest|get_preset)\(\s*"([^"]+)"')
_ASSIGN = re.compile(r'^\s*(?:PRESET|preset|TARGET_PRESET)\s*=\s*"([^"]+)"', re.M)


def _preset_names(engine: str) -> set[str]:
    if engine == "short_reversal":
        from short_reversal.presets import PRESETS
    elif engine == "chase_up":
        from chase_up.presets import PRESETS
    elif engine == "uptrend_pullback":
        from uptrend_pullback.presets import PRESETS
    else:
        from cycle_price_action.presets import PRESET_V1
        return {"PRESET_V1", *PRESET_V1}
    return set(PRESETS)


def _references() -> dict[str, set[str]]:
    """{脚本相对路径: 它引用但不存在的 preset 名集合}(只含确实失效的)。"""
    out: dict[str, set[str]] = {}
    for engine, patterns in SCRIPT_GLOBS.items():
        known = _preset_names(engine)
        for pattern in patterns:
            for raw in sorted(glob.glob(str(REPO_ROOT / pattern))):
                path = Path(raw)
                src = path.read_text(encoding="utf-8")
                cited = set(_CALL.findall(src)) | set(_ASSIGN.findall(src))
                dead = {c for c in cited if c not in known}
                if dead:
                    out[str(path.relative_to(REPO_ROOT))] = dead
    return out


def test_no_new_dead_preset_references() -> None:
    """研究脚本不得引用已不存在的 preset —— 那会让脚本在启动即退出。"""
    actual = {f: sorted(v) for f, v in _references().items()}
    registered = {f: [n] for f, n in KNOWN_DEAD_REFERENCES.items()}
    new = {f: v for f, v in actual.items() if f not in registered}
    assert not new, (
        "§5 VIOLATION: 以下研究脚本引用了**不存在**的 preset(运行即 SystemExit):\n  "
        + "\n  ".join(f"{f} -> {v}" for f, v in new.items())
        + "\n修正脚本,或(若确属历史债务)登记到 KNOWN_DEAD_REFERENCES 并说明原因。"
    )


def test_registered_debt_is_still_debt() -> None:
    """登记表必须**跟着现实走**:修好一个却不同步删登记项 → 失败。

    这条防的是"登记表变成永久借口":它应当只会变短。
    """
    actual = _references()
    stale = []
    for f, name in KNOWN_DEAD_REFERENCES.items():
        if name not in actual.get(f, set()):
            stale.append(f"{f} -> {name}")
    assert not stale, (
        "以下登记项已不再失效(preset 已恢复或脚本已改用現存 preset)—— "
        f"请从 KNOWN_DEAD_REFERENCES 删除:{stale}"
    )


def test_research_scripts_are_actually_scanned() -> None:
    """自检:扫描面不能为空 —— 否则前两条会空转通过。"""
    total = sum(len(glob.glob(str(REPO_ROOT / p)))
                for pats in SCRIPT_GLOBS.values() for p in pats)
    assert total >= 20, f"研究脚本扫描面异常小({total} 个文件)—— 守卫可能已空转"


def test_registered_scripts_still_exist() -> None:
    """登记表引用的脚本不能凭空消失(否则登记的是幽灵)。"""
    missing = [f for f in KNOWN_DEAD_REFERENCES if not (REPO_ROOT / f).exists()]
    assert not missing, f"登记表引用了不存在的脚本:{missing}"


@pytest.mark.parametrize("script,expected", sorted(KNOWN_DEAD_REFERENCES.items()))
def test_such_a_script_fails_loudly_rather_than_silently(script: str, expected: str) -> None:
    """这些脚本虽然失效,但必须**响亮地**失败(而不是跑出个空结果)。

    它们已经是 `SystemExit("preset ... 不在 PRESETS")` —— 本用例把这一点钉住:
    若将来有人把它改成"找不到就跳过",失效就又会变成静默的。
    """
    src = (REPO_ROOT / script).read_text(encoding="utf-8")
    assert "不在 PRESETS" in src or "SystemExit" in src, (
        f"{script} 引用失效 preset 却不再响亮失败 —— "
        "静默跳过会让「脚本没跑」看起来像「脚本跑了且没结论」。"
    )


# ---------------------------------------------------------------------------
# §5: DSR 的输入必须是**年化 Sharpe**,不能是收益率
# ---------------------------------------------------------------------------
def test_no_script_feeds_a_return_percentage_as_observed_sharpe() -> None:
    """§5: `observed_sharpe` 的单位契约是**年化 Sharpe**。

    `chase_up/wf_sweep_all.py` 原先把 `median_return_pct / 100`(窗口中位**总收益**)
    当成 Sharpe 传进 DSR。后果不是数值误差而是**结论错误**:收益率(0.1~1)比典型
    Sharpe 量级低一到两个数量级,实测同一批数字下
        12% 当 Sharpe=0.12 → DSR=0.034, p=0.966("毫无优势")
        真 Sharpe=1.20    → DSR=0.228, p=0.772
    也就是说,它会把**有边际优势**的结论稳定地印成"无优势",而它照样被当作显著性
    结果打印出来。

    检查方式:对每个调用 DSR 的研究脚本,取其调用点前 20 行的**非注释**代码,
    断言其中不出现 `return_pct` 之类的收益率来源。
    """
    offenders = []
    for engine, patterns in SCRIPT_GLOBS.items():
        for pattern in patterns:
            for raw in sorted(glob.glob(str(REPO_ROOT / pattern))):
                path = Path(raw)
                lines = path.read_text(encoding="utf-8").splitlines()
                for i, line in enumerate(lines):
                    if "deflated_sharpe_ratio(" not in line:
                        continue
                    window = [
                        l for l in lines[max(0, i - 20): i]
                        if not l.strip().startswith("#")
                    ]
                    if any("return_pct" in l for l in window):
                        offenders.append(
                            f"{path.relative_to(REPO_ROOT)}:{i + 1}"
                        )
    assert not offenders, (
        "§5 VIOLATION: 以下调用点疑似把**收益率**当作 `observed_sharpe` 传入 DSR"
        f"(DSR 契约要求年化 Sharpe):{offenders}"
    )

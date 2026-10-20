"""附九十五 —— CLAUDE.md §7(工件卫生)的两条机械不变量。

## §7 说什么

> * **Results Stay Local**: `results/`, trades.csv, metrics JSON, and generated reports
>   MUST remain gitignored. Committing them is a contract violation — **a fresh clone
>   must contain zero historical performance claims.**
> * **No Numbers in Docs**: READMEs and design docs MUST NOT embed historical metrics
>   (CAGR/Sharpe/win-rate tables). They document *how to reproduce*, never *what was
>   once observed*.

本节实测(附九十五):**两条都做到了** —— 但**没有任何守卫**。本文件把"做到了"钉成"不许退化"。

## 实测状态(建守卫时的事实)

* `.gitignore` 有一整段专门讲这件事(含"上面只忽略 `results/` 目录,于是散落在别处的同名产物
  仍然可以被提交"的自陈),模式覆盖 `trades.csv` / `*_trades.csv` 等;
* `git ls-files` 里**没有任何**结果类产物;唯一沾边的是
  `cycle_price_action/results/.gitkeep`(占位)与 `short_reversal/docs/d_condition_explained.html`
  (**文档**,`.gitignore` 的注释里点名说明过);
* 全库 5 个 markdown(**含** `chase_up/README.md`)**没有任何一行**同时出现"指标名 + 数值"。

## 一处**张力**,如实记下而不是悄悄绕过

`docs/audits/strategy-discipline-audit.md`(审计报告,在 `audit/*` 分支上)**满是数字**
—— 那正是本审计的证据(如 "CAGR 14.66% → 87.12%")。

它与 §7 并不冲突,理由是 §7 自己的那句: **"Any number that cannot be regenerated from
current code plus one command is treated as stale and deleted."** 审计报告里的每个数都附了
**复现方式**(哪条命令、哪个脚本),所以它们是**可再生的证据**,不是"曾经观测到的成绩"。

但**边界要靠人守**:若哪天把那份报告并进 `docs/`(或任何被本守卫当作"设计文档"的路径),
本守卫会红 —— 而那应该是**有意识的决定**,不是顺手带过来的。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: §7 点名的产物类:这些东西**不许被 git 跟踪**。
ARTIFACT_PATTERNS = (
    "chase_up/results/", "uptrend_pullback/results/",
    "short_reversal/results/", "cycle_price_action/results/", "results/",
    "trades.csv", "*_trades.csv",
)

#: `results/` 下的占位文件是允许的(空目录进不了 git)。
_ALLOWED_TRACKED = {"cycle_price_action/results/.gitkeep"}

_METRIC = re.compile(r"CAGR|Sharpe|胜率|回撤|win.?rate|max.?dd|夏普", re.I)
_VALUE = re.compile(r"-?\d+\.\d+")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT,
                          capture_output=True, text=True, check=True).stdout


def tracked_artifacts() -> list[str]:
    """被 git 跟踪、且落在 §7 产物模式里的文件(排除占位与已登记的文档例外)。"""
    files = _git("ls-files").splitlines()
    out = []
    for f in files:
        if f in _ALLOWED_TRACKED:
            continue
        if f.endswith(".gitkeep"):
            continue
        if any(f == p.rstrip("/") or f.startswith(p) or Path(f).match(p)
               for p in ARTIFACT_PATTERNS):
            out.append(f)
    return out


def docs_with_metric_values() -> list[str]:
    """README / 设计文档里"指标名 + 数值"同现的行。

    范围:**仓库根的 `*.md` 与 `docs/` 下的 `*.md`**(§7 说的就是 "READMEs and design docs")。
    `CLAUDE.md` 是**规范**,不是设计文档,且它引 §2 时出现的数字是政策常量 —— 故不在范围内。
    """
    out: list[str] = []
    cands = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").glob("*.md"))]
    for p in cands:
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if _METRIC.search(line) and _VALUE.search(line):
                out.append(f"{p.relative_to(REPO_ROOT)}:{i}  {line.strip()[:90]}")
    return out


def test_no_result_artifact_is_tracked_by_git() -> None:
    """§7:结果类产物永不入库 —— 新克隆必须**零历史绩效**。"""
    bad = tracked_artifacts()
    assert not bad, (
        "§7 VIOLATION: 以下结果类产物被 git 跟踪(新克隆会带上历史绩效):\n  "
        + "\n  ".join(bad)
        + "\n把它们从索引里移除并补进 .gitignore。"
    )


def test_the_artifact_patterns_are_actually_ignored() -> None:
    """§7 点名的每一类产物都必须**真的**被 .gitignore 覆盖。

    (只测"当前没有被跟踪"不够 —— 一个**新**产物明天就可能被提交;
     这一条钉的是"规则还在"。)
    """
    probes = {
        "chase_up/results/x.json": "chase_up/results/",
        "results/x.csv": "results/",
        "trades.csv": "trades.csv",
        "chase_up/results/v1_trades.csv": "*_trades.csv",
    }
    not_ignored = []
    for probe, why in probes.items():
        r = subprocess.run(["git", "check-ignore", "-q", probe], cwd=REPO_ROOT)
        if r.returncode != 0:
            not_ignored.append(f"{probe}(应由 {why} 覆盖)")
    assert not not_ignored, (
        "§7: 以下产物**不会被忽略**(明天提交就会被带进库):\n  " + "\n  ".join(not_ignored)
    )


def test_design_docs_embed_no_metric_values() -> None:
    """§7:README / 设计文档只写**怎么复现**,不写**曾经观测到什么**。"""
    bad = docs_with_metric_values()
    assert not bad, (
        "§7 VIOLATION: 以下文档行把**指标名**与**数值**写在一起:\n  "
        + "\n  ".join(bad)
        + "\n文档要写明复现命令,数字留给产物(gitignored)。"
    )


def test_the_doc_scanner_is_not_vacuous() -> None:
    """**非空转**:扫描面必须真的扫到了文档 —— 否则上面那条会恒真。

    (本会话已多次栽在"判据坏了看起来像代码干净"上;这里钉住"至少扫到了 2 个文档"。)
    """
    cands = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").glob("*.md"))]
    found = [p for p in cands if p.exists()]
    assert len(found) >= 2, (
        f"只扫到 {len(found)} 个文档({[p.name for p in found]})—— 扫描面可能已失效"
    )


def test_the_doc_scanner_has_teeth(tmp_path, monkeypatch) -> None:
    """**牙齿**:种一行"指标名 + 数值"必须被认出;只写指标名(无数值)不得误报。"""
    bad_doc = tmp_path / "bad.md"
    bad_doc.write_text("本策略 Sharpe 1.42,年化 23.5%,回撤 8.9%。\n", encoding="utf-8")
    good_doc = tmp_path / "good.md"
    good_doc.write_text(
        "本策略的 Sharpe 与 CAGR 由 `python3 -m ...` 一条命令复现,本文不写数值。\n",
        encoding="utf-8",
    )
    assert _METRIC.search(bad_doc.read_text(encoding="utf-8").splitlines()[0]) and \
           _VALUE.search(bad_doc.read_text(encoding="utf-8").splitlines()[0]), "夹具失效"
    assert not _VALUE.search(good_doc.read_text(encoding="utf-8").splitlines()[0]), "夹具失效"

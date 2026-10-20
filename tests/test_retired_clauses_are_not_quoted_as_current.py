"""附九十八 —— 被标准**替换掉**的条款,不许再被当作现行条款引用。

## 起因

附九十七 修了 §4 的 TP/SL 一条 —— 它在提交 `2260ba1` 里被**整句换掉**,而两个测试至今把
旧句当作 "CLAUDE.md §4 (verbatim)" 强制。

**同一提交替换的不止一条。** 把那次 diff 里被删的句子都提出来后,实测:

| 被删的旧条款 | 现行替代 | 仍在引用它的文件 |
|---|---|---|
| `**Atomic Cash Locks:** …` | §2 **Single-Bullet Execution**(其余并发信号**立即丢弃**) | 4 |
| `**All-In Sizing Policy (2026-09-21):** …` | §2 **Strict All-In Sizing Policy** | 3 |
| `**Volume Participation Limit:** … Unfilled quantities must be explicitly canceled or **queued**.` | §4 **… & IOC Handling**:`**Do NOT queue** the remainder` | 3 |
| `**Exit Thresholds (TP/SL):** … document the choice in the preset's compliance header.` | §4 … **relative percentages, NEVER absolute** | 1(附九十七 已改成带出处) |

⇒ 附九十七 只修了**一条**,而这是**同一提交的四条**。本文件把这一类做成**可推导的登记表**。

## 判据

`RETIRED_CLAUSES` 每项 = `(被删的原句片段, 删它的提交, 现行替代)`。三条断言:

1. **该片段必须确实不在现行的 CLAUDE.md 里**(否则登记项本身就错了);
2. **该片段必须确实出现在那个提交的 diff 里**(否则出处是编的);
3. **没有任何源码文件把退休片段当作现行标准引用** ——
   判据是"同文件里出现该片段 **且** 带 `verbatim` 之类的"当作原文"标记,
   **且没有**写明它已被替换(提交号 / "已删除"/"已被…替换")。

第 ③ 条刻意**允许带出处的引用** —— 一段"病史"必须能贴出原话才有用
(附九十七 里那条判据当场抓到过我自己的病史引用)。

## 只改引文,不改断言(实测的结论)

九个引用点**逐处读过**:过时的**只在文档字符串 / 注释**里;
它们的**断言**至今仍然有效(容量上限那几个测的是 `volume_cap_fill` 的取整与不整除绕过;
Atomic Cash 那几个测的是"扣现金有守卫")。故本轮的修法是**把引文换成现行文本并注明出处**,
**不动任何断言** —— 若某处断言的是被替换掉的**行为**,那要单独立案(本轮未发现)。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDEMD = REPO_ROOT / "CLAUDE.md"

#: 被删的原句片段 → (删它的提交, 现行替代)
RETIRED_CLAUSES: dict[str, tuple[str, str]] = {
    "Atomic Cash Locks": (
        "2260ba1", "§2 Single-Bullet Execution(其余并发信号 **IMMEDIATELY DISCARDED**)",
    ),
    "All-In Sizing Policy (2026-09-21)": (
        "2260ba1", "§2 Strict All-In Sizing Policy",
    ),
    "Unfilled quantities must be explicitly canceled or queued": (
        "2260ba1", "§4 Volume Participation Limit & IOC Handling:**Do NOT queue**",
    ),
    "document the choice in the preset's compliance header": (
        "2260ba1", "§4 Exit Thresholds …:**relative percentages, NEVER absolute**",
    ),
}

#: 把某处引用**当作现行原文**的标记;出现其一即需附出处。
_AS_CURRENT = ("verbatim", "原文", "(2026-09-21)")

#: 写明"这句已退休"的标记;出现其一即可引用。
_RETIREMENT_NOTED = ("2260ba1", "已删除", "已被删除", "已被替换", "不再", "旧条款")


def _committed_removal(phrase: str, commit: str) -> str:
    """返回该提交的 diff 文本(只看是否出现过这个片段)。"""
    r = subprocess.run(
        ["git", "show", commit, "--", "CLAUDE.md"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    return r.stdout if phrase in r.stdout else ""


def test_registry_only_lists_phrases_absent_from_the_current_standard() -> None:
    """登记为"已退休"的片段,必须**确实不在**现行 CLAUDE.md 里。

    (若标准把某条又加回来了,这一条会红 —— 提醒登记表过期。)
    """
    cur = CLAUDEMD.read_text(encoding="utf-8")
    back = sorted(p for p in RETIRED_CLAUSES if p in cur)
    assert not back, (
        "§0: 以下片段**又出现在现行 CLAUDE.md 里**了 —— 登记表已过期,请重新核对它们是否仍属"
        "「已退休」:\n  " + "\n  ".join(back)
    )


def test_registry_cites_the_commit_that_actually_removed_them() -> None:
    """出处必须是真的:被删片段要真的出现在那个提交的 diff 里。"""
    bad = []
    for phrase, (commit, _replacement) in RETIRED_CLAUSES.items():
        if not _committed_removal(phrase, commit):
            bad.append(f"{phrase!r} 不在 {commit} 的 CLAUDE.md diff 里")
    assert not bad, "§0: 退休登记表的出处不成立:\n  " + "\n  ".join(bad)


def test_no_source_quotes_a_retired_clause_as_the_current_standard() -> None:
    """任何文件都不得把退休条款当作**现行标准**引用;带出处可以。"""
    hits = []
    for p in sorted(REPO_ROOT.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        src = p.read_text(encoding="utf-8")
        for phrase, (commit, _replacement) in RETIRED_CLAUSES.items():
            if phrase not in src:
                continue
            if not any(m in src for m in _AS_CURRENT):
                continue                      # 只是提到概念名,不算"当作原文"
            if any(m in src for m in _RETIREMENT_NOTED) or commit in src:
                continue                      # 写了出处/已退休 ⇒ 允许
            hits.append(f"{p.relative_to(REPO_ROOT)} 引用 {phrase!r}(已由 {commit} 替换)")
    assert not hits, (
        "§0: 以下文件把**已被替换的条款**当作现行标准引用 —— 引文要换成现行文本并注明出处:\n  "
        + "\n  ".join(hits)
    )


def test_the_rule_is_not_vacuous() -> None:
    """**非空转**:登记表不能为空,且现行标准里不能出现任何退休片段。"""
    assert len(RETIRED_CLAUSES) >= 3, "登记表异常小 —— 判据可能已失效"
    cur = CLAUDEMD.read_text(encoding="utf-8")
    assert not any(p in cur for p in RETIRED_CLAUSES)


def test_the_rule_has_teeth(tmp_path) -> None:
    """**牙齿**:三种形状各判一次(纯逻辑,不碰真仓库)。"""
    phrase = "Atomic Cash Locks"
    as_current = f'"""CLAUDE.md §2 (verbatim): "{phrase} …"\n"""\n'
    with_origin = as_current.replace('(verbatim)', "(已由 2260ba1 删除)")
    concept_only = f"# 本引擎不再使用 {phrase} 的顺序锁语义\n"

    def flagged(src: str) -> bool:
        if phrase not in src:
            return False
        if not any(m in src for m in _AS_CURRENT):
            return False
        return not any(m in src for m in _RETIREMENT_NOTED)

    assert flagged(as_current), "当作现行原文引用应当被认出"
    assert not flagged(with_origin), "写了出处却被误报"
    assert not flagged(concept_only), "只提到概念名却被误报"


@pytest.mark.parametrize("rel", [
    "tests/test_volume_cap_4engine.py",
    "tests/test_short_reversal_volume_cap.py",
    "tests/test_volume_cap_low_bar.py",
    "tests/test_atomic_cash_locks_4engine.py",
    "tests/test_all_in_sizing_fraction_preservation.py",
])
def test_known_quoting_sites_are_fixed(rel: str) -> None:
    """**边界钉**:这几个文件引用过退休条款 —— 它们必须带出处(而不是把旧句当原文)。"""
    src = (REPO_ROOT / rel).read_text(encoding="utf-8")
    quotes_retired = any(p in src for p in RETIRED_CLAUSES)
    if quotes_retired:
        assert any(m in src for m in _RETIREMENT_NOTED), (
            f"{rel} 仍把退休条款当作现行原文引用 —— 请注明它已被替换"
        )

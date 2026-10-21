"""审计报告的**状态头**必须与正文一致 —— 防「文首漂移」(本仓库栽过两次的形态)。

背景(实测,2026-10-21):`docs/audits/strategy-discipline-audit.md` 在 §0 之前有一段**手写的**
状态头,它声明两件事:①累计附录条数;②最新增补是哪一条。这两件事**每一批都会被改**,而在今天
之前没有任何东西盯着它们 —— 实测:正文已到 **131** 条时,文首还写着「107 条 / 附一百零七」
(落后 24 条);同一份报告在 `main` 上的副本更是双重脱节(正文 110 条 / 文首 107 条)。

判据两条,都只用**免解析**的形式,不去解中文数目字:
  1. 文首声明的条数 == 正文里带编号 `## 附N` 标题的实际条数;
  2. 文首「最新增补见**附X**」里的 X 是一条**真实存在**的标题,且它就是**最后**那一条。

文档不在本分支时 **skip**(CLAUDE.md §6:缺产物 → 跳过而不是报错)。这份报告只活在文档分支上;
修复分支 `fix/discipline-remediation` 的树里没有它。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_DOC = Path(__file__).resolve().parents[1] / "docs" / "audits" / "strategy-discipline-audit.md"

# 状态头 = 文件开头那段连续的引用块(`>` 行)。落到第一个「非空且非引用」的行即止。
_QUOTE_LINE = re.compile(r"^>")
_COUNT_CLAIM = re.compile(r"累计落地\s*\*\*(\d+)\s*条附录\*\*")
_LATEST_CLAIM = re.compile(r"最新增补见\*\*(附[^*\s]+)\*\*")
# 带编号的附录标题:编号里不含空白/破折号/冒号/括号(那些是无编号标题的分隔符)。
_NUMBERED_HEADING = re.compile(r"^##\s+(附[^\s—–\-:：(（]+)", re.M)


def _document() -> str:
    if not _DOC.is_file():
        pytest.skip(f"审计报告不在本分支({_DOC.name})—— 它只存在于文档分支")
    return _DOC.read_text(encoding="utf-8")


def _status_header(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        if _QUOTE_LINE.match(line):
            lines.append(line)
        elif lines and line.strip():
            break
    return "\n".join(lines)


def test_header_appendix_count_matches_the_body() -> None:
    text = _document()
    header = _status_header(text)
    claimed = _COUNT_CLAIM.search(header)
    assert claimed, "状态头里没有「累计落地 **N 条附录**」这句声明(改口径时本判据要同步改)"
    actual = len(_NUMBERED_HEADING.findall(text))
    assert int(claimed.group(1)) == actual, (
        f"状态头说 {claimed.group(1)} 条附录,而正文里带编号的 `## 附N` 标题有 {actual} 条 —— "
        f"文首漂移了:把状态头更新到 {actual},或写清为什么口径不同"
    )


def test_header_latest_appendix_exists_and_is_the_last_one() -> None:
    text = _document()
    header = _status_header(text)
    claimed = _LATEST_CLAIM.search(header)
    assert claimed, "状态头里没有「最新增补见**附X**」这句声明"
    token = claimed.group(1)
    headings = _NUMBERED_HEADING.findall(text)
    assert headings, "正文里找不到任何带编号的 `## 附N` 标题"
    assert token in headings, f"状态头指着「{token}」,而正文里没有这条编号标题"
    assert headings[-1] == token, (
        f"状态头说最新增补是「{token}」,而正文最后一条是「{headings[-1]}」"
    )

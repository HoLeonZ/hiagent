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


_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_to_int(token: str) -> int:
    """`附一百三十二` → 132(本册编号只用 百/十 两级)。

    (第一版写成"遇到 百/十 就把累计值乘上去",于是 `一百三十二` 得 1030 ——
     已改成按级累加:`section` 收 百/十 那一段,`num` 收当前数字。)
    """
    section = 0
    num = 0
    for char in token.removeprefix("附"):
        if char == "百":
            section += (num or 1) * 100
            num = 0
        elif char == "十":
            section += (num or 1) * 10
            num = 0
        elif char in _CN_DIGITS:
            num = _CN_DIGITS[char]
        else:
            raise ValueError(f"意外的编号字符 {char!r}(在 {token!r} 里)")
    return section + num


def test_appendix_numbering_is_contiguous() -> None:
    """**编号必须连续无洞、无重号** —— 这条是前两条**挡不住**的。

    前两条只查「条数」与「最后一条」:删掉中间一条、再补一条新的 ⇒ **条数与末条都不变**
    ⇒ 门禁照绿,而编号留了个洞(读者会以为「缺的那条被并进别处了」)。
    这里直接钉编号序列本身:它**不可能被散文满足**,也不需要文首配合。
    """
    headings = _NUMBERED_HEADING.findall(_document())
    assert headings, "正文里找不到任何带编号的 `## 附N` 标题"
    numbers = [_cn_to_int(h) for h in headings]

    duplicated = sorted({n for n in numbers if numbers.count(n) > 1})
    assert not duplicated, f"这些附录编号**重复**:{duplicated}"

    missing = sorted(set(range(min(numbers), max(numbers) + 1)) - set(numbers))
    assert not missing, (
        f"附录编号**不连续**,缺号:{missing} —— 删掉一条后请把后面的编号接上"
        f"(或补回被删的那条)。门禁的前两条**看不出**这种情况。"
    )


def test_the_appendix_number_parser_handles_the_forms_this_document_uses() -> None:
    """解析器本身的牙齿:本册用到的写法各测一遍。

    (第一版把 `一百三十二` 解析成 1030 —— 一条**恒不相等**的判据会红得莫名其妙,
     所以解析器自己也要钉。)
    """
    cases = {"附二": 2, "附十": 10, "附十一": 11, "附二十": 20,
             "附一百": 100, "附一百一": 101, "附一百三十二": 132, "附一百四十一": 141}
    wrong = {token: (_cn_to_int(token), expected)
             for token, expected in cases.items() if _cn_to_int(token) != expected}
    assert not wrong, f"编号解析错了(写法: (实得, 应为)):{wrong}"

"""登记册**文首「先读这里」块**是否跟上了最新的那几节 —— **一条弱门禁, 但它防的失效有前科**。

## 为什么有这条 (§13.95 → §13.93)
登记册里有一条**用血写出来的**规则 (Iteration 95):
> **文档的阅读顺序与结论的时间顺序相反, 所以旧节可能比新节更"乐观"。**
> **每次追加都应该回头检查"这条新结论推翻了开头哪一句"。**

而那条规则**第一次被立起来, 正是因为前 90 轮从没做过** —— 结果是文首写着"§4 说可用"
而同文件的 §6.3 说"不可用", 两者共存了很久。
**2026-10-19 又发生了一次同类**: 文首的 §13.13 禁令段落仍写着
「这 4 个**全部被证实定义不同**」, 而 §13.91 已经**明确说过"那太粗"**
(其中 `win_rate_field` 只是**命名差异**、`max_dd` 只有**两档**) —— 且两节都是**同一天**写的。
⇒ 追加了约 30 节之后, 文首**又漂移了**。

## ⚠️ 这条门禁**不能**做什么 (别把它当成了它做不到的事)
它**不检查文首的论断与各节是否矛盾** —— 那需要读懂语义, 机械不了。
它**只**要求: **文首引用到当前的最高小节号**。
> 它的全部作用是**逼作者打开文首** —— 而**真正的"回头检查"发生在那一步**。
> 所以这是一条**仪式性**的门禁: 弱, 但防的失效 (文首静默漂移) 有明确前科。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOG = REPO / "docs" / "strategy_mining_log.md"
HEAD_MARK = "📍 先读这里"


def _head_text() -> str:
    s = LOG.read_text(encoding="utf-8")
    i = s.index(HEAD_MARK)
    j = s.index("\n---\n", i)
    return s[i:j]


def _max_section(prefix: str) -> str | None:
    """全文档里 `### prefix.N` 的最大 N。"""
    s = LOG.read_text(encoding="utf-8")
    pat = re.compile(rf"^###\s+{re.escape(prefix)}\.(\d+)\b", re.M)
    ns = [int(m.group(1)) for m in pat.finditer(s)]
    return f"{prefix}.{max(ns)}" if ns else None


def test_head_block_exists() -> None:
    """反空转: 找不到文首块 ⇒ 下面的断言全是空的。"""
    head = _head_text()
    assert HEAD_MARK in head and len(head) > 200, f"文首块异常短: {len(head)} 字符"


def test_head_block_cites_the_newest_sections() -> None:
    """文首必须**引用到**当前的最高 `§13.N` 与 `§9.N`。

    ⇒ 想加一节而不动文首, 这条会红。**红的时候请真的去读一遍文首, 而不只是补一个号。**
    """
    head = _head_text()
    for prefix in ("13", "9"):
        newest = _max_section(prefix)
        if newest is None:
            continue
        assert f"§{newest}" in head, (
            f"§13.93: 文首「先读这里」**没有引用到当前最高的一节 `§{newest}`**。\n"
            f"⇒ 你刚追加了新结论, 却没有回头检查文首 —— 而那正是本册记过两次的失效\n"
            f"   (Iteration 95: 前 90 轮从没做过, 于是'§4 说可用'与'§6.3 说不可用'共存了很久;\n"
            f"    2026-10-19: 文首仍写'4 个全部定义不同', 而 §13.91 已说'那太粗')。\n"
            f"**请打开文首, 逐句问: 这一条新结论推翻了开头哪一句?** 然后把它引用进去。"
        )


def test_section_headings_are_visible_to_the_scanner() -> None:
    """§13.163(附): 节标题必须用**扫描器看得见**的写法 —— 否则下面那条门禁会静默失明。

    ## 为什么有这条 (§13.163 的实录)
    本文件的判据是一条要求标题以「三个井号 + 节号」开头的正则。我在 §13.156–§13.163 **八节**上写成 `## §13.NNN`
    (两井号 + 一个 §) ⇒ **那八节对整个门禁不可见** —— 门禁一直只要求文首引用到**更早的**那一节,
    于是我那一整段的「文首已同步」绿灯**全是空的**。
    > 判据的**作用域**比它声称的性质窄 —— 同一形状第四次 (§13.147 系列) ——
    > 而这一次是**我自己的手写格式**造成的, 不是判据写错。

    ⇒ 这条棘轮禁止 `## §N.N` 式的节标题 (本册的章级标题是 `## 1. …`, 用不到 §)。
    """
    bad = [m.group(0) for m in re.finditer(r"^##\s+§\d+\.\d+", LOG.read_text(encoding="utf-8"), re.M)]
    assert not bad, (
        f"§13.163: 这些节标题的形式**扫描器看不见** (应为 `### N.NNN`): {bad}\n"
        f"⇒ 用这种写法, 文首门禁对它们是**失明**的, 那个绿是虚的。"
    )


def test_scanner_sees_the_newest_section_number() -> None:
    """反空转: 扫描器必须能看见**最新**那一节 —— 否则整条门禁在扫一片旧区。

    ⚠️ 这条不硬编码节号 (那会立刻过期); 它要求: 扫描到的最高节号 **≥ 文末最后一节的节号**,
    而"文末最后一节"由**宽松**正则 (允许 `## §N.N` 等写法) 认出 —— 两者一比较,
    写法分歧就会**当场暴露**。
    """
    text = LOG.read_text(encoding="utf-8")
    strict = _max_section("13")
    loose = re.findall(r"^#{2,3}\s+§?13\.(\d+)", text, re.M)
    assert loose, "宽松正则一节也没找到 —— 正则坏了"
    newest_loose = max(int(x) for x in loose)
    newest_strict = int(strict.split(".")[1]) if strict else -1
    assert newest_strict == newest_loose, (
        f"§13.163: 严格扫到的最高节是 {newest_strict}, 而宽松扫到 {newest_loose} "
        f"⇒ 有节用了扫描器看不见的标题写法 (门禁对它们失明)。"
    )

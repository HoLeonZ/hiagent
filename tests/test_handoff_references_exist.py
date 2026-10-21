"""`docs/handoff.md` 引用的每一节都必须在日志里真实存在 (§13.143)。

为什么需要
----------
本册反复栽在**手工索引的过期速度 = 追加速度**上 (§13.94 两个索引接连烂掉;
§13.93 文首块与正文互相矛盾)。`handoff.md` 是一份**手工索引** ——
若不设门禁, 它会以同样的速度烂掉, 而它恰恰是给"下一个人"看的。

判据
----
把 `handoff.md` 里所有 `§<N>.<M>` 引用取出来, 要求日志里存在标题
`#{2,4} <N>.<M>` (允许 `N.M.k` 形式)。
⚠️ 只查**带小节的**引用; 裸 `§N` (如 `§7`) 不查 —— 那是章级引用, 形式不统一。

⚠️ 反向也要防 (§13.94 的教训): 这份索引若**只引用了极少数节**, 它也失去了意义
⇒ 同时要求引用数 ≥ 一个下限 (防"把引用删光以通过")。

用法: `python3 -m pytest tests/test_handoff_references_exist.py`
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HANDOFF = ROOT / "docs" / "handoff.md"
LOG = ROOT / "docs" / "strategy_mining_log.md"

_HEADING = re.compile(r"^\s*#{2,4}\s+(\d+\.\d+(?:\.\d+)?)\b", re.M)
_REF = re.compile(r"§\s*(\d+\.\d+(?:\.\d+)?)")


def _sections_in_log() -> set[str]:
    return set(_HEADING.findall(LOG.read_text(encoding="utf-8")))


def _refs_in_handoff() -> set[str]:
    return set(_REF.findall(HANDOFF.read_text(encoding="utf-8")))


def test_handoff_exists_and_points_at_the_log() -> None:
    assert HANDOFF.exists(), "docs/handoff.md 不存在 —— 它是给下一个人的入口"
    assert "strategy_mining_log.md" in HANDOFF.read_text(encoding="utf-8"), (
        "handoff 必须显式指向 logs/strategy_mining_log.md"
    )


def test_every_section_referenced_by_handoff_exists() -> None:
    have = _sections_in_log()
    want = _refs_in_handoff()
    missing = sorted(want - have)
    assert not missing, (
        f"§13.143: handoff.md 引用了日志里**不存在**的节: {missing}\n"
        f"⇒ 要么节号写错, 要么那一节被改名/删除。**手工索引会以追加速度烂掉 —— 这条就是防它的。**"
    )


def test_handoff_is_not_hollowed_out() -> None:
    """防"把引用删光以通过": 索引必须仍然引用足够多的节。"""
    n = len(_refs_in_handoff())
    assert n >= 20, (
        f"handoff.md 只引用了 {n} 个节 —— 它被删空了? "
        f"(这份文件的价值就在于把 11,797 行压成一个入口, 引用太少就失去意义)"
    )


if __name__ == "__main__":  # pragma: no cover
    h, w = _sections_in_log(), _refs_in_handoff()
    print(f"日志里有 {len(h)} 节; handoff 引用 {len(w)} 节; "
          f"缺失 {sorted(w - h)}")

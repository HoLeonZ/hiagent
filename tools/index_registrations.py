#!/usr/bin/env python3
"""把 §6「已登记未修」索引里**机械可枚举的那一半**变成一条命令 (2026-10-19, §13.94)。

## 为什么 (§6.6 已经烂过一次)
§6 的索引是**手工维护**的:
* §6.5 那张表覆盖到 §13.1x;
* §6.6 是后来补的, **只覆盖 §13.20–§13.39**, 而它自己的开头就写着
  「§6.5 那张表早于 §13.2x ⇒ 从 §6 进来的读者会**漏掉下面全部 15 项**」;
* 而 2026-10-19 我又追加了 **56 节** (§13.40–§13.93 + §9.3/§9.4)。
⇒ **同一个"摘要层腐烂"的模式, 已经在同一处发生两次。**
> **手工索引的过期速度 = 追加速度。** 而它恰恰是**给未来读者做决定用的**。

## 本工具做什么 / 不做什么
**做**: 扫全日志, 列出**每一节**并标出它**是否提到**登记/未修/未做/守卫/xfail —— 一个**候选清单**。
**不做**: **它判不了"会不会改结果"** (那要读懂语义)。**那一列仍然只能人工写。**
⇒ 所以它是**草稿生成器**: 先跑它, 再人工填第二列。**别把它当成索引本身。**

## 用法
    python3 tools/index_registrations.py                 # 全部节
    python3 tools/index_registrations.py --since 13.40    # §13.40 及其后
    python3 tools/index_registrations.py --only-registered  # 只留提到"登记/未修/未做"的

## ⚠️ `--since` 按 `(major, minor)` 比较, 跨章会"回绕"
`--since 9.3` **不是**"§9.3 加上 §13.40 之后" —— 它会把 §10/§11/§12 以及
§13.1–§13.39 **一起**带进来 (因为 `(10, *), (11, *), (12, *)` 都 > `(9, 3)`)。
⇒ 要"某章之后"请用**同章**写法 (`--since 13.40`)。这条是 2026-10-19 实际用出来的,
不是想出来的 —— 我第一次就把它写进了 §6.7, 然后跑了一下才发现对不上。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOG = REPO / "docs" / "strategy_mining_log.md"
HEAD_RE = re.compile(r"^###\s+(\d+\.\d+)\s+(.*)$")
FLAGS = (("登记", "登记"), ("未修", "未修"), ("未做", "未做"), ("未改", "未改"),
         ("xfail", "xfail"), ("守卫", "守卫"), ("已修", "已修"), ("已改", "已改"))


def sections() -> list[tuple[str, str, str]]:
    lines = LOG.read_text(encoding="utf-8").splitlines()
    idx = [(i, m.group(1), m.group(2).strip())
           for i, l in enumerate(lines) if (m := HEAD_RE.match(l))]
    out = []
    for k, (i, sec, title) in enumerate(idx):
        end = idx[k + 1][0] if k + 1 < len(idx) else len(lines)
        out.append((sec, title, "\n".join(lines[i:end])))
    return out


def key(sec: str) -> tuple[int, int]:
    a, b = sec.split(".")
    return int(a), int(b)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="", help="例 13.40")
    ap.add_argument("--only-registered", action="store_true")
    a = ap.parse_args(argv)
    lo = key(a.since) if a.since else (0, 0)

    rows = []
    for sec, title, body in sections():
        if key(sec) < lo:
            continue
        flags = sorted({tag for kw, tag in FLAGS if kw in body})
        if a.only_registered and not ({"登记", "未修", "未做", "未改"} & set(flags)):
            continue
        rows.append((sec, title, flags))
    print(f"共 {len(rows)} 节  (--only-registered = {a.only_registered})")
    print(f"{'节':>8}  {'标记':<28} 标题")
    for sec, title, flags in rows:
        print(f"{sec:>8}  {','.join(flags):<28} {title[:66]}")
    print("\n⚠️ **本工具判不了「会不会改结果」** —— 那一列请人工填 (§6.6 的读法)。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

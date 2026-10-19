"""普查工具(**不是门禁**):注释里 `X.py:NNN` 的**行号引用是否名副其实**。

## 为什么需要它

`06904b1` 修过一族缺陷:注释引用了一个**不存在的行号**,读者被送到别处。那次的处置是
把引用**换成语义**("一致的是闸门语义,不是默认值 —— 旧注释的行号与值都已不存在")。
但那次只改了**它当时看到的那些出现处** —— 附九十 实测:**同一个假声明在另外 6 个地方原样留着**,
其中 `short_reversal/presets.py` 一处重复了 **11 遍**。

## 判据(高精度优先)

一条引用要被判,必须同时满足:
  1. 形如 `X.py:NNN` 或 `X.py:NNN-MMM`(区间支持);
  2. **同一行里这个引用是唯一一个**带行号的引用(一行多引用时,行级分词无法把标识符
     归属给哪一条 —— 不判,宁可漏);
  3. 该行里出现了 **snake_case 标识符**(含下划线、非路径分量、非引擎包名)。

判定:该标识符必须出现在被引行号(区间取整段)的 ±10 行内。否则报"行号与内容不符"。

**已知盲区(附九十三 实测到一处活的)**:形如 `chase_up(:508)` 的引用 ——
**不带 `.py`、也不带文件名** —— 本工具**解析不到目标文件**,故**看不见它**。
实测 `cycle_price_action/portfolio.py` 的注释里就有一处:写 `chase_up(:508)` 与
`uptrend_pullback(:464)`,而那两处实施早已漂到 **510 / 466**。

**没有为它加判据**,理由:那种写法**本质上无法无歧义解析**(`chase_up(:508)` 指哪个文件?
`portfolio.py`? `backtrader_engine.py`?)⇒ 能做的只有"禁止这种格式",而那**不解决真缺陷**
(缺陷是**数字漂了**,不是格式);禁止格式只会把注释逼成别的写法、风险照旧。
正确处置是**如实登记这个盲区** + 遇到时按"换成语义"修掉(本次即如此)。

**覆盖面的诚实声明**(这是本会话反复栽的地方):上述三条把可判的引用压到**很窄**。
实测全库只有 **6 处**引用满足前三条件 —— **窄是换零误报的代价**,不是"全库只有 6 处引用"
(全库 `py:NNN` 引用有 104 处)。故门禁里带一条**非空转下限**:可判数不得低于 5,
否则说明判据坏了(而不是"代码干净")。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 引擎包名 —— 它们出现在注释里是"指哪个引擎",不是"目标处的一个标识符"。
_PACKAGE_TOKENS = frozenset({
    "chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action",
    "claude", "claude_md",
})

_REF = re.compile(r"([A-Za-z_][\w/]*\.py):(\d+)(?:\s*-\s*(\d+))?")
_SNAKE = re.compile(r"\b([a-z][a-z0-9]*_[a-z0-9_]{3,})\b")
_SLACK = 10


def _stem_of(target: str) -> str:
    return target.split("/")[-1][:-3]


def _all_stems_on_line(line: str) -> set[str]:
    return {m.group(1).split("/")[-1][:-3].lower()
            for m in re.finditer(r"([A-Za-z_][\w/]*\.py)", line)}


def find_stale_line_references(path: Path) -> list[tuple[int, str, str]]:
    """返回 `[(行号, 目标, 说明), …]`。"""
    out: list[tuple[int, str, str]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines, 1):
        refs = list(_REF.finditer(line))
        if not refs:
            continue
        drop = _PACKAGE_TOKENS | _all_stems_on_line(line)
        for m in refs:
            target, lo = m.group(1), int(m.group(2))
            hi = int(m.group(3)) if m.group(3) else lo
            resolved = path.parent / target.split("/")[-1]
            if not resolved.exists():
                resolved = ROOT / target
            if not resolved.exists():
                continue
            tlines = resolved.read_text(encoding="utf-8").splitlines()
            if lo > len(tlines):
                out.append((i, target, f"越界 —— 该文件只有 {len(tlines)} 行")); continue
            if len(refs) > 1:
                continue      # 一行多引用:归属不明,不判(宁可漏)
            toks = {w for w in _SNAKE.findall(line)
                    if w.lower() not in drop and w.lower() != _stem_of(target).lower()}
            if not toks:
                continue
            window = "\n".join(tlines[max(0, lo - _SLACK): min(len(tlines), hi + _SLACK)]).lower()
            missing = sorted(w for w in toks if w.lower() not in window)
            if missing:
                out.append((i, target, f"±{_SLACK} 行内找不到 {missing}"))
    return out


def judged_reference_count() -> int:
    """**可判**的引用数(用于非空转下限:判据坏了会掉到 0)。"""
    n = 0
    for p in sorted(ROOT.rglob("*.py")):
        if "__pycache__" in p.parts or "tests" in p.relative_to(ROOT).parts:
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            refs = list(_REF.finditer(line))
            if len(refs) != 1:
                continue
            drop = _PACKAGE_TOKENS | _all_stems_on_line(line)
            toks = {w for w in _SNAKE.findall(line) if w.lower() not in drop}
            if toks:
                n += 1
    return n

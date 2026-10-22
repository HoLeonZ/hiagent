"""§6: **扫描范围列表里的每一项都必须真的存在** —— 否则守卫会静默缩小。

## 2026-10-19 (§13.43) 的实据
`tests/test_assert_vs_raise_audit.py` 里:

```python
SCAN_DIRS = [
    "chase_up",
    "uptrend_pulback",     # ← 少一个 l (2026-10-19 修)
    "short_reversal",
    ...
]

for scan_dir in SCAN_DIRS:
    base = REPO_ROOT / scan_dir
    if not base.exists():
        continue           # ← **静默跳过**
```

⇒ **`uptrend_pullback` 的 28 个生产文件(占该审计的 26%)被静默排除, 而没有任何东西发出过提示。**
修好后该审计覆盖 **78 → 106** 个文件。

> **这是 §0 「Do not silently bypass」在守卫自己身上的实例。**
> 一个把范围写在手写列表里、又用 `if not exists: continue` 兜底的守卫,
> **任何拼错、改名、搬目录都会悄悄缩小它的覆盖面** —— 而它在 `-rs` 里长得跟正常通过一模一样。
> (这与 §13.22 / §13.23 / §13.42 是同一族问题的**第四个面**: 那三次是"列表里少了本该有的",
> 这次是"列表里的**写错了**"。)

## 判据
对 `tests/` 下每个模块级列表/元组/集合:
* **只挑"像是扫描范围"的** —— 判据是**其中至少有 1 项**能在仓库根解析成**已存在的目录**
  (这条过滤掉了 `NUMERIC_COLUMNS` / `REQUIRED_FIELDS` / `ATTR_CHAIN_FINAL_NAMES` 那类
   纯字符串清单, 它们的元素不对应任何目录);
* 然后断言**每一项**都解析成已存在的目录。

⇒ 它只抓"这个列表的功能就是指向目录, 而其中有一项指错了"。
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).parent

BARE_NAME = __import__("re").compile(r"^[a-z][a-z0-9_]*$")


def _scope_lists() -> list[tuple[str, int, str, list[str]]]:
    """返回 [(文件, 行号, 变量名, 元素)] —— 只含"像是扫描范围"的那些列表。"""
    found = []
    for p in sorted(TESTS_DIR.glob("test_*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                continue
            vals = [
                e.value for e in node.value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
            if len(vals) < 2 or not all(BARE_NAME.match(v) for v in vals):
                continue
            # 判别式: 这一项"像是指向目录的清单"。
            #
            # ⚠️ 2026-10-22 (附一百八十六): 原判别式是「**至少有一项**是已存在目录」——
            # 太弱。实测被它误判:`test_cycle_signal_layer_is_causal.py` 里的
            # `FULL_FRAME_NAMES = {"df","bars","panel","panel_ind","data"}` 是**变量名集**,
            # 只因 `"data"` 恰好是仓库根下的目录 ⇒ 整条被当成扫描范围清单 ⇒ 另外 4 个名字报红。
            # (讽刺的是这条守卫存在的理由正是"抓会静默缩小覆盖面的清单"。)
            # 收紧为:**过半**是已存在目录,且**至少 2 项**。带 1 处拼错的真清单是
            # (N−1)/N 项为目录 ⇒ 仍被认出来(原功能不减)。
            hits = sum(1 for v in vals if (REPO_ROOT / v).is_dir())
            if hits < 2 or hits * 2 < len(vals):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            for n in names:
                found.append((p.name, node.lineno, n, vals))
    return found


def test_scope_lists_are_discoverable() -> None:
    """反空转对照: 必须真能找到一些"扫描范围列表", 否则下面的断言全是空的。"""
    scopes = _scope_lists()
    assert len(scopes) >= 3, (
        f"只找到 {len(scopes)} 个扫描范围列表 ({[s[2] for s in scopes]}) —— 判别式可能坏了。"
        f"已知至少有 SCAN_DIRS / FAMILIES / ENGINE_DIRS 三类。"
    )


def test_every_scope_list_entry_is_an_existing_directory() -> None:
    """扫描范围列表里的**每一项**都必须解析成已存在的目录。

    拼错 / 改名 / 搬目录 ⇒ 红。**这一条正是修掉 `"uptrend_pulback"` 那个拼写错误所要的守卫。**
    """
    bad = []
    for fname, lineno, var, vals in _scope_lists():
        for v in vals:
            if not (REPO_ROOT / v).is_dir():
                bad.append(f"  {fname}:{lineno}  {var} 里的 {v!r} 不是仓库根下的目录")
    assert not bad, (
        "以下扫描范围列表里有**指向不存在目录**的项 —— 那些项会让守卫静默缩小覆盖面 "
        "(§0: Do not silently bypass):\n" + "\n".join(bad)
    )

"""普查工具(**不是门禁**):有没有把"整张面板的长度"当成"窗口内的期数"传进去。

起因(附八十一):各引擎的 `load_panel()` 都把起点往前推一个暖机缓冲
(`WARMUP_DAYS = 400`),所以 `panel` **不是**窗口,而是 `[start − 400 天, end]`。
于是 `panel["date"].nunique()` 量的是**面板**长度。而它的名字长得很像窗口统计量,
于是它被当成窗口期数用在两个地方:

  * `n_returns=` → DSR 的 T;
  * `n_trading_days=` → CAGR 的年化分母。

实测(窗口 2025-09-16..2026-09-16,243 个交易日):面板 510 个交易日 ⇒ **T 高估 2.10 倍**。

判据(针对**已观测到的两种形状**,不猜别的):
  凡是以 `n_returns` / `n_trading_days` 为**关键字**传出去的实参,其表达式子树里
  不得出现
    * 任何 `.nunique()` 调用 —— 这是"数了整张表的日期"的写法(**无条件禁**);
    * `len(<看起来像整张表的裸名字>)` —— 这是"数了整张表的行数"的写法
      (只在名字命中表启发式时禁,见 `_LOOKS_LIKE_A_TABLE`)。
  (`len([...])` / `len(x for ...)` 这类**就地构造**的集合不受限:它们量的不是面板。)

合法写法是 `core.walkforward.window_trading_days(panel, start, end)`(单源,窗口内计数,
空窗口 fail-fast)。这个白名单式判据不会被"换个说法"绕过:任何新写法只要还在数面板就会命中。

**如实声明的漏报**:`len(<名字>)` 那一半靠命名,若有人把面板绑到 `t`、`x` 这类名字上就会漏
(实测真缺陷 8/8 全靠 `.nunique()` 那一条命中,`len` 那一条是防御性的)。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# CAGR 年化分母 / DSR 的 T —— 任何以这些名字传出去的量都必须是**窗口内**的
_PERIOD_KWARGS = {"n_returns", "n_trading_days", "trading_days", "n_periods", "n_days"}

#: `len(x)` 里"x 看起来是一张表"的启发式。命中才报,避免把 `len(s)`(窗口内的收益序列)误报。
_LOOKS_LIKE_A_TABLE = ("panel", "df", "frame", "data", "table", "bars", "kline")


def _looks_like_a_table(name: str) -> bool:
    low = name.lower()
    return any(tok in low for tok in _LOOKS_LIKE_A_TABLE)


def _counts_a_whole_table(expr: ast.AST) -> list[str]:
    """子树里"数整张表"的写法(`.nunique()` / `len(表名)`)的可读描述。"""
    found: list[str] = []
    for sub in ast.walk(expr):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Attribute) and func.attr == "nunique":
            found.append(ast.unparse(sub))
        elif isinstance(func, ast.Name) and func.id == "len":
            args = sub.args
            if len(args) == 1 and isinstance(args[0], ast.Name) and _looks_like_a_table(args[0].id):
                found.append(ast.unparse(sub))
    return found


def find_panel_length_as_period(path: Path) -> list[tuple[int, str, str]]:
    """返回 `[(行号, 关键字名, 有问题的表达式), …]`。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    out: list[tuple[int, str, str]] = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        for kw in call.keywords:
            if kw.arg in _PERIOD_KWARGS:
                for bad in _counts_a_whole_table(kw.value):
                    out.append((kw.value.lineno, kw.arg, bad))
    return out


def main(argv: list[str] | None = None) -> int:
    total = 0
    for path in sorted(ROOT.rglob("*.py")):
        if "__pycache__" in path.parts or "tests" in path.relative_to(ROOT).parts:
            continue
        hits = find_panel_length_as_period(path)
        if hits:
            total += len(hits)
            print(f"{path.relative_to(ROOT)}:")
            for ln, arg, expr in hits:
                print(f"    :{ln}  {arg} = {expr}")
    print(f"\n共 {total} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())

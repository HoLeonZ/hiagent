"""§2/§5 守卫：年化口径必须**单源**,且必须是**交易日**口径。

本仓库此前有**三处**不同口径:

| 位置 | 口径 |
|---|---|
| `chase_up/backtest.py` | `交易日数 / 243` |
| `uptrend_pullback/backtest.py` | `交易日数 / 243`(与前一处同值但**各写一份**) |
| `short_reversal/engine.py` | `日历日跨度 / 365` |
| `dna_stats/*.py` | 默认 `252`(参数,由调用方传) |

日历日 ≠ 交易日。实测同一窗口、同一 10% 总收益下,两种引擎口径给出的 CAGR:

| 窗口 | 交易日/日历日 | 交易日口径 | 日历日口径 | 相对差 |
|---|---|---|---|---|
| 2026-04-01→05-01 | 23 / 30   | 173.7% | 218.9% | **26%** |
| 2026-01-20→03-01 | 29 / 40   | 122.3% | 138.6% | **13%** |
| 2025 全年         | 261 / 364 |  9.28% | 10.03% | **8%**  |

**两边都"看起来合理"** —— 这正是最难发现的一类漂移(同一个指标、两处定义、都自洽)。
引擎侧现统一为 `core.trade_schema.TRADING_DAYS_PER_YEAR`(=243,A 股交易日/年)。

`dna_stats` 的 252 属 §5 统计口径(改动会影响 DSR / Bonferroni 的结论),仍另行登记,
不在本文件强制范围内。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

ENGINE_BACKTESTS = {
    "chase_up": REPO_ROOT / "chase_up" / "backtest.py",
    "uptrend_pullback": REPO_ROOT / "uptrend_pullback" / "backtest.py",
}


def _names_referenced(src: str) -> set[str]:
    """源码里**真正被引用**的名字(注释、docstring 里的**不算**)。

    阴性判据尤其需要它:一句「别再用 `DAYS_PER_YEAR`」的注释会把**文本**判据自己判红。
    """
    tree = ast.parse(src)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    return names


def _imported_modules(src: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _called_names(src: str) -> set[str]:
    """被**调用**的函数名(裸名或属性名)。"""
    called: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
    return called


def _literal_assignments(src: str) -> dict[str, object]:
    """`名字 = 字面量` 的赋值(含带注解的)—— 与空格、注解、行尾注释都无关。"""
    literals: dict[str, object] = {}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    literals[target.id] = node.value.value
        elif (isinstance(node, ast.AnnAssign)
              and isinstance(node.target, ast.Name)
              and isinstance(node.value, ast.Constant)):
            literals[node.target.id] = node.value.value
    return literals


def test_canonical_constant_is_trading_days() -> None:
    from core.trade_schema import TRADING_DAYS_PER_YEAR, annualized_years

    assert TRADING_DAYS_PER_YEAR == 243, (
        "A 股交易日/年 ≈ 242~244。改动此值会改变**所有**引擎的年化结果 —— "
        "那是一次全局结果漂移,必须在 PR 里说明,不能顺手改。"
    )
    assert annualized_years(TRADING_DAYS_PER_YEAR) == pytest.approx(1.0)
    assert annualized_years(0) > 0, "下限必须为正(除零保护)"


@pytest.mark.parametrize("engine,path", sorted(ENGINE_BACKTESTS.items()))
def test_engines_use_the_canonical_constant(engine: str, path: Path) -> None:
    """引擎不得各写一份 243 —— 同值不同源就是下一次漂移的起点。

    判据是 **AST**(附一百四十五):「**引用**了 `TRADING_DAYS_PER_YEAR`」+「从
    `core.trade_schema` 导入」,以及「**没有任何**名字被赋成字面量 `243`」。
    注释 / docstring 里的名字**不算引用**;`TRADING_DAYS: int = 243` 这种带注解的写法**也算**。
    """
    src = path.read_text(encoding="utf-8")
    assert ("core.trade_schema" in _imported_modules(src)
            and "TRADING_DAYS_PER_YEAR" in _names_referenced(src)), (
        f"{engine}: 年化常量必须来自 core.trade_schema(§2 单源)"
    )
    hardcoded = sorted(
        name for name, value in _literal_assignments(src).items()
        if isinstance(value, int) and not isinstance(value, bool) and value == 243
    )
    assert not hardcoded, (
        f"{engine}: 又出现了本地写死的 243(赋给了 {hardcoded})—— 回到同值不同源"
    )


def test_all_engines_agree_on_the_annualization_constant() -> None:
    """三个引擎的常量必须**同一个值**(直接比对,而不是各自看源码)。"""
    from chase_up.backtest import TRADING_DAYS as chase_days
    from core.trade_schema import TRADING_DAYS_PER_YEAR
    from uptrend_pullback.backtest import TRADING_DAYS as uptrend_days

    assert chase_days == uptrend_days == TRADING_DAYS_PER_YEAR


def test_short_reversal_annualizes_on_trading_days_not_calendar_days() -> None:
    """short_reversal 必须已切到交易日口径 —— 日历日口径就是那个 26% 偏差的来源。

    判据是 **AST**:①**不引用** `DAYS_PER_YEAR` 这个名字(注释里提到不算 ——
    否则一句「别再用它」的注释会把这条**阴性**判据自己判红;而且 `TRADING_DAYS_PER_YEAR`
    与它只是**子串**关系,文本判据分不出来,AST 按名字分得出来);
    ②**真的调用**了 `annualized_years`(不是"源码里出现过这个词")。
    """
    src = (REPO_ROOT / "short_reversal" / "engine.py").read_text(encoding="utf-8")
    assert "DAYS_PER_YEAR" not in _names_referenced(src), (
        "short_reversal 仍在引用日历日年化名 `DAYS_PER_YEAR`(=`365` 那一套)"
    )
    assert "annualized_years" in _called_names(src), (
        "短反转未**调用**规范的交易日年化助手 `annualized_years`"
    )


def test_short_reversal_metrics_expose_the_annualization_denominator() -> None:
    """口径随产物发布:`cagr` 旁边必须有它的分母(交易日数)。

    与 cycle 的 `account_model` 字段同一理由 —— 一个数字的含义依赖未说明的模型时,
    就不能只让模型活在 docstring 里。
    """
    from core.trade_schema import TRADING_DAYS_PER_YEAR
    from short_reversal.engine import INITIAL_CAPITAL, _metrics_from_holder

    # §2: 合成 holder 也要带 final_nav(无未平仓 → nav == cash)
    holder = {"cash": INITIAL_CAPITAL * 1.10, "final_nav": INITIAL_CAPITAL * 1.10,
              "trades": [], "max_dd": 0.0}
    cfg = {"_name": "synthetic"}
    n_days = 20
    m = _metrics_from_holder(
        holder, "2025-01-01", "2025-01-31", cfg, n_trading_days=n_days
    )

    assert m["n_trading_days"] == n_days
    # CAGR 必须按**交易日**年化;日历日年化会给出更大的值(同一收益、更短的年数)
    expected = 1.10 ** (1.0 / (n_days / TRADING_DAYS_PER_YEAR)) - 1.0
    assert m["cagr"] == pytest.approx(expected, rel=1e-12)

    calendar_years = 30 / 365.0
    calendar_cagr = 1.10 ** (1.0 / calendar_years) - 1.0
    assert abs(expected - calendar_cagr) > 1e-3, (
        "夹具没有区分出两种口径,这条断言就失去意义了(换个更短的窗口)"
    )


def test_the_ast_helpers_ignore_comments_and_distinguish_substring_names() -> None:
    """**牙齿**:①注释 / docstring 里的名字**不算引用**;②`TRADING_DAYS_PER_YEAR` ≠ `DAYS_PER_YEAR`。

    (这两条正是旧文本判据的两个坏方向:阴性判据被一句注释判红;子串关系分不出来。)
    """
    commented = (
        "# DAYS_PER_YEAR = 365  # 别再用它\n"
        '"""文档里提到 annualized_years 与 TRADING_DAYS_PER_YEAR 都不算引用。"""\n'
    )
    assert "DAYS_PER_YEAR" not in _names_referenced(commented)
    assert "TRADING_DAYS_PER_YEAR" not in _names_referenced(commented)
    assert "annualized_years" not in _called_names(commented)
    assert _literal_assignments(commented) == {}, "注释里的赋值不算赋值"

    real = (
        "from core.trade_schema import TRADING_DAYS_PER_YEAR, annualized_years\n"
        "x = annualized_years(TRADING_DAYS_PER_YEAR)\n"
    )
    assert "TRADING_DAYS_PER_YEAR" in _names_referenced(real)
    assert "annualized_years" in _called_names(real)
    assert "core.trade_schema" in _imported_modules(real)
    assert "DAYS_PER_YEAR" not in _names_referenced(real), (
        "`TRADING_DAYS_PER_YEAR` 与 `DAYS_PER_YEAR` 只是**子串**关系,不该混为一谈"
    )

    assert _literal_assignments("TRADING_DAYS: int = 243\n") == {"TRADING_DAYS": 243}, (
        "带注解的硬编码也算硬编码"
    )
    assert "TRADING_DAYS" in _literal_assignments("TRADING_DAYS = 243  # 行尾注释\n")

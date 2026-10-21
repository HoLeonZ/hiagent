"""§5: `iter_reverse.py` 的**迭代记账与惩罚指标** (§13.100, 2026-10-19)。

## 起点 (§13.81 的登记项)
`uptrend_pullback/iter_reverse.py` 是**全仓唯一没有 §5 三件套的优化器**
(`n_trials`/DSR/Bonferroni 命中 0 处) —— 而它正是**当前最优的直系祖先**
(`v33_long_reverse_v20` = `--iter 100` 的产物)。本轮补上。

## 本文件钉的三件事
1. **三件套真的在**: 既调 `deflated_sharpe_ratio` 也调 `sharpe_significance_pvalue`,
   且 `n_trials` 是**真参数** (不是写死 1)。
2. **★ 只报告, 不参与排序** —— 这是本改动**零行为变更**的全部依据。
   排序键必须仍只有 `score / median_ret / worst_ret`; 一旦 `dsr`/`bonferroni_p`
   进了排序键, 选择就会变, 而那是**结果变更** (须单独决策, 不是本轮这种补报告)。
3. **`k` 必须是累积暴露** = 锚点已承载的 `n_comparisons` + 本轮迭代数。
   §5 明文 "Every iteration … increments n_trials"; **从 0 起算会把跨轮历史抹掉**
   (这正是 §13.82 记的那处)。
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "uptrend_pullback" / "iter_reverse.py"


def _src() -> str:
    return SRC_PATH.read_text(encoding="utf-8")


def _tree() -> ast.Module:
    return ast.parse(_src())


def _called_names(tree: ast.AST) -> set[str]:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def test_s5_triad_is_actually_present() -> None:
    """三件套: DSR + Bonferroni p + `n_trials`。"""
    called = _called_names(_tree())
    assert "deflated_sharpe_ratio" in called, (
        "§13.100: iter_reverse 没有调用 deflated_sharpe_ratio —— §5 要求多参数 sweep 报 DSR。"
    )
    assert "sharpe_significance_pvalue" in called, (
        "§13.100: 没有调用 sharpe_significance_pvalue ⇒ Bonferroni 那一半不可复现。"
    )
    assert "n_trials" in _src(), "§13.100: 没有 n_trials 记账"
    # n_trials 必须是**参数**, 不能写死
    fn = next((n for n in ast.walk(_tree())
               if isinstance(n, ast.FunctionDef) and n.name == "score_windows"), None)
    assert fn is not None, "找不到 score_windows"
    args = [a.arg for a in fn.args.args] + [a.arg for a in fn.args.kwonlyargs]
    assert "n_trials" in args, (
        f"§13.100: score_windows 的形参里没有 n_trials (实为 {args}) ⇒ 记账无处传入。"
    )


def test_s5_metrics_do_not_enter_the_sort_key() -> None:
    """★ **只报告, 不参与排序** —— 本改动零行为变更的全部依据。

    排序键若含 `dsr`/`bonferroni_p`, 选择就会变 ⇒ 那是**结果变更**,
    必须先决策再改, 不能顺手做。
    """
    fn = next((n for n in ast.walk(_tree())
               if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    assert fn is not None, "找不到 main"
    sorts = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "sort"]
    assert sorts, (
        "§13.100: 反空转失败 —— 在 main() 里找不到 `rows.sort(...)`。"
        "判据的扫描单位不存在时, 本断言会恒真。"
    )
    for s in sorts:
        key = ast.unparse(s)
        for bad in ("dsr", "bonferroni", "sharpe_p"):
            assert bad not in key, (
                f"§13.100: 排序键里出现了 §5 惩罚指标 `{bad}` —— 排序会因此改变。\n"
                f"实测排序调用: {key}\n"
                f"⇒ 若**确实**想按 §5 排序, 那是**结果变更**, 请单独决策并登记漂移, "
                f"不要在本轮这种'补报告'里捎带。"
            )


def test_k_is_the_accumulated_exposure_not_this_round_only() -> None:
    """`k` 必须 = 锚点已承载的 `n_comparisons` + 本轮迭代数 (§5 Iterative-Tuning Accounting)。"""
    src = _src()
    assert 'n_comparisons' in src, (
        "§13.100: 没有读锚点的 `n_comparisons` ⇒ k 会从 0 起算, 把跨轮迭代历史抹掉。"
    )
    assert "k_accum" in src, (
        "§13.100: 没有累积暴露变量 —— 需要 `k = base.n_comparisons + args.iter` 这样的显式合成。"
    )
    # 且必须真的把它传给 score_windows
    fn = next((n for n in ast.walk(_tree())
               if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "score_windows"]
    assert calls, "找不到 score_windows 的调用点"
    assert all("k_accum" in ast.unparse(c) for c in calls), (
        "§13.100: 调用 score_windows 时没有传累积 k ⇒ 报告出来的 DSR 用的是错的 k。"
    )


def test_n_returns_convention_matches_the_shared_reporter() -> None:
    """`n_returns` 的口径必须与 `dna_stats.walkforward_report.format_walkforward_stats` 一致
    (`max(窗口数 × 63, 100)`), 否则同一个搜索在两处报出不同的 DSR。"""
    src = _src()
    assert "n_total * 63" in src or "n_total*63" in src, (
        "§13.100: n_returns 未按共享口径 `窗口数 × 63` 计算 ⇒ 与 format_walkforward_stats 不一致。"
    )
    assert "100" in src

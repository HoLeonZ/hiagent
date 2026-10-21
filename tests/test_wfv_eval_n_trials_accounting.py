"""§5: `wfv_eval` 的 `n_trials` 必须来自 **preset 的累积暴露** (§13.104, 2026-10-19)。

## 这条登记项 (§13.82) 与它的修补方向
§5 的 Iterative-Tuning Accounting 要求 `n_trials` = **到此为止累计试过的配置数**。
`uptrend_pullback` 一路把这条账记在 preset 的 `n_comparisons` 上
(v19=19 → v20=100 → v21=121 → **v22=162**) —— **但直到 §13.104 它没有任何消费者**。
§13.82 自己写下的修补方向是:
> 「让 `format_walkforward_stats` 的调用方**从 preset 取** `n_comparisons`, 而不是从 CLI/本次候选数。」

**而当时的现状更糟**: `--n-trials` 是**必填**, 且 docstring 的示例教人传 `--n-trials 1` / `12`
—— **两个都不是该 preset 的累积暴露** ⇒ **文档教的用法违反 §5**。

## 本文件钉的
1. 缺省时必须解析成 **preset 自己的 `n_comparisons`** (行为式, 直接调解析器);
2. 显式 CLI 必须**能**覆盖 (派生 candidate 的场景要保留);
3. 解析出来的值必须**真的**被喂进报告器 (不能解析完又用 `args.n_trials`);
4. **账本身必须单调** —— 跨版本的 `n_comparisons` 只增不减 (它记的是"累计");
5. 反空转: 解析器必须真的取到 > 1 的值, 否则本判据在比 `1 == 1`。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "uptrend_pullback" / "wfv_eval.py"

# 该族一路的版本链 (从 §13.81 的族谱)
_CHAIN = ["v33_long_reverse_v19", "v33_long_reverse_v20",
          "v33_long_reverse_v21", "v33_long_reverse_v22"]


def _src() -> str:
    return SRC_PATH.read_text(encoding="utf-8")


def test_default_resolves_to_the_presets_own_accumulated_exposure() -> None:
    """缺省 ⇒ preset 的 `n_comparisons`, 且**报出来源**。"""
    from uptrend_pullback.presets import get_preset
    from uptrend_pullback.wfv_eval import _resolve_n_trials

    cfg = get_preset("v33_long_reverse_v22")
    n, src = _resolve_n_trials(None, cfg)
    assert n == int(cfg["n_comparisons"]), (
        f"§13.104: 缺省时解析出 {n}, 而 preset 记的是 {cfg['n_comparisons']} —— "
        f"§5 的累积账没有被用上。"
    )
    assert "preset" in src, f"§13.104: 必须报出来源, 实为 {src!r}"


def test_the_cli_can_still_override() -> None:
    """派生 candidate 的场景: CLI 必须能覆盖 (但覆盖值会被打印)。"""
    from uptrend_pullback.presets import get_preset
    from uptrend_pullback.wfv_eval import _resolve_n_trials

    cfg = get_preset("v33_long_reverse_v22")
    n, src = _resolve_n_trials(50, cfg)
    assert n == 50, f"§13.104: CLI 覆盖失效 —— 期望 50, 得到 {n}"
    assert "CLI" in src, f"§13.104: 覆盖时必须标明来源是 CLI, 实为 {src!r}"


def test_the_resolved_value_is_the_one_actually_reported() -> None:
    """★ 解析出来之后**必须真的用**它 —— 否则是"算了但不用"。

    判据: `format_walkforward_stats` 的调用点不得出现 `args.n_trials`;
    `args.n_trials` 只允许出现在**解析调用**里。
    """
    tree = ast.parse(_src())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    assert fn is not None, "找不到 main"
    call = next((n for n in ast.walk(fn)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "format_walkforward_stats"), None)
    assert call is not None, "找不到 format_walkforward_stats 的调用点"
    txt = ast.unparse(call)
    assert "args.n_trials" not in txt, (
        f"§13.104: 报告器仍直接用 `args.n_trials` (绕开了 preset 的账):\n{txt}"
    )
    assert "n_trials" in txt, f"§13.104: 报告器没收到 n_trials:\n{txt}"


def test_the_ledger_is_monotone_across_versions() -> None:
    """★ **账本身必须单调**: `n_comparisons` 记的是"累计试过的配置数", 只能增。

    这条防的是"有人把账重置了" —— 那会让 DSR 的选择偏差折算**变松**(k 小 ⇒ DSR 高 ⇒ 乐观)。
    """
    from uptrend_pullback.presets import get_preset

    vals = [(name, int(get_preset(name).get("n_comparisons", 0))) for name in _CHAIN]
    for (n0, v0), (n1, v1) in zip(vals, vals[1:]):
        assert v1 > v0, (
            f"§13.104: 累积账不单调: {n0}={v0} → {n1}={v1}。\n"
            f"'累计'只能增; 若确实要下调, 必须同时说明为什么历史暴露被撤回。"
        )
    assert vals[-1][1] > 1, (
        f"§13.104: 末端的累积暴露只有 {vals[-1][1]} ⇒ 反空转失败, 本判据在比 1==1"
    )

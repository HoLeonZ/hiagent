"""§5 DSR 输入量纲守卫（审计 P3，2026-10-15）。

DSR 的收缩量取决于「检验了多少个假设」(`n_trials` = **试过的配置数**),而不是
「评估了多少个窗口」。审计发现 walk-forward 家族把窗口数当配置数传进去:

    n_trials=len(sharpes)      # sharpes 是逐个 **窗口** 的 Sharpe

后果:DSR **低估收缩、高估显著性** —— 越是被反复评估的窗口序列,越显得"显著"。
最自证的证据是 `short_reversal/walkforward.py`:它传 `n_trials=len(sharpes)`,
而同一行的输出标签写着 `n_windows={len(sharpes)}` —— 参数与标签自相矛盾。

仓库本来就记录了正确的量:preset 的 `n_comparisons` 字段(§5 Iterative-Tuning
Accounting),但该字段此前**被声明却无消费者**。现在 walk-forward 家族改用它,
`n_returns` 亦改为窗口的真实交易日数(6 个月 ≈ 126),而非硬编码 252(全年)。

本文件锁定:
  1. 所有 preset 都声明正的 `n_comparisons`(该字段有消费者才有意义)。
  2. walk-forward 家族必须用 `n_comparisons`,不得再传窗口数。
  3. 窗口交易日数常量为 126(6 个月),不是 252 —— 防止悄悄退回全年口径。
  4. `n_returns` 不得在 walk-forward 家族里硬编码 252。

注:网格类脚本(`uptrend_pullback/sweep_v33_long*.py`、`chase_up/sweep*.py`、
`short_reversal/grid_runner.py`、`cycle_price_action/sweep_thresholds.py`)的
`sharpes` **本就是逐配置**的,故它们传配置数是对的 —— 不在本文件的强制范围内,
逐处读码确认过。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WF_FAMILY = sorted((REPO_ROOT / "short_reversal").glob("wf_v*_focused.py")) + [
    REPO_ROOT / "short_reversal" / "walkforward.py",
]


def _preset_registries() -> list[tuple[str, dict]]:
    out = []
    for name, mod_name in (("chase_up", "chase_up.presets"),
                           ("uptrend_pullback", "uptrend_pullback.presets"),
                           ("short_reversal", "short_reversal.presets")):
        mod = __import__(mod_name, fromlist=["*"])
        out.append((name, mod.PRESETS))
    return out


def test_every_preset_declares_positive_n_comparisons() -> None:
    """§5 Iterative-Tuning Accounting:累计试验数必须被记录,且是正整数。"""
    total = 0
    for engine, reg in _preset_registries():
        bad = [k for k, v in reg.items()
               if not isinstance(v.get("n_comparisons"), int) or v["n_comparisons"] < 1]
        assert not bad, (
            f"§5 VIOLATION: {engine} 的 preset 缺少/非法 n_comparisons: "
            f"{bad[:5]}{'...' if len(bad) > 5 else ''} (共 {len(bad)} 个)"
        )
        total += len(reg)
    assert total >= 100, f"preset 总数异常({total})"


def test_n_comparisons_has_a_consumer() -> None:
    """该字段必须真的被 DSR 调用点消费(否则只是装饰,§6 意义上无意义)。"""
    consumers = [
        p for p in WF_FAMILY
        if "n_comparisons" in p.read_text(encoding="utf-8")
    ]
    assert len(consumers) == len(WF_FAMILY), (
        "§5 VIOLATION: 以下 walk-forward 脚本未消费 n_comparisons: "
        f"{[p.name for p in WF_FAMILY if p not in consumers]}"
    )


@pytest.mark.parametrize("path", WF_FAMILY, ids=lambda p: p.name)
def test_walkforward_uses_configuration_count_not_window_count(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    assert "n_comparisons" in src, (
        f"§5 VIOLATION: {path.name} 未用配置数作 n_trials"
    )
    for bad in ("n_trials=len(sharpes)", "n_trials=len(all_sharpes)"):
        assert bad not in src, (
            f"§5 VIOLATION: {path.name} 仍传窗口数作 n_trials(`{bad}`)—— "
            "会把「评估了多少窗口」当成「检验了多少假设」,低估收缩"
        )


@pytest.mark.parametrize("path", WF_FAMILY, ids=lambda p: p.name)
def test_walkforward_observation_count_comes_from_the_run(path: Path) -> None:
    """§5: 观测数 T 必须由**本次运行**算出 —— 既不得是字面量,也不得是模块级常量。

    附六十:本用例原来的断言是

        assert re.search(r"^WINDOW_TRADING_DAYS = 126\b", src, re.M)

    —— 判据是"**必须存在**那个常数",而不是"不许把 T 写死"。它把当时那版实现的
    形状钉成了要求,于是:一边**放过** 16 个「T 与窗口长度不符」的脚本(它们都有那个
    常数:窗口默认 2 个月 ≈42 天,常数却是 126,DSR 因而系统性**偏乐观**),
    一边让"把 T 改成来自本次运行"的修复**变红**。

    这是本审计反复记录的那一类守卫("断言的是当时实现的形状"),只不过这一次它
    站在**缺陷那一侧**:它不是没拦住,而是**在要求缺陷存在**。
    现按**性质**断言:没有该常量、没有字面量 T、且确实消费了来自运行的 `n_trading_days`。
    """
    src = path.read_text(encoding="utf-8")
    assert not re.search(r"^WINDOW_TRADING_DAYS\s*[:=]", src, re.M), (
        f"§5 VIOLATION: {path.name} 仍有 WINDOW_TRADING_DAYS 常量 —— "
        "它与 CLI 的窗口长度无关,T 会与实际观测数不符"
    )
    for bad in ("n_returns=252", "n_returns=365", "n_returns=126"):
        assert bad not in src, f"§5 VIOLATION: {path.name} 仍硬编码 {bad}"
    # (c) 必须**真的**从 metrics 里读 T —— 用 AST 判,不用词。
    # 我第一次写的是 `assert "n_trading_days" in src`,而我刚插入的**注释**里就
    # 正好提到这个词 ⇒ 把消费那一行整个删掉,断言**仍然通过**(实测)。
    # 这就是本审计反复记录的"判词不判行为";不能自己再犯一次。
    import ast as _ast

    tree = _ast.parse(src)
    reads = [
        n for n in _ast.walk(tree)
        if isinstance(n, _ast.Subscript)
        and isinstance(n.slice, _ast.Constant)
        and n.slice.value == "n_trading_days"
    ]
    assert reads, (
        f"§5 VIOLATION: {path.name} 没有**读取**来自运行的观测数"
        "(应消费引擎发布的 metrics['n_trading_days'])"
    )

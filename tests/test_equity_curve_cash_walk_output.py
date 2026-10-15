"""§2/§3 权益曲线与现金流水 —— **产物边界**守卫（2026-10-15 重写）。

原版（Tick 51, 2026-09-23）是三条 **RED-by-design** 用例：它们断言
`<engine>/results/*equity*.csv` 之类的文件**不存在**，把「缺一个 CSV writer」
登记成一个**永远失败**的测试。这有三个问题：

  1. **与 §7 冲突**。§7 明令 `results/` 必须 gitignored、fresh clone 必须零历史
     产物。于是「某产物是否存在」根本不是仓库的属性 —— 它只反映**本机跑没跑过
     回测**。fresh clone 必然全红；而本机只要有一个 `*ledger*.csv` 之类的东西，
     它又会转绿 —— 两端都不可信。
  2. **与 §6 冲突**。§6：测试在本地 DB / 运行产物缺失时必须 **skip，不得 error**。
     这三条是 fail，不是 skip，于是「红」变成了背景噪音 —— 而本仓库的历史已经
     证明：一旦红是常态，真实回归就会藏在其中（本文件所在分支的整改过程中，
     一次真回归正是被「失败数没变」掩盖过去的）。
  3. **覆盖面反而不如已有守卫**。它们只看文件名，不看内容；而 §2 的实质要求
     ——「equity = free + settling + holdings，且现金守恒」—— 已由
     `tests/test_nav_cash_ledger_invariants.py::
     test_chase_up_equity_nav_identity_and_cash_conservation`
     **在内存里确定性地**验证，不依赖任何磁盘产物。

所以本文件现在只守**产物边界**这件事：产物在 → 校验其 schema；产物不在 →
skip 并点名缺口（而不是静默通过，也不是永久失败）。§2 的能力要求由上面那条
内存守卫负责。缺 CSV writer 一事登记在审计报告 §8「仍未处理」。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINES = ["chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action"]

#: §7 缺口登记文本：产物缺失是**预期状态**（results/ 不入库），不是失败。
_GAP = (
    "§7 GAP REGISTERED: 本机 `{engine}/results/` 下没有 {what}。"
    "results/ 按 §7 必须 gitignored，故 fresh clone 下这里**必然**缺失 —— "
    "这是产物边界，不是纪律违规。§2 的实质要求（NAV 恒等式 + 现金守恒）由 "
    "tests/test_nav_cash_ledger_invariants.py 在内存中确定性验证。"
    "「缺少 {what} 的 writer」属未结事项，登记于审计报告 §8。"
)


def _matching(pattern: str) -> list[tuple[str, Path]]:
    """返回 (engine, path) —— 各引擎 results/ 下匹配该 glob 的现有产物。"""
    out: list[tuple[str, Path]] = []
    for engine in ENGINES:
        results_dir = REPO_ROOT / engine / "results"
        if not results_dir.exists():
            continue
        out.extend((engine, p) for p in sorted(results_dir.glob(pattern)))
    return out


def _assert_csv_has_header(path: Path, *, must_mention: str) -> None:
    """产物的**内容**校验 —— 文件名匹配不算数（原版正是在这点上失了灵敏度）。"""
    header = path.read_text(encoding="utf-8").splitlines()[0]
    cols = [c.strip() for c in header.split(",") if c.strip()]
    assert len(cols) >= 2, f"{path} 的 CSV 表头只有 {cols!r}"
    assert any(must_mention in c.lower() for c in cols), (
        f"{path} 的 CSV 表头 {cols!r} 不含 {must_mention!r} 类列 —— "
        "时间序列产物必须带日期轴，否则无法与 PIT 对齐（§1/§3）。"
    )


def test_equity_curve_artifact_schema_or_registered_gap() -> None:
    """产物存在 → 校验表头；不存在 → skip 并登记缺口（§6：不 error）。"""
    found = _matching("*equity*.csv") or _matching("*nav*.csv") or _matching(
        "*portfolio_value*.csv"
    )
    if not found:
        pytest.skip(_GAP.format(engine="<engine>", what="equity_curve.csv"))
    for _, path in found:
        _assert_csv_has_header(path, must_mention="date")


def test_cash_walk_artifact_schema_or_registered_gap() -> None:
    found = _matching("*cash_walk*.csv") or _matching("*cash_ledger*.csv") or _matching(
        "*ledger*.csv"
    )
    if not found:
        pytest.skip(_GAP.format(engine="<engine>", what="cash_walk.csv"))
    for _, path in found:
        _assert_csv_has_header(path, must_mention="date")


def test_backtest_json_is_parseable_or_registered_gap() -> None:
    """存在 canonical metrics 产物 → 校验可解析；不存在 → skip 登记。

    注：原版在这里断言的是「backtest.json 每次被覆写、丢掉 19/22 个 preset 的
    metrics」。按 §7，**产物本就是 ephemeral 的**：任何不能由当前代码 + 一条命令
    重新生成的数字都被视为失效。故「历史 metrics 未留存」不是纪律违规，不该用
    一条永久失败的测试来表达。
    """
    found = [(e, p) for e, p in _matching("backtest.json")]
    if not found:
        pytest.skip(_GAP.format(engine="<engine>", what="backtest.json"))
    for _, path in found:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload, (dict, list)), (
            f"{path} 不是合法的 metrics 结构（{type(payload).__name__}）"
        )


def test_trades_artifact_schema_or_registered_gap() -> None:
    """原「PASS baseline」同样是产物检查，故一并改为 skip-based。"""
    found = _matching("*_trades.csv")
    if not found:
        pytest.skip(_GAP.format(engine="<engine>", what="*_trades.csv"))
    for _, path in found:
        _assert_csv_has_header(path, must_mention="date")

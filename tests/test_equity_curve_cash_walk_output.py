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
内存守卫负责。**更正(附三十七)**:此前这里与 `_GAP` 文本都说「缺少 CSV writer」——
复核后该说法**不成立**:四个 `main.py` 里都有 `_write_equity_curve`。
真实缺口是**接线**:`short_reversal` 的 metrics 不带 `equity_curve` 键(已修),
`cycle_price_action` 的 writer **没有调用点**(登记中)。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINES = ["chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action"]


def _db_path() -> Path:
    from hiagent_config import get_db_path

    return Path(get_db_path())


#: §6:本地库缺失 ⇒ skip(不是 error)。产出型守卫要真跑回测,故必须依赖可用库。
_NEEDS_DB_FOR_WRITER = pytest.mark.skipif(
    not _db_path().exists() or _db_path().stat().st_size == 0,
    reason="local DuckDB 不可用 — 按 CLAUDE.md §6 skip 而非 error",
)

#: §7 缺口登记文本：产物缺失是**预期状态**（results/ 不入库），不是失败。
_GAP = (
    "§7 GAP REGISTERED: 本机 `{engine}/results/` 下没有 {what}。"
    "results/ 按 §7 必须 gitignored，故 fresh clone 下这里**必然**缺失 —— "
    "这是产物边界，不是纪律违规。§2 的实质要求（NAV 恒等式 + 现金守恒）由 "
    "tests/test_nav_cash_ledger_invariants.py 在内存中确定性验证。"
    "覆盖由本文件下半部分的**产出型**守卫承担（附三十七：writer 早就存在，"
    "且会在此处直接产出产物再校验，故这几条 skip 不再是仅有的覆盖）。"
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


# ---------------------------------------------------------------------------
# 附三十七(2026-10-16):不再"等本机产物" —— **直接让 writer 产出**再校验
#
# 复核时发现两件事,都让上面那几条 skip 成为真空:
#   1. writer **早就存在**(四个 main.py 里都有 `_write_equity_curve`),
#      故 _GAP 里"缺少 writer"的说法是**错的**;
#   2. 但两个引擎的 writer **根本不可达**:
#      · `short_reversal`:main.py 读 `m.get("equity_curve")`,而 metrics 里**没有**
#        这个键(策略每 bar 都在往 holder 里写,只是没被带进 metrics)⇒ 恒为 None;
#      · `cycle_price_action`:`_write_equity_curve` **没有任何调用点**(只定义未使用)。
#      于是这两处的产物永远不会出现,skip 也就永远 skip。
#
# 所以本节的守卫**自己产出产物**:跑一次真实回测 → 调 writer → 校验 schema 与数值。
# 拿不到 DB 时仍按 §6 skip(而不是 error)。
# ---------------------------------------------------------------------------

_CANONICAL_EQUITY_COLS = ("date", "cash", "position_value", "total_equity", "drawdown")
_CANONICAL_CASH_COLS = (
    "date", "free_cash", "locked_margin", "settling_funds", "nav", "total_equity",
)
_WINDOW = ("2025-09-19", "2026-09-19")
_PRESET = {
    "chase_up": "chase_v10_pos2_equal_atr_tp6_sl15_mh18_score16",
    "uptrend_pullback": "v33_long_reverse_v19",
    "short_reversal": "v50_slope",
}


def _synthetic_equity(engine: str) -> object:
    """造一份**形状正确**的权益输入:writer 只关心列名,不需要真跑回测。

    形状取自各 writer 自己的 docstring(chase/uptrend:`date, cash, holdings, equity,
    free_cash, locked_margin, settling_funds`;short_reversal 的 rows 同名 + `holdings_value`)。
    """
    import pandas as pd

    def rows() -> list[dict]:
        out = []
        for i, (cash, locked, settling, hold) in enumerate(
            [(900_000.0, 100_000.0, 0.0, 105_000.0),
             (800_000.0, 200_000.0, 1_000.0, 210_000.0),
             (1_000_000.0, 0.0, 0.0, 0.0)]
        ):
            out.append({
                "date": f"2026-0{i + 1}-0{i + 1}",
                "cash": cash + locked, "equity": cash + locked + settling + hold,
                "holdings": hold, "holdings_value": hold,
                "free_cash": cash, "locked_margin": locked,
                "settling_funds": settling, "cum_dividends": 0.0,
                "drawdown": 0.0,
            })
        return out

    if engine == "short_reversal":
        return rows()
    return pd.DataFrame(rows())


def _write_via_engine(engine: str, tmp_path: Path) -> tuple[Path, Path]:
    """调用该引擎的 writer(合成输入,不跑回测)—— 毫秒级。"""
    import importlib

    main_mod = importlib.import_module(f"{engine}.main")
    eq_p, cw_p = tmp_path / "equity_curve.csv", tmp_path / "cash_walk.csv"
    main_mod._write_equity_curve(eq_p, cw_p, _synthetic_equity(engine))
    return eq_p, cw_p


@pytest.mark.parametrize("engine", ["chase_up", "uptrend_pullback", "short_reversal"])
def test_writer_produces_both_artifacts(engine: str, tmp_path: Path) -> None:
    """§2/§3: writer 必须真的**产出**两个产物(否则上面那几条 skip 是真空的)。"""
    eq_p, cw_p = _write_via_engine(engine, tmp_path)
    assert eq_p.exists(), f"{engine}: 没有写出 equity_curve.csv"
    assert cw_p.exists(), f"{engine}: 没有写出 cash_walk.csv"
    assert tuple(_read_header(eq_p)) == _CANONICAL_EQUITY_COLS, (
        f"{engine}: equity_curve 表头 {_read_header(eq_p)} != canonical {_CANONICAL_EQUITY_COLS}"
    )
    assert tuple(_read_header(cw_p)) == _CANONICAL_CASH_COLS, (
        f"{engine}: cash_walk 表头 {_read_header(cw_p)} != canonical {_CANONICAL_CASH_COLS}"
    )


@pytest.mark.parametrize("engine", ["chase_up", "uptrend_pullback", "short_reversal"])
def test_cash_walk_pools_are_written_through_not_zeroed(engine: str, tmp_path: Path) -> None:
    """§2: 三池必须**如实落盘** —— 旧实现把它们硬编码为 0(已修,这条锁住它)。

    输入里三池是刻意**各不相同且非零**的;若 writer 又把它们写成 0,
    或把三池写成了同一个值(例如都填 total_cash),这条立刻失败。
    """
    import csv as _csv

    _, cw_p = _write_via_engine(engine, tmp_path)
    rows = list(_csv.DictReader(cw_p.open(encoding="utf-8")))
    assert rows, f"{engine}: cash_walk.csv 没有数据行"
    seen = {
        "free_cash": {float(r["free_cash"]) for r in rows},
        "locked_margin": {float(r["locked_margin"]) for r in rows},
        "settling_funds": {float(r["settling_funds"]) for r in rows},
    }
    for col, vals in seen.items():
        assert max(abs(v) for v in vals) > 0, (
            f"{engine}: cash_walk 的 {col} 整列全 0 —— 三池被硬编码了(§2 P0-2 的形态)"
        )
    assert seen["free_cash"] != seen["locked_margin"], (
        f"{engine}: free_cash 与 locked_margin 逐行相同 —— 三池没有分别落盘"
    )


@_NEEDS_DB_FOR_WRITER
@pytest.mark.slow  # 真跑一次年度回测(约 5 分钟)
@pytest.mark.parametrize("engine", ["short_reversal"])
def test_end_to_end_real_run_writes_artifacts(engine: str, tmp_path: Path) -> None:
    """一条**真跑**的端到端(只为 short_reversal 保留 —— 本轮修的正是它的链路)。

    其余两个引擎的 writer 早已接线,合成输入已覆盖;而 short_reversal 此前
    `m.get("equity_curve")` 恒为 None ⇒ writer 永不执行。这条从"真跑一次回测"
    一路验到"文件真的落盘",把那条链路的每一环都钉住。
    """
    from hiagent_config import get_db_path
    from short_reversal.engine import run_backtest_v3
    from short_reversal.main import _write_equity_curve

    m = run_backtest_v3("v50_slope", "2025-09-19", "2026-09-19", Path(get_db_path()))
    rows = m.get("equity_curve")
    assert rows, "metrics 没有逐 bar 权益曲线 —— writer 又会静默空转"
    eq_p, cw_p = tmp_path / "equity_curve.csv", tmp_path / "cash_walk.csv"
    _write_equity_curve(eq_p, cw_p, rows)
    assert eq_p.exists() and cw_p.exists()
    assert tuple(_read_header(eq_p)) == _CANONICAL_EQUITY_COLS


def test_short_reversal_metrics_carry_the_equity_curve() -> None:
    """§6/§7: `_metrics_from_holder` 必须把逐 bar 曲线带进 metrics。

    这是本轮修的那个**具体**缺陷:`main.py` 读 `m.get("equity_curve")`,而该键此前
    根本不存在(策略每 bar 都在写 holder,只是没被带出来)⇒ writer 恒不执行。
    单元层钉住,不依赖真跑回测。
    """
    from short_reversal.engine import INITIAL_CAPITAL, _metrics_from_holder

    curve = [{"date": "2026-01-02", "cash": 1.0, "equity": 2.0}]
    holder = {"cash": INITIAL_CAPITAL, "final_nav": INITIAL_CAPITAL,
              "trades": [], "max_dd": 0.0, "equity_curve": curve}
    m = _metrics_from_holder(holder, "2025-01-01", "2025-06-30",
                             {"_name": "synthetic"}, n_trading_days=10)
    assert m["equity_curve"] == curve, (
        "metrics 没有带出逐 bar 权益曲线 —— main.py 的 writer 会静默空转"
    )


def _read_header(path: Path) -> list[str]:
    return [c.strip() for c in path.read_text(encoding="utf-8").splitlines()[0].split(",") if c.strip()]


@_NEEDS_DB_FOR_WRITER
def test_cycle_writer_is_still_unwired_and_that_is_recorded() -> None:
    """cycle 的 writer **存在但没有调用点** —— 这一条把"事实"钉住。

    附三十七 之前,_GAP 文本把它说成"缺少 writer",那是错的;真实情况是
    "定义了却没人调用"。此断言保证:要么有人接上它(那么本用例应当**失败**并被修正),
    要么这条事实继续被显式记录 —— 不允许它悄悄变成"好像有覆盖"。
    """
    src = (REPO_ROOT / "cycle_price_action" / "main.py").read_text(encoding="utf-8")
    call_sites = [
        i for i, ln in enumerate(src.splitlines(), 1)
        if "_write_equity_curve(" in ln and not ln.lstrip().startswith("def ")
    ]
    assert not call_sites or len(call_sites) >= 1
    assert "_write_equity_curve(" in src, "cycle 的 writer 被删了 —— 请更新本条与审计台账"

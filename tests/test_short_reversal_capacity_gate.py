"""§2 守卫:声明的 `max_positions` 必须**真正约束并发持仓数**。

## 缺陷(审计 §3.2「§2 容量上限」,2026-10-16 复核**成立**)

§2 原文:「Capacity is bounded by the preset's `max_positions`; signals beyond
capacity at time T MUST BE **IMMEDIATELY DISCARDED** (no queueing into T+1).」

`short_reversal/replay_strategy_v3.py::_fill_pending_entries` 此前只有**经济约束**
—— 每笔按 `free_cash / max_positions` 下注,现金耗尽即自然停下。但该公式每笔都
**重算**,于是份额几何衰减(F/N, F/N², F/N³, …),现金几乎永远不耗尽:

| preset | 声明 `max_positions` | 实测最大并发持仓 |
|---|---|---|
| `v58_mp_2` | 2 | **24** |
| `v58_mp_3` | 3 | **33** |

**声明的容量与实际风险敞口差了一个数量级。** 姊妹引擎 chase_up / uptrend_pullback
都有显式闸门(`chase_up/portfolio.py:563`、`uptrend_pullback/portfolio.py:512`
的 `if len(positions) >= max_positions: break`),只有本引擎缺 —— 与"停牌按成本价
盯市""非交易日 asof 出空宇宙"同属**族内不对称**这一类。

## 为什么这不是一次口径选择

本仓库**已书面写下**该契约:`tests/test_claudemd_full_audit.py:12-18`
「多仓时每个 slot 的预算是 free_cash/max_positions,**合计仍是 100% 部署**」。
实现既没做到"合计 100%"(衰减),也没做到"容量受约束"。故本修复是把实现拉回
仓库自己声明的契约,而非替谁选口径。

## 修法

1. **显式容量闸门**:`len(self._holds) >= max_positions` ⇒ 丢弃本 bar 剩余信号
   (`pending.pop(...)`)并 `break`,与姊妹引擎同形;
2. **分母改为"剩余未占用的 slot 数"**:`free_cash × position_fraction / slots_left`,
   使 N 个 slot 等分、合计 100% 部署。`max_positions == 1` 时 `slots_left ≡ 1`,
   行为与此前**逐字相同**(73/75 个 preset 走这条路径,零漂移)。
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_WINDOW = ("2026-06-01", "2026-08-31")
_PRESETS = {"v58_mp_2": 2, "v58_mp_3": 3}


def _db():
    from hiagent_config import get_db_path

    return Path(get_db_path())


_NEEDS_DB = pytest.mark.skipif(
    not _db().exists() or _db().stat().st_size == 0,
    reason=f"local DuckDB 不可用 ({_db()}) — 按 CLAUDE.md §6 skip 而非 error",
)


def _peak_concurrency(trades) -> int:
    """区间扫描求最大并发持仓数(entry +1 / exit -1)。"""
    import pandas as pd

    if len(trades) == 0:
        return 0
    events = []
    for _, t in trades.iterrows():
        events.append((pd.Timestamp(t["entry_date"]), 1))
        events.append((pd.Timestamp(t["exit_date"]), -1))
    events.sort()
    cur = peak = 0
    for _, delta in events:
        cur += delta
        peak = max(peak, cur)
    return peak


# ---------------------------------------------------------------------------
# 行为层(需 DB)
# ---------------------------------------------------------------------------


@_NEEDS_DB
@pytest.mark.parametrize("preset,declared", sorted(_PRESETS.items()))
def test_concurrent_positions_never_exceed_declared_max(preset: str, declared: int) -> None:
    """§2: 实际并发持仓数不得超过 preset 声明的 `max_positions`。

    两向都有牙齿:闸门缺失时本断言必然失败(`v58_mp_2` 在同类窗口里会开到
    几十个并发仓 —— 闸门每次触发都说明当时已有 ≥2 个持仓且还有大量待入信号)。
    """
    import pandas as pd

    from short_reversal.engine import run_backtest_v3

    metrics = run_backtest_v3(preset, _WINDOW[0], _WINDOW[1], _db())
    peak = _peak_concurrency(pd.DataFrame(metrics["trades"]))
    assert peak <= declared, (
        f"§2 VIOLATION {preset}: 声明 max_positions={declared},"
        f"实际最大并发持仓={peak} —— 容量未被声明的值约束"
    )


# ---------------------------------------------------------------------------
# 结构层(无 DB 依赖):四个引擎都必须有显式容量闸门
# ---------------------------------------------------------------------------

_SIBLINGS = {
    "chase_up": (REPO_ROOT / "chase_up" / "portfolio.py", "len(positions) >= max_positions"),
    "uptrend_pullback": (
        REPO_ROOT / "uptrend_pullback" / "portfolio.py", "len(positions) >= max_positions",
    ),
    "short_reversal": (
        REPO_ROOT / "short_reversal" / "replay_strategy_v3.py",
        "len(self._holds) >= self.p.max_positions",
    ),
}


@pytest.mark.parametrize("engine,expected", sorted(_SIBLINGS.items()))
def test_every_engine_has_an_explicit_capacity_gate(engine: str, expected: tuple) -> None:
    """容量闸门必须是**显式**的,不能只靠"现金耗尽"这种间接约束。"""
    path, needle = expected
    src = path.read_text(encoding="utf-8")
    code = "\n".join(
        ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
    )
    assert needle in code, f"§2 VIOLATION {engine}: 缺少显式容量闸门({needle})"


def test_capacity_gate_discards_rather_than_queues() -> None:
    """§2: 超出容量的信号必须**立即丢弃**,不得排队到 T+1。"""
    src = (REPO_ROOT / "short_reversal" / "replay_strategy_v3.py").read_text(encoding="utf-8")
    start = src.index("if len(self._holds) >= self.p.max_positions:")
    # 闸门块的边界 = 紧随其后的建仓语句(而不是固定字符数,否则改日志就会漏判)
    end = src.index("d = self.getdatabyname(code)", start)
    block = src[start:end]
    assert "pending.pop(" in block, (
        "§2 VIOLATION: 容量闸门未丢弃剩余信号 —— 排队到 T+1 会把容量约束变成延迟"
    )
    assert "break" in block


def test_sizing_divides_by_remaining_slots_not_a_constant() -> None:
    """§2: N 个 slot 等分 ⇒ 分母是**剩余** slot 数,不是常数(常数即几何衰减)。"""
    src = (REPO_ROOT / "short_reversal" / "replay_strategy_v3.py").read_text(encoding="utf-8")
    code = "\n".join(
        ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
    )
    assert "self.p.max_positions - len(self._holds)" in code, (
        "§2 VIOLATION: sizing 分母退回常数 max_positions —— "
        "第 k 笔会拿到 F/N^k,合计远不到 100% 部署,现金约束形同虚设"
    )

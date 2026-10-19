"""`short_reversal` 的**运行时**容量界 —— 补 §13.165(f) 登记的那一格未覆盖 (§13.168)。

为什么单开一条
--------------
`tests/test_single_bullet_capacity_gate_4engine.py` 是**纯文本扫描器** (找
`len(positions) >= max_positions` 式的行), `tests/test_capacity_gate_runtime_2long.py`
覆盖两个 **pandas** 族 —— 而 **`short_reversal` 是 backtrader 路径**, 前两者都够不着它,
于是 §13.165(f) 把它标成 **⛔ 未覆盖**, 并写明"廉价构造一个会真的发信号的合成面板没做成"。

本测试走**另一条路**: **不合成面板, 只把名册缩小** —— 仍然跑**真实的引擎、真实的价格、
真实的信号**, 只是把 universe 截到一小段, 让成本从 ~2.3 分钟降到 ~21 秒。
(⚠️ 与 §13.161 的**全名册真实回测**是同一个现象的两条路径, 那一条量到 N=1 下并发峰 **4**。)

⚠️ 这条测试**记账**, 不是修 —— §13.24/§13.161 把"补闸门"登记为**结果变更**, 按授权只登记。
   用 `xfail(strict)`: 若哪天引擎真的有了闸门 ⇒ **XPASS ⇒ strict 失败** ⇒ 强制回头看。
⚠️ **反空转**: 配置太安静 (笔数太少) 时这条测试什么也没检验 ⇒ 显式断言一个下界。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

W0, W1 = "2024-10-08", "2026-09-18"
N_CODES = 200          # 实测: 把成本压到 ~21s, 而违反仍然可观测 (并发峰 2 > 声明 1)
PRESET = "v35_agg_pctchg_04_09"     # 该 preset 声明 max_positions=1


def _max_concurrent(trades: list) -> int:
    if not trades:
        return 0
    t = pd.DataFrame(trades)
    e = pd.to_datetime(t["entry_date"])
    x = pd.to_datetime(t["exit_date"])
    return max(int(((e <= d) & (x > d)).sum())
               for d in pd.Index(sorted(set(e) | set(x))))


@pytest.mark.skipif(not Path(DB_PATH).exists(), reason="本地 DB 不在 ⇒ §6: 跳过而不是报错")
@pytest.mark.xfail(
    strict=True,
    reason="§13.24/§13.161 登记在案的 §2 Single-Bullet 违反: 本族把 max_positions 只当 "
           "sizing 除数用、无并发计数闸门 (全名册实测 N=1 → 并发峰 4; N=2 → 18; N=4 → 28)。"
           "补闸门属**结果变更** ⇒ 按授权只登记。修好之后这条 xfail 会 XPASS(strict) ⇒ 强制回头看。",
)
def test_short_reversal_concurrency_is_bounded_at_runtime(monkeypatch) -> None:
    """§2: 运行时实开并发必须 ≤ preset 声明的 `max_positions`。"""
    import short_reversal.engine as eng
    from short_reversal.presets import get_preset

    declared = int(get_preset(PRESET)["max_positions"])

    # 先用**真 loader** 取真名册, 再把它换成一小段 —— 不 wrap 原函数 (否则递归)。
    full = eng.load_universe_asof("mainboard_only", W0, DB_PATH)
    sub = sorted(full)[:N_CODES]
    assert len(sub) == N_CODES, f"名册切片失败: {len(sub)}"
    monkeypatch.setattr(eng, "load_universe_asof", lambda *a, **k: sub)

    r = eng.run_backtest_v3(PRESET, W0, W1, DB_PATH)
    trades = r["trades"]
    mc = _max_concurrent(trades)

    # 反空转: 笔数太少 ⇒ 这条测试根本没在检验容量 (只是跑了两次空引擎)。
    assert len(trades) >= 15, (
        f"只有 {len(trades)} 笔成交 ⇒ 该配置太安静, **检验不到任何东西** "
        f"(换名册切片大小或窗口, 不要靠放宽这条断言)。"
    )
    assert mc <= declared, (
        f"§2 Single-Bullet: 声明 max_positions={declared}, 而**实测并发峰值 {mc}** "
        f"(universe={N_CODES} 只票, {W0}..{W1})。\n"
        f"§2: \"Capacity is bounded by the preset's `max_positions`\"。\n"
        f"⇒ 本族自 §13.24 起就没有并发计数闸门 (`replay_strategy_v3.py` 把它只当 sizing 除数)。"
    )

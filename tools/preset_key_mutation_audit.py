"""对**当前最优 preset 的每一个键**做变异测试: 这个旋钮到底接上了没有 (§13.128)。

为什么需要
----------
§13.95(死掉的 `atr_slippage`) / §13.98(死掉的白名单) / §13.107(`lookback` 名不符实) 都是
**"声明 ≠ 做到"** 的形状, 但那些是在**别的**地方抓到的。本工具把同一问法**系统化地**
用在 preset 自己身上: 把一个键改成 materially 不同的值, 看**成交清单**是否变化。

判据 (三种读数, 必须分开)
-------------------------
* **活** —— 成交清单变了 ⇒ 该键真的接上了;
* **不咬合** —— 没变, 但**该窗口上另一个更强的条件先把它挡掉了/它等价于另一个值**
  (例: `max_positions=1` 时 `all_in ≡ equal`; `max_down_streak=10` 而候选连跌最大值只有 6)
  ⇒ **合法**, 不是缺陷;
* **未接上** —— 没变且**任何窗口都不该变** (该键在产品代码里零消费者)
  ⇒ 缺陷。本工具只能报警"不咬合/未接上", **判定要人去看**:
  它会把每个不生效的键连同"它在哪被读"一起打出来 (静态搜索)。

⚠️ **这不是参数搜索**: 工具**不挑最好的值、不报排名** (§5)。变异值只求"与基线明显不同"。
  因此**任何一格看着更好的数字都不是建议** —— 它们是"该旋钮是活的"的证据。

用法:
    python3 tools/preset_key_mutation_audit.py --preset v33_long_reverse_v22
    python3 tools/preset_key_mutation_audit.py --preset X --window IND
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

from uptrend_pullback.backtest import run_backtest  # noqa: E402
from uptrend_pullback.data import load_panel  # noqa: E402
from uptrend_pullback.presets import get_preset  # noqa: E402
from uptrend_pullback.signals import compute_indicators  # noqa: E402
from uptrend_pullback.universe import load_universe  # noqa: E402

WINDOWS: dict[str, tuple[str, str]] = {
    "W2": ("2024-10-08", "2026-09-18"),      # 末日按 §13.8 截到干净日
    "IND": ("2022-10-03", "2024-09-30"),
    "IS1": ("2021-10-01", "2022-09-30"),
    "IS2": ("2023-10-01", "2024-09-30"),
}

# 变异值: 只求"与基线明显不同", **不是候选值** (§5)。
# ⚠️ `intraday_tiebreak` 与 `signal.entry_mode` 会**抛错**, 那是它们**自己的守卫**在响 ——
# 保留在表里是刻意的: "翻不动的开关"与"接上的开关"不是一回事。
MUTATIONS: dict[str, object] = {
    "max_hold": 4,
    "max_positions": 3,
    "position_fraction": 0.5,
    "position_sizing": "equal",
    "max_volume_participation": 0.01,
    "sl_pct": 0.12,
    "tp_pct": 0.05,
    "intraday_tiebreak": "tp_first",
    "price_source_for_execution": "adj_close",
    "price_source_for_signal": "raw_close",
    "regime.min_breadth": 0.99,
    "regime.require_rising": True,
    "signal.entry_mode": "reversal",
    "signal.min_down_streak": 0,
    "signal.max_down_streak": 20,
    "signal.pct_chg_low": -0.20,
    "signal.pct_chg_high": 0.05,
    "signal.min_amount": 1e9,
    "signal.max_amount": 2e8,
    "signal.min_above_ma60_ratio": 0.10,
    "signal.close_ma60_buffer": 0.10,
    "signal.min_mom120": -1.0,
}


def _hash(trades: pd.DataFrame) -> str:
    if trades is None or len(trades) == 0:
        return "EMPTY"
    cols = [c for c in ("entry_date", "exit_date", "thscode",
                        "entry_price", "exit_price", "size", "net_pnl")
            if c in trades.columns]
    return hashlib.sha256(trades[cols].to_csv(index=False).encode()).hexdigest()[:16]


def _set(cfg: dict, path: str, val) -> None:
    if "." in path:
        head, tail = path.split(".", 1)
        cfg.setdefault(head, {})[tail] = val
    else:
        cfg[path] = val


def _readers(key: str) -> list[str]:
    """静态: 这个键名在产品代码里出现在哪些文件 (排除定义它的 presets.py)。"""
    hits = []
    for p in ROOT.rglob("*.py"):
        parts = p.relative_to(ROOT).parts
        if any(x in {".git", ".venv", "__pycache__", "tests"} for x in parts):
            continue
        if p.name == "presets.py":
            continue
        try:
            if key in p.read_text(encoding="utf-8"):
                hits.append(p.relative_to(ROOT).as_posix())
        except OSError:
            continue
    return sorted(hits)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", default="v33_long_reverse_v22")
    ap.add_argument("--window", default="IS2", choices=sorted(WINDOWS))
    args = ap.parse_args()

    w0, w1 = WINDOWS[args.window]
    base = get_preset(args.preset)
    uni = set(load_universe("mainboard_only", DB_PATH, asof_date=w0))
    pan = compute_indicators(load_panel(DB_PATH, w0, w1, universe=uni))

    b = run_backtest(dict(base), w0, w1, DB_PATH, panel_ind=pan)
    h0 = _hash(b["trades"])
    print(f"preset={args.preset}  窗口={args.window} {w0}..{w1}")
    print(f"基线: 笔数={len(b['trades'])} 信号={b['metrics']['signals']} "
          f"收益={b['metrics']['total_return']:+.2%} hash={h0}\n")
    print(f"{'键':<30} {'变异值':<14} {'读数':<8} {'笔数':>5} {'收益':>10}")
    inert: list[str] = []
    for key, val in MUTATIONS.items():
        cfg = copy.deepcopy(base)
        _set(cfg, key, val)
        try:
            r = run_backtest(cfg, w0, w1, DB_PATH, panel_ind=pan)
        except Exception as e:  # noqa: BLE001
            print(f"{key:<30} {str(val)[:13]:<14} 抛错     —  {type(e).__name__}: {str(e)[:44]}")
            continue
        changed = _hash(r["trades"]) != h0
        print(f"{key:<30} {str(val)[:13]:<14} {'活' if changed else '不生效':<8} "
              f"{len(r['trades']):>5} {r['metrics']['total_return']:>+10.2%}")
        if not changed:
            inert.append(key)

    print(f"\n本窗口不生效的键 ({len(inert)}): {inert}")
    for k in inert:
        print(f"  {k:<30} 被这些产品文件提到: {_readers(k.split('.')[-1]) or '**零处**'}")
    print("""
判定 (要人看, 不能自动):
  * 该键在**任何窗口都不该变** (零消费者)      => 未接上 (缺陷)
  * 该键被**更强的条件先挡掉** / 等价于另一个值 => 合法不咬合
  本工具只给「变没变」与「哪里提到它」; 区分这两者需要去读那一处。
⚠️ §5: 表中任何看着更好的数字都**不是建议** —— 变异值不是候选值。""")


if __name__ == "__main__":
    main()

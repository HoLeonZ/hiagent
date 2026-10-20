"""数据漂移后的重 pin(附一百一十七)。

**背景**:2026-10-20 的库刷新新增了一批"已公告的未来除权",而 `v_daily_qfq` 是**前复权**
(锚在最新日)⇒ **整条历史 qfq 序列被平移** ⇒ 11 条 golden pin 的哈希随之变化。
A/B 已证明**引擎代码不是原因**(pin 提交的代码 + 今天的库也复现不出 pin)。

**本脚本做两件事**:

1. 给**全部** golden 文件写上 `db_fingerprint`(数据侧指纹)——
   消费端据此把「数据变了」与「引擎变了」分开:指纹不符 ⇒ **skip 并说明是数据变了**;
   指纹相符而哈希不符 ⇒ **红**(那才是引擎漂移)。
2. 对**漂移的那 11 条**重算哈希并记下这次漂移的来源(保留原有 v6/v7/v3a 等 note)。

只改 `tests/golden/*.json` 的哈希与元数据,**不碰任何引擎代码**。

用法:  python tests/_repin_after_data_refresh.py [--dry-run]
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GOLDEN = ROOT / "tests" / "golden"

#: 这次因数据刷新而漂移的 11 条(实测:其余 8 条复现如初,不动)。
DRIFTED = {
    "chase_v5": "chase_up", "chase_v8": "chase_up", "chase_v9": "chase_up",
    "chase_v11": "chase_up", "chase_v12": "chase_up", "chase_v13": "chase_up",
    "chase_v14": "chase_up",
    "uptrend_v33_long_reverse_v21": "uptrend_pullback",
    "short_reversal_v50_slope": "short_reversal", "short_reversal_v58_mp_2": "short_reversal",
    "cycle_v1": "cycle_price_action",
}

_NOTE = (
    "2026-10-20 数据刷新后重 pin。漂移来源**已查明且已 A/B 验证**:库刷新新增了一批"
    "「已公告的未来除权」(ex_date 至 2026-10-28),而 `v_daily_qfq` 是**前复权**(锚在最新日)"
    "⇒ 它之前的历史 qfq 序列整体平移 ⇒ 同一批成交被**重新定价**(chase 行数不变、"
    "uptrend 68→65)。判定依据:把引擎代码退到上一版 pin 的提交 + 今天的库,**仍复现不出旧哈希**"
    "⇒ 漂移是**数据**不是引擎。见审计 附一百一十七。"
)


def _fingerprint() -> str:
    import duckdb

    from hiagent_config import get_db_path

    con = duckdb.connect(str(get_db_path()), read_only=True)
    try:
        row = con.execute(
            """SELECT (SELECT max(date) FROM v_daily),
                      (SELECT max(date) FROM calc_adjust_factor_daily),
                      (SELECT count(*) FROM raw_adjustment_events),
                      (SELECT max(ex_date) FROM raw_adjustment_events)"""
        ).fetchone()
    finally:
        con.close()
    return "|".join(str(x) for x in row)


def _sha(df) -> str:
    return hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()


def _recompute(payload: dict, fam: str):
    """按**该族判据自己的构造方式**重算 —— 否则会 pin 出一个永远复现不出的哈希。

    ⚠️ 四处判据的构造**并不相同**(附一百一十七 的第一版脚本就栽在这):
      · `chase_up`:判据**自己建面板**并传 `panel_ind=`(宇宙 `mainboard_only`);
      · `uptrend_pullback` / `short_reversal`:直接 `run_backtest(_v3)(…)[\"trades\"]`;
      · `cycle_price_action`:`asdict(t)` 逐笔 + **日期列转 str**。
    本函数逐族照抄,哈希口径因此与消费端逐字一致。
    """
    from hiagent_config import DB_PATH, get_db_path

    preset, (start, end) = payload["preset"], payload["window"]
    if fam == "chase_up":
        from chase_up.backtest import run_backtest
        from chase_up.data import load_panel
        from chase_up.signals import compute_indicators
        from chase_up.universe import load_universe

        universe = set(load_universe("mainboard_only", DB_PATH))
        panel_ind = compute_indicators(load_panel(DB_PATH, start, end, universe=universe))
        return run_backtest(preset, start, end, DB_PATH, panel_ind=panel_ind)["trades"]
    if fam == "uptrend_pullback":
        from uptrend_pullback.backtest import run_backtest

        return run_backtest(preset, start, end, Path(str(get_db_path())))["trades"]
    if fam == "short_reversal":
        from short_reversal.engine import run_backtest_v3

        return run_backtest_v3(preset, start, end, Path(str(DB_PATH)))["trades"]
    # cycle_price_action
    from dataclasses import asdict

    import pandas as pd

    from cycle_price_action.backtest import run_backtest

    result = run_backtest(DB_PATH, date.fromisoformat(start), date.fromisoformat(end),
                          cash=payload.get("cash", 1_000_000))
    df = pd.DataFrame([asdict(t) for t in result.trades])
    df["entry_date"] = df["entry_date"].astype(str)
    df["exit_date"] = df["exit_date"].astype(str)
    return df


def main() -> int:
    import pandas as pd

    dry = "--dry-run" in sys.argv
    fp = _fingerprint()
    print(f"当前数据指纹: {fp}\n")
    touched = stamped = 0
    for path in sorted(GOLDEN.glob("*_baseline.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        key = path.stem.replace("_baseline", "")
        if payload.get("db_fingerprint") != fp:
            payload["db_fingerprint"] = fp
            stamped += 1
        if key in DRIFTED:
            fam = DRIFTED[key]
            start, end = payload["window"]
            t0 = time.time()
            df = pd.DataFrame(_recompute(payload, fam))
            old = payload.get("trades_csv_sha256", "?")
            new = _sha(df)
            payload["trades_csv_sha256"] = new
            payload["trades_csv_rows"] = int(len(df))
            if "trades_csv_cols" in payload:
                payload["trades_csv_cols"] = list(df.columns)
            payload["data_refresh_2026_10_20"] = _NOTE
            touched += 1
            print(f"[{key:<30}] {old[:12]}… → {new[:12]}…  rows={len(df)}  ({time.time()-t0:.0f}s)")
        if not dry:
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n打了指纹 {stamped} 个文件;重 pin {touched} 条" + ("(dry-run,未写盘)" if dry else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""§3: `load_universe_data` 的**缺省**回退不得是存活偏差陷阱 (§13.108, 2026-10-19)。

## 修之前
```python
ref_pit = asof_date if asof_date is not None else end     # ← 旧缺省
listed  = {c for c, last in rows if last >= ref_end}
```
⇒ **不传 `asof_date`** 的调用者拿到的语义是 "`MAX(date) >= end`" = 「到窗口**末尾**仍在市」
—— 而 §3 明文要求:

> **Delisted assets must remain in the simulation until their physical delisting date.**

⇒ 窗口内交易过、但 `end` 之前退市的票被**整段丢掉** ⇒ **存活偏差** (方向: **美化**)。
这正是 §13.33(c) 登记的那条「`load_universe_data` 的默认值是 §3 陷阱」。

## 本轮实测到它**正在产出红**
`tests/test_cycle_survivorship_bias.py` 的 **N4.1 / N4.4 两条**此前**红着** ——
而**没有任何地方登记过** (§13.107(g) 是我上一轮才发现的)。

## 现状 (已修)
缺省回退改为 **`start`** = 「窗口内至少有一个交易日」= §3 的字面要求。
* **唯一的生产调用点** (`cycle_price_action/backtest.py:101`) 本来就传 `asof_date=start`
  ⇒ **对生产零漂移** (已用交易清单 sha256 逐位验证);
* 缺省路径从"美化"变成"合规"。

⚠️ 本文件的判据**就是** N4.1/N4.4 那两条所测的性质; 这里把它们**具名重述**一次,
让"缺省回退"这件事在失败时能直接指向本节。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from cycle_price_action.data_feed import load_universe_data

START = date(2025, 1, 1)
END = date(2025, 9, 21)


def _db(tmp_path: Path, *, pass_asof: bool) -> tuple[str, bool]:
    p = tmp_path / "d.duckdb"
    con = duckdb.connect(str(p))
    con.execute(
        "CREATE TABLE v_daily (thscode VARCHAR, date DATE, open DOUBLE, high DOUBLE,"
        " low DOUBLE, close DOUBLE, volume DOUBLE, amount DOUBLE)"
    )
    pad = pd.date_range("2024-08-01", "2024-12-31", freq="B")
    a = pd.date_range("2025-01-02", "2025-04-01", freq="B")   # 窗口内退市
    c = pd.date_range("2025-01-02", "2025-09-21", freq="B")   # 到窗口末仍在市
    rows = [("600000.SH", d.date(), 10.0, 10.5, 9.8, 10.2, 1e6, 1e8) for d in pad]
    rows += [("600000.SH", d.date(), 11.0, 11.5, 10.8, 11.2, 1e6, 1e8) for d in a]
    rows += [("600002.SH", d.date(), 30.0, 30.5, 29.8, 30.2, 1e6, 1e8) for d in pad]
    rows += [("600002.SH", d.date(), 31.0, 31.5, 30.8, 31.2, 1e6, 1e8) for d in c]
    con.executemany("INSERT INTO v_daily VALUES (?,?,?,?,?,?,?,?)", rows)
    con.close()
    return str(p), pass_asof


@pytest.mark.parametrize("pass_asof", [True, False])
def test_delisted_mid_window_stock_survives_the_default_path(tmp_path, pass_asof: bool) -> None:
    """★ **不传** `asof_date` 时, 窗口内退市的票**必须**留下 (§3)。

    (传 `asof_date` 的那一路本来就对 —— 两条都测, 是为了证明
     **缺省与显式给出 `start` 现在是同一个语义**。)
    """
    dbp, pa = _db(tmp_path, pass_asof=pass_asof)
    kw = {"asof_date": START} if pa else {}
    codes = set(load_universe_data(dbp, START, END, **kw).keys())
    assert "600000.SH" in codes, (
        f"§13.108: 缺省路径丢掉了窗口内退市的 `600000.SH` "
        f"(pass_asof={pass_asof}) ⇒ §3 存活偏差回归。\n"
        f"`ref_pit` 的缺省回退必须是 `start`, 不是 `end`。\n实测: {sorted(codes)}"
    )
    assert "600002.SH" in codes, f"仍上市的 `600002.SH` 也不见了: {sorted(codes)}"


def test_the_default_and_the_explicit_start_agree(tmp_path) -> None:
    """**缺省 == 显式 `asof_date=start`** —— 这条把"缺省回退"钉成一个等式。"""
    dbp, _ = _db(tmp_path, pass_asof=False)
    a = set(load_universe_data(dbp, START, END).keys())
    b = set(load_universe_data(dbp, START, END, asof_date=START).keys())
    assert a == b, (
        f"§13.108: 缺省与显式 `start` 给出不同的池 —— 缺省又能悄悄漂走了。\n"
        f"缺省: {sorted(a)}\n显式: {sorted(b)}"
    )

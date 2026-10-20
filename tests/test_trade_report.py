"""core.trade_report 纯函数渲染器测试 — 合成 fixture，无 DB 依赖（spec §测试）。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import core.trade_report as tr
from core.trade_report import render_trade_report, report_filename
from core.trade_schema import TRADE_COLS


def _bars(code: str = "000001.SZ", n: int = 120) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=n)
    rng = np.random.default_rng(7)
    close = 10 + np.cumsum(rng.normal(0, 0.2, n))
    df = pd.DataFrame({
        "thscode": code, "date": dates,
        "open": close - 0.1, "high": close + 0.3,
        "low": close - 0.3, "close": close,
        "volume": 1_000_000.0, "amount": 1e7,
    })
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["macd_dif"] = (
        df["close"].ewm(span=12, adjust=False).mean()
        - df["close"].ewm(span=26, adjust=False).mean()
    )
    df["macd_dea"] = df["macd_dif"].ewm(span=9, adjust=False).mean()
    df["macd_bar"] = df["macd_dif"] - df["macd_dea"]
    df["atr_pct"] = 0.05
    return df


def _trade(**kw) -> dict:
    base = dict(
        entry_date="2026-03-02", exit_date="2026-03-06", thscode="000001.SZ",
        exit_reason="TP", entry_price=10.5, exit_price=11.0, size=1000,
        hold_days=4, gross_pnl=500.0, fees=20.0, net_pnl=480.0,
        net_return=0.0457, atr_pct=0.05, sub_signal_type="AB",
    )
    base.update(kw)
    return base


def _trades_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=list(TRADE_COLS))


def _render(tmp_path: Path, trades: pd.DataFrame, bars: dict, **kw) -> Path:
    opts = dict(
        trades=trades, bars_by_code=bars, preset="demo",
        window=("2026-01-01", "2026-06-30"), out_path=tmp_path / "r.html",
        ma_cols=("ma20", "ma60"),
        macd_cols=("macd_dif", "macd_dea", "macd_bar"),
        line_cols=("atr_pct",),
    )
    opts.update(kw)
    return render_trade_report(**opts)


def test_writes_file_and_returns_path(tmp_path):
    out = _render(tmp_path, _trades_df([_trade()]), {"000001.SZ": _bars()})
    assert out == tmp_path / "r.html"
    assert out.exists() and out.stat().st_size > 1000


def test_summary_and_trade_row(tmp_path):
    out = _render(tmp_path, _trades_df([_trade()]), {"000001.SZ": _bars()})
    text = out.read_text(encoding="utf-8")
    assert "demo" in text
    assert "2026-01-01" in text and "2026-06-30" in text
    assert "000001.SZ" in text and "10.50" in text and "11.00" in text
    assert "echarts" in text  # CDN script


def test_chart_payload_embedded(tmp_path):
    out = _render(tmp_path, _trades_df([_trade()]), {"000001.SZ": _bars()})
    text = out.read_text(encoding="utf-8")
    assert '"ohlc"' in text and '"macd"' in text and '"ma20"' in text
    assert '"entry"' in text and '"exit"' in text


def test_missing_code_graceful(tmp_path):
    trades = _trades_df([_trade(thscode="999999.SZ")])
    out = _render(tmp_path, trades, {})
    assert "无 K 线数据" in out.read_text(encoding="utf-8")


def test_empty_trades(tmp_path):
    out = _render(tmp_path, _trades_df([]), {})
    text = out.read_text(encoding="utf-8")
    assert "交易数: 0" in text


def test_trade_extra_cols_shown(tmp_path):
    df = _trades_df([_trade()])
    df["k_line_score"] = 0.8
    out = _render(tmp_path, df, {"000001.SZ": _bars()},
                  trade_extra_cols=("k_line_score",))
    text = out.read_text(encoding="utf-8")
    assert "k_line_score" in text and "0.8" in text


def test_report_filename():
    assert report_filename("p", datetime(2026, 10, 11, 12, 0, 0)) == \
        "p_report_20261011_120000.html"


def test_renderer_no_db_import():
    """§6: core 渲染层禁止 DB 依赖（源码断言）。"""
    src = Path(tr.__file__).read_text(encoding="utf-8")
    assert "duckdb" not in src


def test_report_labels_returns_as_unattributed(tmp_path):
    """§5: 无基准时,报告必须**显式**标注「未归因」。

    CLAUDE.md §5 verbatim: 头条收益必须附基准相对超额;纯 beta 复制不得当作 alpha。
    本地库无指数序列 → 归因不可计算。此时把裸收益直接呈现给读者,正是 §5 要防的
    "把 beta 当 alpha";故渲染器必须自己说清楚,而不是指望读者会怀疑。

    注:该标注随**每一份报告**一起走 —— 它不能只活在某个测试的 skip 文本或审计
    文档里(那种"没人提起所以不存在"的状态正是本仓库反复吃亏的地方)。
    """
    out = _render(tmp_path, _trades_df([_trade()]), {"000001.SZ": _bars()})
    text = out.read_text(encoding="utf-8")
    assert "未归因" in text, "§5 VIOLATION: 报告未标注归因状态。"
    # 单源:标注文本取自规范常量,而不是渲染函数里另写一遍。
    assert tr.UNATTRIBUTED_NOTICE in text

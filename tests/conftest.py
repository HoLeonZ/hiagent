"""共享 fixture：临时 DuckDB（带 v_daily 完整 schema）+ 黑名单 + 合成单股 panel。"""
from __future__ import annotations

import zlib
from pathlib import Path

import duckdb
import pandas as pd
import pytest


SAMPLE_CODES = [
    "600000.SH",  # 沪主板
    "601318.SH",  # 沪主板
    "603000.SH",  # 沪主板
    "605999.SH",  # 沪主板
    "000001.SZ",  # 深主板
    "002415.SZ",  # 深主板
    "003000.SZ",  # 深主板
    "300750.SZ",  # 创业板（应排除）
    "301000.SZ",  # 创业板
    "688981.SH",  # 科创板（应排除）
    "689009.SH",  # 科创板
    "830799.BJ",  # 北交所（应排除）
    "832000.BJ",  # 北交所
    "123456.SH",  # 非法前缀（应排除）
]


@pytest.fixture
def sample_thscodes() -> list[str]:
    """覆盖各前缀边界条件。"""
    return list(SAMPLE_CODES)


@pytest.fixture
def temp_duckdb(tmp_path: Path, sample_thscodes: list[str]) -> Path:
    """建 v_daily 表（完整 schema：thscode/date/open/high/low/close/amount/volume）。

    每只代码在 2024-06-01 ~ 2025-12-31 期间每日 1 行 OHLCV 数据。
    """
    db = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute(
            "CREATE TABLE v_daily ("
            "  thscode VARCHAR, date DATE,"
            "  open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,"
            "  amount DOUBLE, volume DOUBLE"
            ")"
        )
        dates = pd.date_range("2024-06-01", "2025-12-31", freq="B")
        rows = []
        for code in sample_thscodes:
            for d in dates:
                # §0 (audit 2026-10-15, 可复现性): 原为 `hash(code) % 100`。
                # CPython 对 str 的 `hash()` 逐**进程**随机化(PYTHONHASHSEED),
                # 于是同一份夹具在不同运行里生成**不同的价格** —— 既直接违反
                # §0「相同输入必须产出逐字节相同的输出」,又是潜在的 flaky 来源
                # (价格不同 → 可能触及不同的分支)。改用确定性摘要。
                base = 10.0 + (zlib.crc32(code.encode("utf-8")) % 100) / 10.0
                rows.append((code, d.date(), base, base + 0.5, base - 0.5,
                             base, 5e7, 1e6))
        con.executemany(
            "INSERT INTO v_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
        )
    finally:
        con.close()
    return db


@pytest.fixture
def exclude_txt(tmp_path: Path) -> Path:
    """黑名单文件：排除 600000.SH 和 002415.SZ。"""
    p = tmp_path / "exclude.txt"
    p.write_text("# comment\n600000.SH\n002415.SZ\n", encoding="utf-8")
    return p


@pytest.fixture
def synthetic_single_stock_panel() -> pd.DataFrame:
    """200 个交易日 × 1 只股票，价格单调下行 + 满足 V5 cascade 条件。

    用于 Phase3V3Strategy 单股回测：
      - 后 100 日是单调下跌 → MA5<MA10<MA20<MA60 在末尾附近成立
      - 跌速 ~2%/日 → pct_chg 接近 -0.02 (但要 > 0, 所以方向反过来设计)
    """
    dates = pd.date_range("2025-01-01", periods=200, freq="B")
    rows = []
    base = 20.0
    for i, d in enumerate(dates):
        # 前 130 日温和上涨（累积让 MA60 形成 + 制造连阳段）
        if i < 130:
            price = base + 0.05 * i  # 累积涨幅 +6.5
        # 后 70 日阶梯式下跌（每日 +0.5% 后再 -3%）
        else:
            price = base + 0.05 * 130 - 0.03 * (i - 130) * 2
        open_p = price
        high_p = price + 0.3
        low_p = price - 0.3
        close_p = price
        rows.append({
            "thscode": "600000.SH",
            "date": d,
            "open": open_p, "high": high_p, "low": low_p, "close": close_p,
            "amount": 5e7, "volume": 1e6,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# §6: 需要本机行情库的测试必须 **skip 而非 error**
# ---------------------------------------------------------------------------
def market_db_available() -> bool:
    """本地行情库是否可用 —— 存在**且非空**(供模块级 `skipif` 使用:模块级不能 skip)。

    只查 `exists()` 会让 **0 字节占位文件**漏过去,而那正是 fresh clone 的形状
    (`data/hiagent.db` 是 0 字节占位,真正的库在用户目录、不在快照里)。实测:
    只查存在性时,0 字节库下有 8 个用例 FAIL、3 个 ERROR。
    """
    from hiagent_config import get_db_path

    db = Path(get_db_path())
    return db.exists() and db.stat().st_size > 0


def require_market_db() -> Path:
    """返回本地行情库路径;不可用则 `pytest.skip`。

    CLAUDE.md §6 verbatim:
      "Tests MUST skip (not error) when the local DB or run artifacts are absent."

    **fresh clone 的真实状态就是"没有库"**。若依赖库的测试在此状态下 error 或 fail,
    新克隆得到的是一套**红的**套件 —— 而"红是常态"正是本仓库已经吃过一次的亏
    (见审计附六:红成为常态后,一次真实回归被"失败数没变"掩盖过去)。
    """
    from hiagent_config import get_db_path

    db = Path(get_db_path())
    if not market_db_available():
        pytest.skip(f"§6: 本地行情库不可用({db})—— skip 而非 error")
    return db


# ---------------------------------------------------------------------------
# §0/§6: golden pin 的**数据指纹** —— 把「数据变了」与「引擎变了」分开(附一百一十七)
# ---------------------------------------------------------------------------
def current_db_fingerprint() -> str:
    """数据侧指纹(廉价但敏感):行情表末日 | 因子表末日 | 事件条数 | 事件最大 ex_date。

    为什么取这四个:2026-10-20 实测到的漂移机制是 —— 事件表新增"**已公告的未来除权**",
    而 `v_daily_qfq` 是**前复权**(锚在最新日)⇒ **整条历史 qfq 序列被平移**。
    所以"事件条数"与"事件最大 ex_date"必须进指纹;只看行情表末日是看不出这件事的。
    """
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


def skip_if_pinned_under_other_data(baseline: dict, name: str) -> None:
    """指纹不符 ⇒ **skip 并说明是数据变了**,而不是报成"引擎漂移"。

    * 指纹**相符** ⇒ 调用方照常比哈希;哈希不符才是**引擎漂移**(该红);
    * 指纹**不符** ⇒ pin 的哈希本就不该复现 —— 报红会训练人忽略红灯(§6 的 background noise);
      故 skip,并给出两个指纹与重 pin 的入口;
    * 指纹字段**缺失**(旧格式) ⇒ 也 skip,并要求重生成 ——
      因为此时**无法区分**两种漂移,而"分不清"时把红当引擎问题看是错的。
    """
    pinned = baseline.get("db_fingerprint")
    if pinned is None:
        pytest.skip(
            f"{name}: 该基线**未记录数据指纹**(旧格式)⇒ 无法区分「数据变了」与「引擎变了」。"
            "请重生成:`python tests/_repin_after_data_refresh.py`(或各族 _regen_/_capture_ 脚本)。"
        )
    current = current_db_fingerprint()
    if pinned != current:
        pytest.skip(
            f"{name}: **数据变了**(不是引擎漂移)—— pin 时的库指纹与现在不同。\n"
            f"  pin 时: {pinned}\n  现在 : {current}\n"
            "前复权视图锚在最新日,新增「已公告的未来除权」会平移整条历史序列 ⇒ "
            "同一批成交被重新定价。重 pin:`python tests/_repin_after_data_refresh.py`。"
        )

"""选股范围：沪深主板 + 黑名单剔除 + as-of 过滤。

DuckDB 无历史成分表 → as-of 代理：剔除 asof_date 之后才上市的票。
严格的 HS300 / 中证 500 历史成分 as-of 标 P2（需新拉数据）。
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from short_reversal import ShortReversalError

# 沪深主板前缀
_SH_MAIN = ("60", "601", "603", "605")
_SZ_MAIN = ("000", "001", "002", "003")

#: §3/§0 (2026-10-17): 黑名单是**单一共享**文件(仓库根 `data/`)。
#: 此前这里指向 `short_reversal/data/exclude_thscodes.txt` —— 该路径**不存在**,
#: 于是被 git 跟踪的共享黑名单(仓库根 `data/exclude_thscodes.txt`)从未被加载。
#: 叠加 `_load_exclude` 的"路径缺失即静默返回空集", 结果是
#: 「要排除 29 只」与「排除了 0 只」**完全不可区分** —— 违反 §0「Do not silently bypass」。
_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXCLUDE_PATH = _REPO_ROOT / "data" / "exclude_thscodes.txt"

#: 唯一应用黑名单的模式 —— 模式的**名字**就是它的契约。
#: 名单内容是大盘金融股(工/建/农/招行、中信/华泰等券商), 属**研究口径**的排除,
#: 不是安全清单。让它在 `mainboard_only` 下也生效, 等于借"修 bug"之手改掉全部
#: 出厂 preset 的股票池。故按模式门控 —— 对 mainboard_only **行为中性**。
_EXCLUDE_MODE = "exclude_hs300_zhongtou_finance"


def _is_main_board(code: str) -> bool:
    if code.endswith(".BJ"):
        return False
    if code.endswith(".SH"):
        body = code.split(".", 1)[0]
        return any(body.startswith(p) for p in _SH_MAIN)
    if code.endswith(".SZ"):
        body = code.split(".", 1)[0]
        return any(body.startswith(p) for p in _SZ_MAIN)
    return False


def _resolve_exclude_path(mode: str, exclude_path: Path | None) -> Path | None:
    """决定实际要用的黑名单路径; 返回 None 表示**不排除**。

    - 调用方**显式**传入路径 → 一律生效(它明说了要排除)。
    - 否则只有 `exclude_hs300_zhongtou_finance` 模式才排除 (见 _EXCLUDE_MODE)。
    """
    if exclude_path is not None:
        return Path(exclude_path)
    return DEFAULT_EXCLUDE_PATH if mode == _EXCLUDE_MODE else None


def _load_exclude(path: Path | None) -> set[str]:
    """读取黑名单。

    路径为 None → 空集 (该模式下不排除, 这是**明确**的语义)。
    **要求排除却找不到文件 → fail-fast** (§0: 不得静默把"要排除"退化成"没排除")。
    """
    if path is None:
        return set()
    if not path.exists():
        raise ShortReversalError(
            f"黑名单文件不存在: {path} —— 要求排除却读不到, 拒绝静默退化为"
            f"'排除 0 只' (§0 Fail-Fast)"
        )
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


#: §4 做空可行性 (2026-10-17): ST / 风险警示股涨跌停为 ±5% (主板 ±10%), 且
#: **不在融资融券标的名单里 ⇒ 现实中不可做空**。本库没有名称列 (v_symbol.name /
#: dim_symbol.name 均 0 行非空), 故用**价格行为代理**判定:
#:   某 bar 满足 |涨跌幅| ≈ 5% 且 high == low (全天一个价 = 封死停板);
#:   截至 asof 出现 ≥ _ST_MIN_SEALED 次即判为 5% 涨跌停品种。
#: 判定窗口取 **asof 前 180 天** —— 反映"截至该时点是否是风险警示股", 避免把早年
#: 曾警示、如今已摘帽的票误排除。
#: 说明: 这是**代理**, 不是精确名单 —— 它会漏掉停牌多、波动小因而从未封板的风险
#: 警示股。作为"宁可少做也不做假成交"的方向性过滤使用是保守的。
_ST_LIMIT_BAND = 0.05
_ST_BAND_TOL = 0.0015
_ST_MIN_SEALED = 3


def _suspected_five_pct_limit_codes(db_path: Path, asof_date: str) -> set[str]:
    """返回截至 asof_date 疑似 ±5% 涨跌停 (风险警示类) 的代码集合。

    PIT: 只用 `date <= asof_date` 的 bar —— 不用未来信息。
    """
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            """
            WITH d AS (
              SELECT thscode, high, low,
                     close / LAG(close) OVER (PARTITION BY thscode ORDER BY date) - 1 AS ret
              FROM v_daily WHERE date <= ? AND date > (?::DATE - INTERVAL 180 DAY)
            )
            SELECT thscode FROM d
            WHERE ret IS NOT NULL
              AND abs(abs(ret) - ?) < ? AND high = low
            GROUP BY 1 HAVING count(*) >= ?
            """,
            [asof_date, asof_date, _ST_LIMIT_BAND, _ST_BAND_TOL, _ST_MIN_SEALED],
        ).fetchall()
    except duckdb.Error as e:
        raise ShortReversalError(f"DuckDB read failed: {e}") from e
    finally:
        con.close()
    return {r[0] for r in rows}


def load_universe_asof(
    mode: str,
    asof_date: str,
    db_path: Path,
    exclude_path: Path | None = None,
    exclude_suspected_st: bool = False,
) -> list[str]:
    """返回 asof_date 之前已上市 + 黑名单过滤 + mode 分类的代码列表。

    Args:
      mode: 'mainboard_only' | 'exclude_hs300_zhongtou_finance'
            （后者目前等同 mainboard_only；HS300/CSI500 历史成分表未建立）
      asof_date: 'YYYY-MM-DD' —— 剔除该日之后才上市/才有交易的票
      db_path: DuckDB 路径
      exclude_path: 黑名单文件路径（默认 data/exclude_thscodes.txt）

    Raises:
      ValueError: mode 未知
      ShortReversalError: DuckDB 读取失败
    """
    if mode not in ("mainboard_only", "exclude_hs300_zhongtou_finance"):
        raise ValueError(
            f"Unknown universe mode: {mode!r}. "
            f"Available: mainboard_only, exclude_hs300_zhongtou_finance"
        )

    excluded = _load_exclude(_resolve_exclude_path(mode, exclude_path))
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            "SELECT DISTINCT thscode FROM v_daily "
            "WHERE date <= ? ORDER BY thscode",
            [asof_date],
        ).fetchall()
    except duckdb.Error as e:
        raise ShortReversalError(f"DuckDB read failed: {e}") from e
    finally:
        con.close()

    all_codes = [r[0] for r in rows]
    if exclude_suspected_st:
        excluded = excluded | _suspected_five_pct_limit_codes(db_path, asof_date)
    filtered = [
        c for c in all_codes
        if _is_main_board(c) and c not in excluded
    ]
    return sorted(filtered)

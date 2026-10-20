"""选股范围：沪深主板 + 黑名单剔除 + as-of 过滤。

DuckDB 无历史成分表 → as-of 代理：剔除 asof_date 之后才上市的票。
严格的 HS300 / 中证 500 历史成分 as-of 标 P2（需新拉数据）。

=== 数据受阻方向 (2026-10-14 全库/全参数探索后确认) ===
以下 universe 细化方向在当前 DB 下不可测:
  - ST 股过滤: v_daily 无 ST/名称列; dim_symbol.name 全为 NULL (0 行非空)。
    ST 股 ±5% 涨跌停, 与主板 ±10% 不同, 理论上应单独处理 (参 §4 board-aware)。
  - 指数成分 (HS300/CSI500): 无历史成分表。
  - 黑名单: `data/exclude_thscodes.txt` **存在且被跟踪**(ffe29be),但此前代码把
    默认路径写成了不存在的 `short_reversal/data/exclude_thscodes.txt`,于是它从未
    被加载 —— 与模式无关地恒为 no-op。2026-10-15 已修正:单一共享路径 + 由
    `exclude_hs300_zhongtou_finance` 模式门控(名单是大盘金融股,属研究口径,
    不应影响 `mainboard_only`)。
如未来引入 ST 标记或成分表, 可在 _is_main_board 之外增设过滤。
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from short_reversal import ShortReversalError

# 沪深主板前缀
_SH_MAIN = ("60", "601", "603", "605")
_SZ_MAIN = ("000", "001", "002", "003")

# 创业板 (ChiNext) / 科创板 (STAR) — v67 broad universe 扩展用。
# §4 注意: 创业板/科创板涨跌停 ±20% (主板 ±10%), limit 逻辑需按板区分。
_SZ_CHINEXT = ("300",)
_SH_STAR = ("688",)

#: §3 (audit 2026-10-15): 黑名单是**单一共享**文件(仓库根 `data/`)。
#: 此前这里指向 `short_reversal/data/exclude_thscodes.txt` —— 该路径**不存在**,
#: 于是被 git 跟踪的共享黑名单(见 `data/exclude_thscodes.txt`,提交于 `ffe29be`)
#: 从未被加载。更糟的是模块 docstring 把 no-op 的原因写成"该文件不存在",
#: 而它**存在且已被跟踪** —— 一句错误的说明会把后来人引向完全错误的结论。
_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXCLUDE_PATH = _REPO_ROOT / "data" / "exclude_thscodes.txt"

#: 唯一应用黑名单的模式 —— 模式的**名字**就是它的契约。
#: 此前黑名单与模式**无关**地生效,而唯一可能的默认路径又不存在,于是它对每个
#: 模式都是 no-op,包括那个以"排除"命名的模式。模式名不是装饰。
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


def _is_broad(code: str) -> bool:
    """v67 (2026-10-13): 主板 + 创业板(300.SZ) + 科创板(688.SH)。

    扩展 universe 以测试 reverse-momentum 在更广市场微观结构上的表现。
    §4: 300/688 涨跌停 ±20%, 由 strategy 的 board-aware limit threshold 处理。
    """
    if _is_main_board(code):
        return True
    if code.endswith(".SH"):
        body = code.split(".", 1)[0]
        return any(body.startswith(p) for p in _SH_STAR)
    if code.endswith(".SZ"):
        body = code.split(".", 1)[0]
        return any(body.startswith(p) for p in _SZ_CHINEXT)
    return False


def _resolve_exclude_path(mode: str, exclude_path: Path | None) -> Path | None:
    """决定实际要用的黑名单路径;返回 None 表示**不排除**。

    - 调用方**显式**传入路径 → 一律生效(它明说了要排除)。
    - 否则只有 `exclude_hs300_zhongtou_finance` 模式才排除。

    模式门控的理由:黑名单的内容是**大盘金融股**(工/建/农/招行、中信/华泰/海通
    等券商),那是一个**研究口径**的排除,不是安全清单。让它在 `mainboard_only`
    下也生效,等于用一次"修 bug"偷偷改掉所有 preset 的股票池。
    """
    if exclude_path is not None:
        return Path(exclude_path)
    return DEFAULT_EXCLUDE_PATH if mode == _EXCLUDE_MODE else None


def _load_exclude(path: Path | None) -> set[str]:
    """读取黑名单。路径为 None → 空集;**要求排除却找不到文件 → fail-fast**。

    §0 (audit 2026-10-15): 此前路径缺失时静默返回空集,于是"要排除 29 只"与
    "排除了 0 只"完全不可区分 —— 一个失效的风险控制输入会被当成"已启用"。
    与本仓库反复出现的静默默认同型一致。
    """
    if path is None:
        return set()
    if not path.exists():
        raise ShortReversalError(
            f"§0: 要求应用黑名单,但文件不存在: {path}。"
            "静默返回空集会让「要排除」与「排除 0 个」不可区分。"
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
            -- §1 (§13.73): 显式顶层 ORDER BY —— 结果集行序必须确定 (§0 可复现性)。
            -- 消费者把它折成 set (见下方 return), 故此句**零结果漂移**。
            ORDER BY 1
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
      mode: 'mainboard_only' | 'exclude_hs300_zhongtou_finance' | 'broad_only'
            （exclude_hs300_zhongtou_finance 目前等同 mainboard_only；
             HS300/CSI500 历史成分表未建立。broad_only 加创业板+科创板。）
      asof_date: 'YYYY-MM-DD' —— 剔除该日之后才上市/才有交易的票
      db_path: DuckDB 路径
      exclude_path: 黑名单文件路径。显式传入则一律生效;**缺省时仅
                    `exclude_hs300_zhongtou_finance` 模式使用共享黑名单**
                    (`<repo_root>/data/exclude_thscodes.txt`)。
      exclude_suspected_st: 是否并入 §4 的"疑似 ±5% 封板(ST/风险警示)"代理集合。
                    默认 False(行为中性)。

    Raises:
      ValueError: mode 未知
      ShortReversalError: DuckDB 读取失败
    """
    if mode not in (
        "mainboard_only",
        "exclude_hs300_zhongtou_finance",
        "broad_only",
    ):
        raise ValueError(
            f"Unknown universe mode: {mode!r}. "
            f"Available: mainboard_only, exclude_hs300_zhongtou_finance, broad_only"
        )

    excluded = _load_exclude(_resolve_exclude_path(mode, exclude_path))
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        # §3 PIT (audit 2026-10-16): 本查询此前只是 `WHERE date <= ?`,**没有退市
        # 判定** —— 于是一只 2018 年就退市的票在 2026 年的窗口里依然"在宇宙里"。
        # §3 的 PIT Mandate 要求「Delisted assets must remain in the simulation
        # **until their physical delisting date**」,即退市日之后必须剔除。
        #
        # 判据与 chase_up / uptrend_pullback 对齐(三者必须给同一个宇宙):
        # 活跃 ⇔ 该票**整表**最后一根 bar >= asof 当日或之前的最后一个交易日。
        # 注意**不能**写成 `HAVING MAX(date) >= asof` —— 那样在 asof 落在非交易日时
        # 对每只票都不成立(全部被误判为已退市 ⇒ 空宇宙),且会把
        # "当日停牌"(整表最后一根 bar 在 asof 之后)错杀成退市。
        rows = con.execute(
            "WITH last_td AS (SELECT MAX(date) AS d FROM v_daily WHERE date <= ?), "
            "     overall AS (SELECT thscode, MAX(date) AS last_any "
            "                 FROM v_daily GROUP BY thscode) "
            "SELECT DISTINCT v.thscode FROM v_daily v "
            "JOIN overall o ON o.thscode = v.thscode "
            "WHERE v.date <= (SELECT d FROM last_td) "
            "  AND o.last_any >= (SELECT d FROM last_td) "
            "ORDER BY v.thscode",
            [asof_date],
        ).fetchall()
    except duckdb.Error as e:
        raise ShortReversalError(f"DuckDB read failed: {e}") from e
    finally:
        con.close()

    all_codes = [r[0] for r in rows]
    if exclude_suspected_st:
        # §4 (2026-10-17, branch): ST / 风险警示类 ±5% 封板代理 —— 该类标的
        # 不在融资融券名单里, 现实中不可做空。默认关闭, 仅显式声明时生效。
        # 必须在下方空宇宙 fail-fast **之前**并入, 否则"全被 ST 代理滤掉"
        # 会再次退化成静默的 0 笔交易。
        excluded = excluded | _suspected_five_pct_limit_codes(db_path, asof_date)
    if mode == "broad_only":
        filtered = [
            c for c in all_codes
            if _is_broad(c) and c not in excluded
        ]
    else:
        filtered = [
            c for c in all_codes
            if _is_main_board(c) and c not in excluded
        ]
    if not filtered:
        # §0 Fail-Fast (audit 2026-10-16): 空 universe 必须显式失败。
        # 此前静默返回 [] —— 与 chase_up / uptrend_pullback 的同款守卫不对称:
        # asof 早于数据覆盖起点、或黑名单滤掉全部标的时,回测会**静默跑出 0 笔
        # 交易**,与"策略没信号"完全同形。
        raise ShortReversalError(
            f"Empty universe: mode={mode!r}, asof_date={asof_date!r}, db={db_path}. "
            f"§0 Fail-Fast: 空 universe 会让回测静默产出 0 笔交易。"
            f"常见原因: asof_date 早于数据覆盖起点(或黑名单滤掉了全部标的)。"
        )
    return sorted(filtered)

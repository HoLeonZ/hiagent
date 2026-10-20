"""选股范围：沪深主板 + 黑名单剔除。

mode:
  mainboard_only → 仅沪深主板（SH 60/601/603/605 + SZ 000/001/002/003）
  all_ex_bj      → 剔除北交所之外的全部 A 股（含创业板/科创板）

注意：本库 v_symbol 表为空，无法按名称剔除 ST/*ST。这是已知局限，
在 docs 的 spec 中有记录。
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from uptrend_pullback import UptrendPullbackError

_SH_MAIN = ("60", "601", "603", "605")
_SZ_MAIN = ("000", "001", "002", "003")

VALID_MODES = ("mainboard_only", "all_ex_bj")


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


def _is_a_share_ex_bj(code: str) -> bool:
    return code.endswith(".SH") or code.endswith(".SZ")


def _all_thscodes(db_path: Path, asof_date: str | None = None) -> list[str]:
    """返回 v_daily 中所有 distinct thscode。

    asof_date: 若给定,只返回 asof_date 当日仍活跃的代码 (PIT 过滤);
              即排除 asof_date 之后才上市 / asof_date 之前已退市的票。
              若 None, 返回 post-hoc 全集 (兼容老接口)。
    """
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        if asof_date is None:
            rows = con.execute(
                "SELECT DISTINCT thscode FROM v_daily ORDER BY thscode"
            ).fetchall()
        else:
            # §3 PIT Mandate: 排除 (a) asof_date 之后才上市的票
            # (无 date <= asof_date 数据) AND (b) asof_date 之前已退市的票。
            # 判定基准必须是「asof 当日或之前的最后一个交易日」, 而不是 asof 字面值:
            # 否则 `HAVING MAX(date) >= asof` 在 asof 是周末/节假日时对每只票都不成立
            # (最后一个交易日 < asof) → 全部被误判为「已退市」→ 空集 → 回测静默产出
            # 0 笔交易。last_td 在交易日上恒等于 asof, 故交易日行为不变。
            # §3 PIT (audit 2026-10-16): "已退市" 的判据必须是「**整表**最后一根
            # bar 早于 asof 当日或之前的最后一个交易日」,而不是「asof 那天没有
            # bar」。后者把**当日停牌**与**已退市**混为一谈:`MAX(date)` 是在
            # `date <= ?` 过滤后的分组里取的,恒 <= asof,于是
            # `HAVING MAX(date) >= last_td` 退化成「在最后一个交易日**恰好有** bar」
            # —— 这正是本注释上半段自己声明的判据(「asof_date 之前已退市的票」)
            # 的反面。
            #
            # 实测(2026-01-09,mainboard_only):本式 3167 只 vs short_reversal 3176 只,
            # 少掉的 9 只全部是**当天/近日停牌**的票(如 002049.SZ 最后一根 bar
            # 2025-12-29,而整表最后一根是 2026-09-30 —— 停牌,不是退市)。
            # 停牌票仍在市、窗口内会复牌,按 §1/§3 必须留在 universe 里。
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
    finally:
        con.close()
    return [r[0] for r in rows]


def _load_exclude(exclude_path: Path | None) -> set[str]:
    """读取黑名单。None → 空集(未要求排除);显式传入但文件缺失 → fail-fast。

    §0 (audit 2026-10-15): 此前 `not Path(exclude_path).exists()` 也静默返回空集,
    于是"要排除 29 只"与"排除了 0 只"不可区分 —— 一个失效的风险控制输入会被
    当成"已启用"。
    """
    if exclude_path is None:
        return set()
    path = Path(exclude_path)
    if not path.exists():
        raise FileNotFoundError(
            f"§0: 要求应用黑名单,但文件不存在: {path}。"
            "静默返回空集会让「要排除」与「排除 0 个」不可区分。"
        )
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def load_universe(
    mode: str,
    db_path: Path,
    exclude_path: Path | None = None,
    asof_date: str | None = None,
) -> list[str]:
    """返回符合 mode 的 thscode 列表（已剔除黑名单）。

    asof_date: 若给定, 只返回 asof_date 当日仍活跃的代码 (§3 PIT Mandate);
              若 None, 返回 post-hoc 全集 (兼容老调用)。
    """
    if mode not in VALID_MODES:
        raise ValueError(
            f"Unknown universe mode: {mode!r}. Available: {', '.join(VALID_MODES)}"
        )

    try:
        all_codes = _all_thscodes(db_path, asof_date=asof_date)
    except duckdb.Error as e:
        raise UptrendPullbackError(f"DuckDB read failed: {e}") from e

    excluded = _load_exclude(exclude_path)
    pred = _is_main_board if mode == "mainboard_only" else _is_a_share_ex_bj

    result = sorted(c for c in all_codes if pred(c) and c not in excluded)
    if not result:
        # §0 Fail-Fast: 空 universe 必须显式失败。静默返回 [] 会让 engine 跑出一个
        # 0 笔交易的回测 —— 看起来像「策略没信号」, 实为数据覆盖/参数问题。
        raise UptrendPullbackError(
            f"Empty universe: mode={mode!r}, asof_date={asof_date!r}, db={db_path}. "
            f"§0 Fail-Fast: 空 universe 会让回测静默产出 0 笔交易。"
            f"常见原因: asof_date 早于数据覆盖起点。"
        )
    return result

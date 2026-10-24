"""选股范围：沪深主板 + 黑名单剔除 (沿用 uptrend_pullback/universe.py 口径)。"""
from __future__ import annotations

from pathlib import Path

import duckdb

from chase_up import ChaseUpError

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
            # （首现日 MIN(date) > asof）AND (b) asof_date 之前已退市的票
            # （末根 bar 早于 asof 当日或之前的最后一个交易日）。
            #
            # ⚠️ **基准必须是"asof 当日或之前的最后一个交易日"，不是 asof 字面值。**
            # 原实现把 `date <= asof` 写进了 WHERE，于是 `HAVING MAX(date) >= asof`
            # 只能在"该票**恰好**在 asof 当天有 bar"时成立 —— 而 asof 落在周末/
            # 节假日时对每只票都不成立 → **空集** → 回测**静默**产出 0 笔交易。
            # 实测（2026-10-24）：asof=2025-01-01（元旦）→ **0 只**；
            # asof=2024-01-01（元旦）→ **0 只**；asof=2025-06-01（周日）→ **0 只**；
            # asof=2023-06-01（周四，交易日）→ 3086 只。
            # 于是"平台默认窗口 2025-01-01 起"在 chase_up 上**永远 0 笔**，
            # 而界面看上去只是"这个策略没信号"。
            #
            # ⚠️ **MAX(date) 必须跨全部日期取**，不能只看 `date <= asof` 的那些行 ——
            # 否则"最后一根 bar 在 asof 之前"就等于"已退市"，把**停牌**的票也误杀。
            # 停牌不是退市（§1：停牌产生缺失 bar，不是合成 bar）。
            rows = con.execute(
                "SELECT thscode FROM v_daily "
                "GROUP BY thscode "
                "HAVING MIN(date) <= ? "
                "AND MAX(date) >= (SELECT MAX(date) FROM v_daily WHERE date <= ?) "
                "ORDER BY thscode",
                [asof_date, asof_date],
            ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def _load_exclude(exclude_path: Path | None) -> set[str]:
    if exclude_path is None or not Path(exclude_path).exists():
        return set()
    return {
        line.strip()
        for line in Path(exclude_path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def load_universe(
    mode: str,
    db_path: Path,
    exclude_path: Path | None = None,
    asof_date: str | None = None,
) -> list[str]:
    """返回符合 mode 的 thscode 列表 (已剔除黑名单)。

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
        raise ChaseUpError(f"DuckDB read failed: {e}") from e

    excluded = _load_exclude(exclude_path)
    pred = _is_main_board if mode == "mainboard_only" else _is_a_share_ex_bj

    return sorted(c for c in all_codes if pred(c) and c not in excluded)
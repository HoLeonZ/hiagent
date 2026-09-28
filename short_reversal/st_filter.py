"""ST 状态启发式过滤。

注意:
- ST 是时变状态,官方 API 不直接暴露历史变更。命名启发式(以 `*ST` / `ST` 开头的简称)
  只在 5 条件命中的 thscode 集合上调用 — 调用量小(≤几十只),成本可控。
- 真正下单前必须人工去券商 app 二次确认,因为:
    * 部分票存在改名窗口期(刚被 ST 改名 / 刚摘帽改名),name 滞后 1-3 天
    * 部分新股在前 5 个交易日不限涨跌幅,但券商两融池可能未纳入
    * 退市整理期票的两融规则独立,本过滤器不感知
"""
from __future__ import annotations

import json
import logging
import subprocess
from typing import Iterable

import pandas as pd

logger = logging.getLogger(__name__)

_ST_PREFIXES = (
    "*ST", "ST", "SST", "S*ST",
    "N", "N+",  # 新股 (前 5 个交易日不设涨跌幅, 流动性规则不同)
    "C", "XC",  # 创业板注册制新股 / 风险警示
    "U", "XB",  # 未盈利 / 协议转让
    "D",  # 退市整理期
)


def _looks_like_st(name: str) -> bool:
    if not name:
        return False
    name = name.lstrip()
    return any(name.startswith(p) for p in _ST_PREFIXES)


def _fetch_name_map(codes: Iterable[str]) -> dict[str, str]:
    """批量调用 hithink-finance symbol search 取名称。失败/超时返回空 dict。"""
    out: dict[str, str] = {}
    for code in sorted(set(codes)):
        ticker = code.split(".")[0]
        try:
            proc = subprocess.run(
                ["hithink-finance", "symbol", "search", "--q", ticker,
                 "--asset-type", "a-share", "--format", "json"],
                capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
            logger.warning("search %s failed: %s", code, e)
            continue
        try:
            env = json.loads(proc.stdout)
        except json.JSONDecodeError:
            continue
        if not env.get("ok"):
            continue
        items = env.get("data", {}).get("item") or []
        hit = next((x for x in items if x.get("thscode") == code), None)
        if hit:
            out[code] = hit.get("name") or ""
    return out


def filter_st_codes(
    panel: pd.DataFrame, signal_date: str
) -> tuple[pd.DataFrame, list[dict]]:
    """基于名称启发式剔除 ST 票,返回 (filtered_panel, excluded_records)。

    ⚠️ 这个版本会对整个 universe 拉名称 (5k+ 次 search),只在回测离线 batch
    场景用得起。实时信号扫描请用 filter_signal_codes_for_st。
    """
    codes = panel["thscode"].unique().tolist()
    name_map = _fetch_name_map(codes)
    st_codes: dict[str, str] = {
        c: name_map[c] for c in codes if _looks_like_st(name_map.get(c, ""))
    }
    excluded = [
        {"thscode": c, "name": st_codes[c], "signal_date": signal_date,
         "reason": "ST/*ST 风险警示 (启发式: 命名前缀)"}
        for c in st_codes
    ]
    if not excluded:
        return panel, []
    keep = panel[~panel["thscode"].isin(st_codes.keys())].reset_index(drop=True)
    logger.info("[st-filter] 剔除 %d 只 ST/*ST 票", len(excluded))
    return keep, excluded


def filter_signal_codes_for_st(
    signals: pd.DataFrame, signal_date: str
) -> tuple[pd.DataFrame, list[dict]]:
    """对已通过 5 条件的命中票做 ST 启发式剔除。

    实时信号场景: 命中数通常 ≤ 几十只, 远端 search 调用量在秒级。
    """
    if signals.empty:
        return signals, []
    codes = signals["thscode"].unique().tolist()
    name_map = _fetch_name_map(codes)
    st_codes: dict[str, str] = {
        c: name_map[c] for c in codes if _looks_like_st(name_map.get(c, ""))
    }
    excluded = [
        {"thscode": c, "name": st_codes[c], "signal_date": signal_date,
         "reason": "ST/*ST 风险警示 (启发式: 命名前缀)"}
        for c in st_codes
    ]
    if not excluded:
        return signals, []
    keep = signals[~signals["thscode"].isin(st_codes.keys())].reset_index(drop=True)
    logger.info("[st-filter] 剔除 %d 只 ST/*ST 票", len(excluded))
    return keep, excluded

"""ST 状态启发式过滤。

注意:
- ST 是时变状态,官方 API 不直接暴露历史变更。命名启发式(以 `*ST` / `ST` 开头的简称)
  只在 5 条件命中的 thscode 集合上调用 — 调用量小(≤几十只),成本可控。
- 真正下单前必须人工去券商 app 二次确认,因为:
    * 部分票存在改名窗口期(刚被 ST 改名 / 刚摘帽改名),name 滞后 1-3 天
    * 部分新股在前 5 个交易日不限涨跌幅,但券商两融池可能未纳入
    * 退市整理期票的两融规则独立,本过滤器不感知

§0 (audit 2026-10-16) —— **取不到名称即失败,不静默放行**:
  `_fetch_name_map` 在任何一只票取不到名称时抛 `STFilterUnavailable`。此前它
  "失败即跳过、返回拿到的那部分",而调用方以 `name_map.get(c, "")` 兜底 ⇒
  取不到名称的票被当成"非 ST"**静默通过**。风险控制输入的"没跑成"与"跑了没命中"
  必须可区分。要在无过滤下扫描请显式 `--include-st`。
  注入点是 `_fetch_name_map` 这一层,故回测路径(不 import 本模块)完全不受影响。

§3 PIT 偏离(**已声明,不是 as-of 语义**):
  名称取自**当前**时点。因此对历史的 `--signal-date` 而言,本过滤用的是"今天"的
  ST 状态,而不是该信号日的状态 —— 它**不是** point-in-time 过滤。历史扫描中被
  本过滤剔除/保留的票,不得当作 PIT 结论使用;回测引擎不走本模块,故回测的
  universe 不受此影响(回测的 PIT 过滤在 `short_reversal/universe.py`)。
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


class STFilterUnavailable(RuntimeError):
    """取不到名称 ⇒ ST 过滤**无法完成**(§0: 不得静默放行)。"""


def _fetch_name_map(codes: Iterable[str]) -> dict[str, str]:
    """批量调用 hithink-finance symbol search 取名称。

    §0 (audit 2026-10-16): 只要有**任何一只有**名称取不到,就抛
    `STFilterUnavailable`。此前是"失败即 continue,最后返回拿到的那部分",
    而调用方用 `name_map.get(c, "")` 兜底 —— `_looks_like_st("")` 为 False,
    于是**取不到名称的票会被当成"不是 ST"静默放行**。一个风险控制过滤器
    "没跑成"与"跑了且没有命中"必须可区分,否则它提供的安全感是假的。
    这与本仓库已修的同形缺陷同类(`chase_up/universe.py` 的黑名单:`不存在的
    文件静默返回空集` ⇒ "要排除 29 只"与"排除了 0 只"不可区分)。

    确实要在**无过滤**下出结果,请显式传 `--include-st`(两个入口都已有该开关)——
    把"放弃风险检查"变成一次**明确的**操作,而不是一次安静的失败。
    """
    unique = sorted(set(codes))
    out: dict[str, str] = {}
    failed: list[str] = []
    for code in unique:
        ticker = code.split(".")[0]
        try:
            proc = subprocess.run(
                ["hithink-finance", "symbol", "search", "--q", ticker,
                 "--asset-type", "a-share", "--format", "json"],
                capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
            logger.warning("search %s failed: %s", code, e)
            failed.append(code)
            continue
        try:
            env = json.loads(proc.stdout)
        except json.JSONDecodeError:
            failed.append(code)
            continue
        if not env.get("ok"):
            failed.append(code)
            continue
        items = env.get("data", {}).get("item") or []
        hit = next((x for x in items if x.get("thscode") == code), None)
        if hit:
            out[code] = hit.get("name") or ""
        else:
            failed.append(code)
    if failed:
        raise STFilterUnavailable(
            f"§0 fail-fast: {len(failed)}/{len(unique)} 只未能取得名称,"
            f"ST 过滤无法完成: {failed[:5]}{'…' if len(failed) > 5 else ''}。"
            f"静默跳过会让『已过滤』与『过滤没跑成』不可区分;"
            f"若确实要在无 ST 过滤下扫描,请显式加 --include-st。"
        )
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

"""§0 守卫:ST 过滤器**取不到名称时必须失败**,不得静默放行。

## 缺陷(2026-10-16 复核确认)

`short_reversal/st_filter.py` 的 `_fetch_name_map` 是"失败即 `continue`,返回拿到的那部分",
而调用方用 `name_map.get(c, "")` 兜底 —— 而 `_looks_like_st("")` 为 `False`,
于是**取不到名称的票被当成"非 ST"静默通过**:

    name_map 为空(CLI 不在 / 超时 / 返回非 JSON / ok=false)
      ⇒ st_codes 为空 ⇒ keep = 全体 ⇒ 「已过滤」与「过滤根本没跑成」不可区分

一个**风险控制**过滤器以"没查出问题"的形式失效,方向正好与 §0 的 Pessimistic Default
相反(§0:「Always assume the worst-case scenario for market liquidity, execution
price, and statistical significance」「Do not silently bypass」)。

这与本仓库已修的同形缺陷同类:`chase_up/universe.py` 的黑名单"文件不存在时静默返回
空集" ⇒「要排除 29 只」与「排除了 0 只」不可区分。

## 修法

`_fetch_name_map` 只要有**任何一只**取不到名称即抛 `STFilterUnavailable`。
要在无过滤下出结果,显式传 `--include-st`(两个入口都已有该开关)—— 把"放弃风险检查"
变成一次**明确的**操作。注入点在 `_fetch_name_map` 这一层,故**回测路径完全不受影响**
(已用传递闭包核对:四个回测入口可达的 40 个仓库模块里,没有一条边通向
`subprocess` / `st_filter` / 网络)。

## 附:为什么这条不是"§6 策略层不做 IO"的违反

审计台账把本项记为"§6 信号层发子进程/网络 IO"。逐条核对后**不成立**:
`st_filter` 只被 `scan_signals.py` / `scan_signals_fast.py`(实时扫描工具)引用,
§6 定义的 Strategy(`replay_strategy_v3`)在回测路径上不触达它。真实缺陷是上面的
**静默放行**,不是分层问题。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from short_reversal import st_filter as stf  # noqa: E402


class _Proc:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


def _cli_returning(mapping: dict[str, tuple[str, str] | None]):
    """造一个假的 `hithink-finance symbol search`。

    mapping: ticker → (完整 thscode, 名称);`None` 表示该票**查不到**(空 items)。
    必须带上完整 thscode:引擎按 `thscode == code` 精确匹配,交易所后缀错了
    就会被判成"取不到名称"(这正是被测的那条失败路径)。
    """

    def _run(cmd, **kwargs):
        ticker = cmd[cmd.index("--q") + 1]
        entry = mapping.get(ticker)
        if entry is None:
            items: list[dict] = []
        else:
            thscode, name = entry
            items = [{"thscode": thscode, "name": name}]
        return _Proc(json.dumps({"ok": True, "data": {"item": items}}))

    return _run


def _signals(*codes: str) -> pd.DataFrame:
    return pd.DataFrame({"thscode": list(codes), "score": [1.0] * len(codes)})


# ---------------------------------------------------------------------------
# 失败必须响亮(两向有牙:旧实现返回 {} / 部分结果,本组断言必红)
# ---------------------------------------------------------------------------


def test_unreachable_cli_raises_instead_of_returning_empty(monkeypatch) -> None:
    """CLI 不可用 ⇒ 抛错。旧行为:返回空 dict ⇒ 全体放行。"""

    def _boom(cmd, **kwargs):
        raise FileNotFoundError("hithink-finance not found")

    monkeypatch.setattr(stf.subprocess, "run", _boom)
    with pytest.raises(stf.STFilterUnavailable, match="无法完成"):
        stf._fetch_name_map(["600000.SH", "000001.SZ"])


def test_partial_lookup_failure_raises(monkeypatch) -> None:
    """**部分**失败同样不得静默 —— 取不到的那只正是可能被漏过的 ST。"""
    monkeypatch.setattr(
        stf.subprocess, "run",
        _cli_returning({"600000": ("600000.SH", "浦发银行"), "000001": None}),
    )
    with pytest.raises(stf.STFilterUnavailable, match="000001.SZ"):
        stf._fetch_name_map(["600000.SH", "000001.SZ"])


def test_non_json_response_raises(monkeypatch) -> None:
    """返回非 JSON(例如 CLI 打了别的日志)⇒ 抛错,不当作"无 ST 命中"。"""
    monkeypatch.setattr(stf.subprocess, "run", lambda cmd, **kw: _Proc("not json\n"))
    with pytest.raises(stf.STFilterUnavailable):
        stf._fetch_name_map(["600000.SH"])


def test_ok_false_envelope_raises(monkeypatch) -> None:
    """远端返回 `ok=false` ⇒ 抛错。"""
    monkeypatch.setattr(
        stf.subprocess,
        "run",
        lambda cmd, **kw: _Proc(json.dumps({"ok": False, "data": {}})),
    )
    with pytest.raises(stf.STFilterUnavailable):
        stf._fetch_name_map(["600000.SH"])


# ---------------------------------------------------------------------------
# 正常路径不得被上组改动破坏(否则过滤器变成"从不放行"也不可用)
# ---------------------------------------------------------------------------


def test_st_named_stock_is_excluded(monkeypatch) -> None:
    """正路径:带 `*ST` 前缀的票仍必须被剔除并如实报告。"""
    monkeypatch.setattr(
        stf.subprocess,
        "run",
        _cli_returning({"600000": ("600000.SH", "浦发银行"), "000001": ("000001.SZ", "*ST海航")}),
    )
    kept, excluded = stf.filter_signal_codes_for_st(
        _signals("600000.SH", "000001.SZ"), "2026-01-05"
    )
    assert list(kept["thscode"]) == ["600000.SH"]
    assert [e["thscode"] for e in excluded] == ["000001.SZ"]


def test_normal_names_all_pass(monkeypatch) -> None:
    """正路径:全部取到且无 ST 前缀 ⇒ 原样返回,不抛错。"""
    monkeypatch.setattr(
        stf.subprocess, "run", _cli_returning({"600000": ("600000.SH", "浦发银行"), "000001": ("000001.SZ", "平安银行")})
    )
    kept, excluded = stf.filter_signal_codes_for_st(
        _signals("600000.SH", "000001.SZ"), "2026-01-05"
    )
    assert len(kept) == 2 and excluded == []


# ---------------------------------------------------------------------------
# fail-fast 必须有**显式**逃生门(否则运维会去改代码来绕过)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entry", ["short_reversal/scan_signals.py", "short_reversal/scan_signals_fast.py"]
)
def test_both_entry_points_offer_an_explicit_opt_out(entry: str) -> None:
    """两个实时扫描入口都必须提供 `--include-st`,把"放弃风险检查"变成明确操作。"""
    src = (REPO_ROOT / entry).read_text(encoding="utf-8")
    assert '"--include-st"' in src, (
        f"{entry} 缺少 --include-st:Fail-fast 若没有显式逃生门,"
        "运维会绕过它(改代码),那时守卫就真的失效了"
    )

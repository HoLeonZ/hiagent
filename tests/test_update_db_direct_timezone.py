"""§0 时间确定性守卫：工具脚本的日期 ↔ 时间戳转换必须**与本机时区无关**。

审计 §6 第 1 条（原为「没有任何 cell 覆盖」的六个面之一）：
`tools/update_db_direct.py` 用**本机时区**把日期与毫秒时间戳互转 ——
naive datetime 的 `.timestamp()` 按本地时区解释，反方向亦然。后果是
**同一份 API 负载在不同机器上会落成不同的 bar 日期**（UTC 与 UTC+8 机器可差一天）。

CLAUDE.md §0 (verbatim):
  "**Reproducibility Mandate:** Identical inputs MUST produce byte-identical
   outputs. Fix all seeds, **normalize timestamps to a single exchange
   timezone**, and compare floats with explicit tolerance."

本文件钉两件事：
  1. 往返精确：`from_ms(to_ms(d)) == d`。
  2. 转换**不随 TZ 环境变量变化**（在子进程里换三种时区各跑一次，结果必须一致）。
     —— 这一条正是原实现在结构上会失败的地方。

并顺带把锚点钉住：交易所时区为 UTC+8，故当日 00:00 对应 epoch 当天 16:00Z。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "update_db_direct.py"
DATES = ["2016-09-02", "2024-06-01", "2025-12-31", "2026-04-30"]

#: UTC+8 的 00:00 落在 UTC 前一天 16:00，即 epoch 日内偏移 16 小时。
_UTC8_MIDNIGHT_OFFSET_MS = 16 * 3600 * 1000


def _load_tool():
    spec = importlib.util.spec_from_file_location("update_db_direct", TOOL_PATH)
    assert spec and spec.loader, f"无法加载 {TOOL_PATH}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_roundtrip_is_exact() -> None:
    mod = _load_tool()
    for d in DATES:
        assert mod.from_ms(mod.to_ms(d)) == d, f"往返不精确: {d}"


def test_to_ms_anchors_to_exchange_midnight() -> None:
    """锚点必须是 **UTC+8 的当日 00:00**，而不是本机时区的 00:00。"""
    mod = _load_tool()
    for d in DATES:
        ms = mod.to_ms(d)
        assert ms % 86_400_000 == _UTC8_MIDNIGHT_OFFSET_MS, (
            f"{d} 的 epoch ms={ms} 不落在 UTC+8 当日 00:00 —— "
            "说明锚点跟着本机时区走了(§0:时间戳必须归一到单一交易所时区)。"
        )


def test_conversions_are_independent_of_local_timezone() -> None:
    """决定性的一条：换时区重跑，输出必须逐字节相同。

    原实现(naive datetime + `.timestamp()` / `fromtimestamp`)在此必然失败。
    """
    snippet = (
        "import importlib.util,sys;"
        "spec=importlib.util.spec_from_file_location('u', sys.argv[1]);"
        "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
        "print([m.to_ms(d) for d in sys.argv[2:]]);"
        "print([m.from_ms(m.to_ms(d)) for d in sys.argv[2:]])"
    )
    outputs: dict[str, str] = {}
    for tz in ("UTC", "Asia/Shanghai", "America/New_York"):
        env = {**os.environ, "TZ": tz}
        proc = subprocess.run(
            [sys.executable, "-c", snippet, str(TOOL_PATH), *DATES],
            capture_output=True, text=True, env=env,
        )
        assert proc.returncode == 0, f"TZ={tz} 子进程失败: {proc.stderr}"
        outputs[tz] = proc.stdout.strip()

    distinct = set(outputs.values())
    assert len(distinct) == 1, (
        "§0 VIOLATION: 日期↔时间戳转换随本机时区变化 —— "
        f"同一份输入在不同 TZ 下产出不同结果: {outputs}"
    )

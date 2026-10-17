"""§0 时间确定性: `tools/update_db_direct.py` 的日期↔毫秒转换必须与时区无关。

缺陷 (2026-10-17 复核): `to_ms` 用 naive datetime 的 `.timestamp()`, 落库时又用
naive 的 `datetime.fromtimestamp()`。两者都按**本机时区**解释, 于是同一组日期在
不同 TZ 下产出不同的毫秒值 —— 实测 `2026-09-30` 在

    TZ=UTC               → 1790726400000
    TZ=Asia/Shanghai     → 1790697600000
    TZ=America/New_York  → 1790740800000

相差至多 12 小时, **足以让同一份 API 负载落成不同的 bar 日期**。
CLAUDE.md §0: "normalize timestamps to a single exchange timezone"。

修法: 锚定 `EXCHANGE_TZ = UTC+8` (A 股无夏令时), 并抽出 `from_ms` 供落库复用。
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

TOOL = Path(__file__).parent.parent / "tools" / "update_db_direct.py"

_PROBE = (
    "import importlib.util,sys;"
    "spec=importlib.util.spec_from_file_location('u',sys.argv[1]);"
    "m=importlib.util.module_from_spec(spec);"
    "exec(compile(open(sys.argv[1]).read(),sys.argv[1],'exec'),m.__dict__);"
    "print(m.to_ms('2026-09-30'), m.from_ms(m.to_ms('2026-09-30')))"
)


def _run_with_tz(tz: str) -> str:
    r = subprocess.run(
        [sys.executable, "-c", _PROBE, str(TOOL)],
        capture_output=True, text=True,
        env={"TZ": tz, "PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0"},
    )
    assert r.returncode == 0, f"TZ={tz} 下运行失败: {r.stderr[-400:]}"
    return r.stdout.strip()


def test_date_to_ms_is_timezone_independent() -> None:
    """三种时区下, 往返结果必须完全一致 (旧实现在此处必然三值不同)。"""
    outs = {tz: _run_with_tz(tz) for tz in ("UTC", "Asia/Shanghai", "America/New_York")}
    assert len(set(outs.values())) == 1, (
        f"日期→毫秒→日期 随 TZ 变化, 违反 §0: {outs}"
    )
    assert outs["UTC"].endswith("2026-09-30"), f"往返未回到原日期: {outs['UTC']}"


def test_exchange_tz_is_utc_plus_8() -> None:
    """钉住锚点 —— A 股无夏令时, 恒为 UTC+8。"""
    spec = importlib.util.spec_from_file_location("_u", TOOL)
    mod = importlib.util.module_from_spec(spec)
    exec(compile(TOOL.read_text(encoding="utf-8"), str(TOOL), "exec"), mod.__dict__)
    assert mod.EXCHANGE_TZ.utcoffset(None).total_seconds() == 8 * 3600


def test_no_naive_timestamp_conversion_remains() -> None:
    """结构断言: 不得再出现 naive 的 `.timestamp()` / `fromtimestamp()` 转换。"""
    src = TOOL.read_text(encoding="utf-8")
    assert "datetime.fromtimestamp(" not in src.replace(
        "datetime.fromtimestamp(ms / 1000, tz=EXCHANGE_TZ)", ""
    ), "落库处仍在使用 naive fromtimestamp"
    assert "strptime(date_str, \"%Y-%m-%d\").timestamp()" not in src

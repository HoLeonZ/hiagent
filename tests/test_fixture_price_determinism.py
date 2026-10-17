"""§0 可复现性: 合成库夹具的价格必须与进程无关。

缺陷 (2026-10-17 发现): `tests/conftest.py` 的 `temp_duckdb` 用
`10.0 + (hash(code) % 100) / 10.0` 造价格。CPython 对 str 的 `hash()` 逐**进程**
随机化 (PYTHONHASHSEED), 于是**同一份夹具在不同运行里生成不同的价格** ——
直接违反 §0「Identical inputs MUST produce byte-identical outputs」。
实测: 同一次运行里两个进程给出 `hash('600000.SH') % 100` = 8 与 22。

影响: 任何"改动前后比对失败集合"的回归判定都带上噪声; 价格不同还可能让测试
触及不同分支, 是 flaky 的来源。

修法: 改用 `zlib.crc32` 确定性摘要。
"""
from __future__ import annotations

import subprocess
import sys
import zlib
from pathlib import Path

CONFTEST = Path(__file__).parent / "conftest.py"


def test_fixture_does_not_use_process_random_hash() -> None:
    """夹具不得用 `hash()` 播种 (逐进程随机)。"""
    src = CONFTEST.read_text(encoding="utf-8")
    assert "hash(code)" not in src, (
        "conftest.py 不得用 builtins.hash() 播种价格 —— 它逐进程随机化 (§0)"
    )
    assert "zlib.crc32" in src, "夹具价格必须用确定性摘要"


def test_fixture_prices_identical_across_hash_seeds() -> None:
    """三个不同的 PYTHONHASHSEED 下, 夹具价格算式必须给出相同结果。"""
    code = (
        "import zlib;"
        "print([round(10.0+(zlib.crc32(c.encode('utf-8'))%100)/10.0,4)"
        " for c in ['600000.SH','000001.SZ','601398.SH']])"
    )
    outs = set()
    for seed in ("0", "12345", "999"):
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        )
        assert r.returncode == 0, r.stderr
        outs.add(r.stdout.strip())
    assert len(outs) == 1, f"不同 hash seed 下价格不一致: {outs}"


def test_deterministic_digest_is_stable() -> None:
    """钉住具体取值 —— 防止有人"顺手"换成别的摘要而悄悄改了夹具。"""
    assert zlib.crc32(b"600000.SH") % 100 == 20

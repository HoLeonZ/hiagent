"""附八十四 —— 工具**做了 0 件事**时,退出码不许是 0。

## 缺陷(实测)

`short_reversal/grid_runner.py` 在**在线库上真跑**的结果:

```
$ python3 short_reversal/grid_runner.py
  [ERR] tp_pct=0.015: §0/§6: preset '_grid_cons_tp_pct_0_015' 未声明 'position_sizing' … (×27)
→ 落盘 short_reversal/results/grid/grid_v3_p3p5fix.csv
$ echo $?
0
```

**27/27 个配置全部被引擎的 preset 契约拒绝**,脚本落一张**空网格**、一个 DSR 都不打、
**退出码 0**。这是 `core/cli_verdict`(附六十三)当初为另外四个工具建的场景,而这个脚本
一直不在那份名单里 —— 于是它是这条纪律里**唯一还在静默的**。

根因不止一个字段(补上 `position_sizing` 后下一个是 `price_source_for_execution`),
故本条只做**契约那半**:脚本不再假装成功。

## 这条守卫在测什么

真的调用 `main()`(把 `grid()` 桩成"全部失败"),断言**返回值(即退出码)非零**且结论文本
点名了失败比例。**不桩的话**它会去连在线库跑 27 个一年期回测 —— 那既慢又依赖本机数据。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _repo_on_path():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    yield


def test_grid_runner_exits_nonzero_when_every_config_failed(monkeypatch, tmp_path) -> None:
    """**行为验证**:27/27 失败 ⇒ 退出码 1,且结论说清比例。"""
    mod = importlib.import_module("short_reversal.grid_runner")

    def all_failed(axis, base, values, base_name):
        return [{"axis": axis, "value": v, "error": "synthetic failure"} for v in values]

    monkeypatch.setattr(mod, "grid", all_failed)
    monkeypatch.chdir(tmp_path)   # 落盘目录是相对路径,让它建在 tmp_path 下

    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = mod.main()
    out = buf.getvalue()

    assert code != 0, (
        "§0: 全部配置都失败时退出码必须非零 —— 否则下游会把这张**空网格**当成品。"
    )
    assert "[PARTIAL]" in out and "27/27" in out, (
        "结论文本必须点名失败比例(实测 4+3+3+3 与 4+3+4+3 共 27 个配置)。实际:\n" + out[-400:]
    )


def test_grid_runner_exits_zero_when_every_config_succeeded(monkeypatch, tmp_path) -> None:
    """反向:全部成功时不得报错退出(免得守卫只会往一个方向偏)。"""
    mod = importlib.import_module("short_reversal.grid_runner")

    def all_ok(axis, base, values, base_name):
        return [{"axis": axis, "value": v, "name": f"{axis}_{v}", "n": 3, "win%": 50.0,
                 "CAGR%": 5.0, "Sharpe": 1.0, "DD%": 10.0, "TP/SL/T": "1/1/1",
                 "n_trading_days": 242} for v in values]

    monkeypatch.setattr(mod, "grid", all_ok)
    monkeypatch.chdir(tmp_path)   # 落盘目录是相对路径,让它建在 tmp_path 下

    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = mod.main()

    assert code == 0, f"全部成功却非零退出:{buf.getvalue()[-300:]}"
    assert "[OK]" in buf.getvalue()

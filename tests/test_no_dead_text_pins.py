"""§6 守卫: 死文本钉桩数必须为 0 (§13.122)。

**死钉桩** = 一条"跑了却**不可能通过**"的结构断言:
    `assert "LIT" in SRC` 而 LIT 不在 SRC 里  ⇒ 永不可能通过
    `assert "LIT" not in SRC` 而 LIT 在 SRC 里 ⇒ 永不可能通过
    `SRC.index("LIT")` 而 LIT 不在 SRC 里      ⇒ 抛 ValueError, 同上

它和 §13.20/§13.21 记的「跑了却**不可能失败**的守卫」是**对偶**: 前者零信息量,
后者也零信息量 —— 但前者更坏, 因为它在测试报告里是**红的**, 于是久而久之
被当成"已知的噪音"跳过, 连它旁边那些**活的**断言一起失去注意力。

真例 (§13.122): `test_short_reversal_trailing_no_lookahead.py` 钉了
`'self._close(d, price, reason)\\n            return'`, 而 §13.97 给平仓腿补了
执行冲击、调用变成了 `self._close(d, self._exit_fill_px(...), reason)` ——
**一次正当的参数变更**就让这条断言永久失效, 而它看起来仍在守着因果顺序。

判据是**工具在已知实例上的命中**, 不是"工具跑通了" —— 见
`tools/scan_dead_text_pins.py` 自带的两处更正记录 (第一版把正文当路径 ⇒ 假绿 0;
第二版只认 `assert` ⇒ 漏掉 `.index()` 那一类, 也正是真例所在的那一类)。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from scan_dead_text_pins import scan_file  # noqa: E402


def _census() -> tuple[list[tuple[str, dict]], int]:
    dead_all: list[tuple[str, dict]] = []
    alive = 0
    for f in sorted((ROOT / "tests").glob("test_*.py")):
        dead, n_alive = scan_file(f)
        alive += n_alive
        for d in dead:
            dead_all.append((f.name, d))
    return dead_all, alive


def test_no_dead_text_pins_in_tests() -> None:
    """全 tests/ 不许有死钉桩 (钉桩的**目标文件里必须真有那段字**)。"""
    dead, alive = _census()
    detail = "\n".join(
        f"  {name} L{d['lineno']}: 目标={d['src']} —— {d['why']}\n"
        f"      钉的是: {d['lit'][:90]!r}"
        for name, d in dead
    )
    assert not dead, (
        f"§6: 发现 {len(dead)} 条**死文本钉桩** (永不可能通过的守卫):\n{detail}\n"
        "修法: 钉**形状 + 次序**而不是整条调用文本 (§13.122)。"
    )
    # 反向: 工具本身必须**真的在看东西** —— 一个什么都解析不出来的扫描器
    # 也会打出"0 条死钉桩"这个假的绿。
    assert alive > 10, (
        f"扫描器只认出 {alive} 条活钉桩 —— 它多半没解析出 SRC, "
        f"这个 0 是**假的绿** (见 §13.122 第一版)"
    )


def test_census_scanner_hits_a_known_dead_pin() -> None:
    """在**已知实例**上验证工具会命中 —— 否则"0 条"说明不了任何事。

    造一个临时 `SRC`-式钉桩, 断言 `scan_file` 认得出它是死的。
    """
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "target.py"
        target.write_text("def real_function():\n    return 1\n", encoding="utf-8")
        probe = Path(td) / "test_probe.py"
        probe.write_text(
            "from pathlib import Path\n"
            f'SRC = (Path(__file__).parent / "target.py").read_text(encoding="utf-8")\n'
            "\n"
            "def test_alive():\n"
            '    assert "def real_function" in SRC\n'
            "\n"
            "def test_dead():\n"
            '    assert "def function_that_never_existed" in SRC\n'
            "\n"
            "def test_dead_index():\n"
            '    SRC.index("def also_never_existed")\n',
            encoding="utf-8",
        )
        dead, alive = scan_file(probe)

    lits = {d["lit"] for d in dead}
    assert alive == 1, f"活钉桩应恰好 1 条, 实得 {alive}"
    assert "def function_that_never_existed" in lits, (
        "`assert ... in SRC` 落空那一类没被认出来"
    )
    assert "def also_never_existed" in lits, (
        "`SRC.index(...)` 落空那一类没被认出来 (正是 §13.122 真例所在的那一类)"
    )

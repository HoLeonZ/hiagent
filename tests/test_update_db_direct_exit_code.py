"""§0 守卫:`update_db_direct.py` 的结论必须落在**退出码**上。

## 缺陷(附六十三)

```python
print(f"  errors:    {errors}")   # 自己统计并打印错误数
...
return 0                          # ← 却无条件返回 0
```

这个脚本写的是**共享行情库**,而所有回测都读它:一次**部分失败**的更新以退出码 0
结束,pipeline 会当作成功继续,下一轮回测就读到**半更新**的库 —— 同一份代码在不同
时间跑出不同结果,正是 §0 可复现性要防的事。

与附五十八 的 phantom 工具同族:**结论只在 stdout,退出码恒 0**。
"""
from __future__ import annotations

import ast
import importlib.util

import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "update_db_direct.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("update_db_direct", TOOL_PATH)
    assert spec and spec.loader, f"无法加载 {TOOL_PATH}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 行为:退出码映射
# ---------------------------------------------------------------------------


def test_partial_failure_returns_nonzero() -> None:
    """有标的更新失败 ⇒ 退出码 **1**(不是 0)。"""
    mod = _load_tool()
    code, msg = mod.update_verdict(inserted=500, skipped=20, errors=3)
    assert code == 1, "§0 VIOLATION: 部分失败仍返回 0 —— pipeline 会把半更新当成功"
    assert "PARTIAL" in msg


def test_success_returns_zero() -> None:
    mod = _load_tool()
    code, msg = mod.update_verdict(inserted=500, skipped=20, errors=0)
    assert code == 0
    assert "OK" in msg


def test_no_op_is_zero_but_explicitly_not_success() -> None:
    """确实无事可做 ⇒ 0,但结论措辞必须**说清它不是"更新成功"**。

    (--target 的默认值是一个写死的旧日期;选早了就走这条路径。)
    """
    mod = _load_tool()
    # (a) 处理了 100 个标的、一个也没入库 ⇒ 单独一档 NOTHING-DONE
    code, msg = mod.update_verdict(inserted=0, skipped=100, errors=0)
    assert code == 0
    assert "NOTHING-DONE" in msg
    assert "也不等于成功" in msg, "「无事可做」被写成了成功口径"
    # (b) 压根没有可处理的项目 ⇒ NO-OP(与 (a) 分开:一档是"做了但没结果",
    #     一档是"没有可做的",两者都不等于成功)
    code2, msg2 = mod.update_verdict(inserted=0, skipped=0, errors=0)
    assert code2 == 0
    assert "NO-OP" in msg2
    assert "也不等于成功" in msg2


def test_all_failed_returns_nonzero() -> None:
    mod = _load_tool()
    code, _ = mod.update_verdict(inserted=0, skipped=0, errors=100)
    assert code == 1


# ---------------------------------------------------------------------------
# 结构:main() 必须**用**那个结论,而不是自己写死 0
# ---------------------------------------------------------------------------


_TOOLS = {
    "tools/render_top5_presets_html.py": "main",
    "tools/rerun_top_presets.py": "main",
    "tools/run_all_backtests_html.py": "main",
    "tools/update_db_direct.py": "main",
}


@pytest.mark.parametrize("rel,func", sorted(_TOOLS.items()))
def test_tool_exit_code_comes_from_the_shared_verdict(rel: str, func: str) -> None:
    """**家族**守卫:结论必须来自共享判定(`core.cli_verdict`),且不得再写死 `return 0`。

    实测(附六十三):五个工具里**四个**都是
    `except Exception → print(ERROR) → return 0` —— 其中 `run_all_backtests_html`
    甚至**已经在数 `error_count`**,却仍然返回 0。判据用 AST:注释里写"我们返回了正确
    退出码"不算。
    """
    tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
    fns = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func
    ]
    assert len(fns) == 1, f"{rel}: 找不到唯一的 {func}()"
    fn = fns[0]

    calls = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id in {"cli_verdict", "update_verdict"}
    ]
    assert calls, (
        f"§0 VIOLATION: {rel} 的 {func}() 未使用共享判定 —— 退出码又回到写死的值"
    )

    literal_zero_returns = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)
        and n.value.value == 0
    ]
    assert not literal_zero_returns, (
        f"§0 VIOLATION: {rel} 的 {func}() 里仍有写死的 `return 0`(第 "
        f"{[n.lineno for n in literal_zero_returns]} 行)—— 部分失败会被报成成功"
    )


def test_shared_verdict_is_the_single_implementation() -> None:
    """共享判定只应有一处实现(`core/cli_verdict`),各工具不得各写一份映射。"""
    import importlib.util as _iu

    spec = _iu.spec_from_file_location(
        "core_cli_verdict", REPO_ROOT / "core" / "cli_verdict.py"
    )
    mod = _iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.cli_verdict(failures=1, attempted=2, succeeded=1, what="x")[0] == 1
    assert mod.cli_verdict(failures=0, attempted=2, succeeded=2, what="x")[0] == 0

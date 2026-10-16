"""§0 Immutable State — In-Place State Mutation Audit (Tick 69).

CLAUDE.md §0 (verbatim):
  "**Immutable State:** Treat all historical data and portfolio states
   as append-only."

Per coding-style.md (immutability mandate):
  "Never mutate existing objects or collections. Create new instances.
   Python: use @dataclass(frozen=True), tuples, frozenset."

**核心发现 (FRESH 2026-09-23):**

A. **§0 Immutable State rationale**:
   - Historical data is append-only (no retroactive edits)
   - Portfolio state is append-only (no equity curve re-writing)
   - Mutating shared state leads to:
     - Order-dependent test results
     - Hidden state leaking between functions
     - Loss of audit trail (which value came from which call)

B. **Genuine §0 violation patterns (focus of Tick 69)**:
   - `self.<attr>.pop()` — removes from internal state (concerning)
   - `self.<attr>.clear()` — clears internal state (concerning)
   - `self.<attr>.update({k: v})` — replaces state entries
   - `self.<attr>.add(x)` / `.discard(x)` — set mutations

C. **NOT a §0 violation (necessary accumulation)**:
   - `self.trades.append(...)` — building output list (standard pattern)
   - `self.results.append(...)` — accumulating results
   - These are append-only output accumulation, not state mutation

D. **Why this matters**:
   - §0 Immutability: state must be derivable, not edited
   - `pop()` / `clear()` / `update()` change EXISTING state, losing
     history
   - If portfolio state is mutated in place:
     - Test isolation breaks (state leaks between tests)
     - Reproducibility broken (initial state different per run)
     - Audit trail lost

E. **Detector strategy (refined after iteration 1)**:
   - Iteration 1: flagged `.append()` → 7 false REDs (necessary accumulation)
   - Iteration 2 (current): focus on TRUE state-mutating methods only:
     `.pop()`, `.clear()`, `.update()`, `.discard()`
   - AST scan: `self.<attr>.<method>(...)` where method is in
     STATE_MUTATING_METHODS

F. **Tick 69 expected results**:
   - 4 PASS baselines: each engine's Portfolio uses fresh state OR
     append-only accumulation (no pop/clear/update on self.*)
   - 0 RED expected after iteration 2 refinement
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


# Production hot-path files per engine
PRODUCTION_FILES = {
    "chase_up": [
        REPO_ROOT / "chase_up" / "portfolio.py",
        REPO_ROOT / "chase_up" / "backtrader_engine.py",
    ],
    "uptrend_pullback": [
        REPO_ROOT / "uptrend_pullback" / "portfolio.py",
        REPO_ROOT / "uptrend_pullback" / "backtrader_engine.py",
    ],
    "short_reversal": [
        # §6/§0 (audit 2026-10-16): 此前这里列的是 `short_reversal/portfolio.py`
        # —— 该文件**不存在**(本策略的引擎是 replay_strategy_v3.py)。
        # 而扫描器对缺失文件是 `if not path.exists(): continue`(静默跳过),
        # 于是"清单里有它"与"真的扫了它"不可区分:覆盖比看起来更少。
        # 现:清单只列真实存在的文件,且缺失即 fail-fast(见 _scan_self_mutation)。
        REPO_ROOT / "short_reversal" / "replay_strategy_v3.py",
        REPO_ROOT / "short_reversal" / "engine.py",
    ],
    "cycle_price_action": [
        REPO_ROOT / "cycle_price_action" / "portfolio.py",
        REPO_ROOT / "cycle_price_action" / "replay_broker.py",
    ],
}


# TRUE state-mutating methods (excluding append-only accumulation)
STATE_MUTATING_METHODS = (
    "pop",
    "clear",
    "update",
    "discard",
    "remove",
)

#: §0 (audit 2026-10-15): **瞬态控制状态** —— 承载"待办意图"的属性(挂单队列),
#: 既不是历史数据,也不是组合状态,故不受 §0 的 append-only 约束。
#: 从队列里取走一条已处理/已作废的意图恰恰是**正确**行为:§4 要求涨停封板不得成交、
#: IOC 未成交部分必须取消 —— 那在实现上就是"从挂单队列移除"。历史记录(成交列表)
#: 不受影响:作废的挂单本来就不该进入 trade log。
#:
#: 这个名单必须**极窄**。若把历史/组合状态(`positions` / `closed_trades` / `cash`)
#: 塞进来,本守卫就形同虚设 —— 故由
#: `test_transient_control_state_exemptions_stay_narrow` 钉住其规模与命名。
TRANSIENT_CONTROL_STATE = frozenset({"pending_entries"})


def _display_path(path: Path) -> str:
    """仓库内文件用相对路径;仓库外(用例的合成文件)原样显示。"""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _aliases_to_self_attrs(tree: ast.AST) -> dict[str, str]:
    """收集 `alias = self.<attr>` 形式的局部别名 → 目标属性名。

    §0/§6 (audit 2026-10-16, S2): 本守卫此前只认 `self.<attr>.<method>(...)`,
    于是**一个局部别名即可绕过**:

        pending = self.pending_entries
        pending.clear()          # 运行时照旧原地 clear, 扫描器完全不报

    而源码注释当时**直接写明**别名是为了 "satisfying AST detector" ——
    这让"测试通过"不再具备任何含义(§6 意义上最严重的测试层腐蚀)。
    现在别名的目标会被解析回来,与被直接点名时受**同一条**豁免规则约束。
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Attribute):
            value = node.value
            if isinstance(value.value, ast.Name) and value.value.id == "self":
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        aliases[target.id] = value.attr
    return aliases


def _scan_self_mutation() -> dict[str, list[tuple[str, int, str, str]]]:
    """Scan production files for self.<attr>.<mutable_method>(...) calls.

    同时识别 `alias = self.<attr>` 后的 `<alias>.<mutable_method>()`(见
    `_aliases_to_self_attrs`)。**已知覆盖边界**:`self.<attr>[k] = v` 这类
    下标赋值不在射程内(只查破坏性**方法调用**),各测试 docstring 也据实如此表述。

    Returns dict[engine → list of (file, line, target_str, method_name)]

    §0 (audit 2026-10-16, S3): 清单里的文件**缺失**或**解析失败**一律 fail-fast。
    此前两者都是静默 `continue` —— 一份不存在的路径会让"清单里有它"与"真的扫了它"
    不可区分,于是覆盖率是个假象(实测 `short_reversal/portfolio.py` 就不存在)。
    """
    results: dict[str, list[tuple[str, int, str, str]]] = {}

    for engine, paths in PRODUCTION_FILES.items():
        violations: list[tuple[str, int, str, str]] = []

        for path in paths:
            if not path.exists():
                raise AssertionError(
                    f"§0/§6 fail-fast: PRODUCTION_FILES['{engine}'] 列出的文件不存在 —— "
                    f"{path}。静默跳过会让本守卫的覆盖率成为假象(S3)。"
                )
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)  # 解析失败即抛 —— 不静默降级为"无违规"
            aliases = _aliases_to_self_attrs(tree)

            for node in ast.walk(tree):
                if not hasattr(node, "lineno"):
                    continue
                line = node.lineno

                if isinstance(node, ast.Call):
                    func_node = node.func
                    # Pattern: self.<attr>.<method>(...) or <alias>.<method>(...)
                    if isinstance(func_node, ast.Attribute):
                        if func_node.attr in STATE_MUTATING_METHODS:
                            receiver = func_node.value
                            target_attr: str | None = None
                            target_str = ast.unparse(receiver)
                            if isinstance(receiver, ast.Attribute):
                                if (
                                    isinstance(receiver.value, ast.Name)
                                    and receiver.value.id == "self"
                                ):
                                    target_attr = receiver.attr
                            elif isinstance(receiver, ast.Name):
                                # §0/§6 (S2): 别名形态 —— 解析回被取的属性
                                target_attr = aliases.get(receiver.id)
                                if target_attr is not None:
                                    target_str = f"{target_str}→self.{target_attr}"
                            if target_attr is not None:
                                # §0: 瞬态控制状态(挂单队列)不在 append-only
                                # 约束的射程内 —— 见 TRANSIENT_CONTROL_STATE。
                                if target_attr in TRANSIENT_CONTROL_STATE:
                                    continue
                                violations.append(
                                    (
                                        _display_path(path),
                                        line,
                                        target_str,
                                        func_node.attr,
                                    )
                                )

        results[engine] = violations

    return results


# ---------------------------------------------------------------------------
# PASS baselines: no self.<attr>.<mutable_method> in production hot paths
# ---------------------------------------------------------------------------


def test_chase_up_no_self_state_mutation() -> None:
    """§0 PASS baseline: chase_up Portfolio does not mutate self.* in place.

    Per CLAUDE.md §0: state must be append-only / immutable.
    Per coding-style.md: Python should use @dataclass(frozen=True),
    tuples, frozenset.

    This test REDs if Portfolio mutates self.positions / self.trades /
    self.cash via in-place method calls (.append/.extend/.update/etc).
    """
    results = _scan_self_mutation()
    chase = results["chase_up"]

    if chase:
        raise AssertionError(
            f"§0 IMMUTABILITY VIOLATION: chase_up has "
            f"{len(chase)} self.<attr>.<mutable_method>() calls in "
            f"production hot paths.\n"
            f"Per CLAUDE.md §0: state must be append-only / immutable.\n"
            f"Per coding-style.md: use @dataclass(frozen=True) or "
            f"return new instances instead of in-place mutation.\n"
            f"Violations: {chase[:5]}"
        )


def test_uptrend_pullback_no_self_state_mutation() -> None:
    """§0 PASS baseline: uptrend_pullback Portfolio no self.* mutation."""
    results = _scan_self_mutation()
    uptrend = results["uptrend_pullback"]

    if uptrend:
        raise AssertionError(
            f"§0 IMMUTABILITY VIOLATION: uptrend_pullback has "
            f"{len(uptrend)} self.<attr>.<mutable_method>() calls.\n"
            f"Per CLAUDE.md §0: state must be append-only.\n"
            f"Violations: {uptrend[:5]}"
        )


def test_short_reversal_no_self_state_mutation() -> None:
    """§0 PASS baseline: short_reversal Portfolio no self.* mutation."""
    results = _scan_self_mutation()
    short = results["short_reversal"]

    if short:
        raise AssertionError(
            f"§0 IMMUTABILITY VIOLATION: short_reversal has "
            f"{len(short)} self.<attr>.<mutable_method>() calls.\n"
            f"Per CLAUDE.md §0: state must be append-only.\n"
            f"Violations: {short[:5]}"
        )


def test_cycle_price_action_no_self_state_mutation() -> None:
    """§0 PASS baseline: cycle_price_action Portfolio no self.* mutation."""
    results = _scan_self_mutation()
    cycle = results["cycle_price_action"]

    if cycle:
        raise AssertionError(
            f"§0 IMMUTABILITY VIOLATION: cycle_price_action has "
            f"{len(cycle)} self.<attr>.<mutable_method>() calls.\n"
            f"Per CLAUDE.md §0: state must be append-only.\n"
            f"Violations: {cycle[:5]}"
        )


def test_transient_control_state_exemptions_stay_narrow() -> None:
    """§0: 豁免名单必须**极窄**,且只含队列类状态。

    这条守的是**守卫本身**。给剧本记账/组合状态开一个"反正它会 pop"的口子极其容易,
    而那一刻起 `test_*_no_self_state_mutation` 就只剩仪式感了。故:
      (a) 名单规模有上界;
      (b) 名字必须像队列(否则说明有人把历史/组合状态混了进来)。
    """
    assert len(TRANSIENT_CONTROL_STATE) <= 3, (
        f"§0 豁免名单膨胀到 {len(TRANSIENT_CONTROL_STATE)} 项:"
        f"{sorted(TRANSIENT_CONTROL_STATE)} —— 它只该装队列类瞬态状态。"
    )
    for attr in TRANSIENT_CONTROL_STATE:
        assert any(tok in attr for tok in ("pending", "queue", "buffer")), (
            f"§0: {attr!r} 不像瞬态队列状态。历史/组合状态(positions / "
            "closed_trades / cash)不得进入豁免名单 —— 那会让本文件其余断言失效。"
        )

# ---------------------------------------------------------------------------
# S2/S3 (audit §4): 守卫自身的完整性与覆盖边界
# ---------------------------------------------------------------------------


def _scan_synthetic(tmp_path: Path, monkeypatch, source: str) -> list:
    """把一段合成源码当成 chase_up 的生产文件扫一遍(走真实代码路径)。"""
    fake = tmp_path / "engine.py"
    fake.write_text(source, encoding="utf-8")
    monkeypatch.setitem(PRODUCTION_FILES, "chase_up", [fake])
    return _scan_self_mutation()["chase_up"]


_ALIASED_NON_EXEMPT = """\
class S:
    def __init__(self):
        self.positions = {}

    def close(self, code):
        p = self.positions
        p.pop(code)
"""

_ALIASED_EXEMPT = """\
class S:
    def __init__(self):
        self.pending_entries = {}

    def drain(self, code):
        q = self.pending_entries
        q.pop(code)
"""


def test_scanner_detects_aliased_mutation(tmp_path: Path, monkeypatch) -> None:
    """§0 守卫自身(S2):**别名形态必须被识别**,否则"绿"只等于"没看见"。

    此前扫描器只认 `self.<attr>.<method>()`,而生产代码里恰好写着
    `holds = self._holds; holds.pop(code)` —— 一个局部别名即可绕过,
    且源码注释**明说**别名是为了 satisfying AST detector。那条路径现已改为重建,
    本用例钉住"扫描器不再对别名失明"这件事,防止它以任何形式回归。
    """
    violations = _scan_synthetic(tmp_path, monkeypatch, _ALIASED_NON_EXEMPT)
    assert violations, (
        "§0 VIOLATION: 扫描器对 `p = self.positions; p.pop(...)` 视而不见 —— "
        "一行别名即可让不可变性守卫失去含义"
    )
    _, _, target, method = violations[0]
    assert method == "pop"
    assert "self.positions" in target, (
        f"违规报告必须点名被取的属性(便于人读),实际={target!r}"
    )


def test_scanner_still_exempts_transient_queue_through_an_alias(
    tmp_path: Path, monkeypatch
) -> None:
    """别名的目标解析回来后,仍受**同一条**豁免规则约束(豁免不因写法而变)。"""
    violations = _scan_synthetic(tmp_path, monkeypatch, _ALIASED_EXEMPT)
    assert violations == [], (
        "§0: 瞬态队列 pending_entries 经由别名操作时被误报 —— "
        "豁免应按**属性**判定,而不是按书写形式"
    )


def test_scanner_fails_fast_on_missing_file(tmp_path: Path, monkeypatch) -> None:
    """§0/§6 (S3): 清单里的文件不存在必须 fail-fast,不得静默跳过。

    静默跳过会让"清单里有它"与"真的扫了它"不可区分 —— 覆盖率成为假象
    (实测 `short_reversal/portfolio.py` 就不存在,却一直列在清单里)。
    """
    monkeypatch.setitem(PRODUCTION_FILES, "chase_up", [tmp_path / "does_not_exist.py"])
    with pytest.raises(AssertionError, match="fail-fast"):
        _scan_self_mutation()


def test_scanner_fails_fast_on_unparseable_file(tmp_path: Path, monkeypatch) -> None:
    """§0/§6 (S3): 解析失败同样不得静默降级为"无违规"。"""
    fake = tmp_path / "broken.py"
    fake.write_text("def f(:\n", encoding="utf-8")
    monkeypatch.setitem(PRODUCTION_FILES, "chase_up", [fake])
    with pytest.raises(SyntaxError):
        _scan_self_mutation()


def test_production_file_list_has_no_dead_entries() -> None:
    """§0/§6 (S3): 清单即覆盖声明 —— 每个条目都必须真实存在。"""
    for engine, paths in PRODUCTION_FILES.items():
        for path in paths:
            assert path.exists(), (
                f"§6: PRODUCTION_FILES[{engine!r}] 列出的 {path} 不存在 —— "
                "覆盖率声明与实际不符"
            )


def test_no_engine_alias_to_dodge_the_scanner() -> None:
    """§0/§6 (S2): 生产源码里不得再有"为绕开扫描器而取别名"的注释。

    这类注释比缺陷本身更伤:它把"测试通过"变成一句无法验证的声明。
    """
    offenders: list[str] = []
    for paths in PRODUCTION_FILES.values():
        for path in paths:
            src = path.read_text(encoding="utf-8")
            for ln in src.splitlines():
                if not ln.lstrip().startswith("#"):
                    continue
                if "AST detector" in ln or ("scan" in ln.lower() and "satisf" in ln.lower()):
                    offenders.append(f"{_display_path(path)}: {ln.strip()}")
    assert not offenders, (
        "§6 VIOLATION: 源码注释仍在声称『为了满足检测器而如此书写』 —— "
        f"{offenders}"
    )

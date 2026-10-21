"""「按源码文本下结论」的判据只能变少,不能变多 —— 棘轮(附一百四十)。

## 为什么

本册已 **6** 次在同一个形态上命中:守卫把**行为**判成**源码文本**,而
`assert "…" in src` 这类判据有且只有两个坏方向,两个方向都实测出现过:

* **太松**:注释 / 文档串能**满足**它 ⇒ 一次真实的断裂被静默放行
  (§3 公司行为接线 · §5 sweep DSR · §1 死 preset 守卫);
* **太紧**:合法重构被判**不满足** ⇒ 假红
  (§4 借券载重 · §5 `n_comparisons`)。

已改掉的四处散在四个文件里。**问题是:没有人拦着新写一条。** 本文件把"还剩多少"钉成
**只许变短的登记表**。

## 两张表,**按证据强弱分开**(不合并)

| 表 | 判据 | 处数 / 文件 |
|---|---|---|
| `KNOWN_TEXT_SHAPED_CHECKS` | 有**正面证据**指向源码:`inspect.getsource(...)`,或路径里**任一段**以 `.py` 结尾 | **142 / 34** |
| `KNOWN_UNRESOLVED_CHECKS` | 读的是文件,但路径来自**函数参数 / 变量**,静态解析不出 ⇒ 归"判不了" | **147 / 36** |

分开的理由:把"判不了"并进"通过"正是本册记过的失效;而把它并进"源码",一旦那条其实是读
HTML/CSV 的,就会**假报**。两张表各自只许变短,消息里也分开报,谁涨了一目了然。

## 口径(以及它的**面**)

普查 `tests/test_*.py` 里 `"…" in X` / `X not in …` / `re.search(…, X)`,`X` 是上面那两类之一。
**不登记**:读 HTML / CSV / JSON / SQL 内容再断言其内容的 —— 那本来就该用文本。

## 局限(如实写)

* 只看 `tests/test_*.py`;
* 不追函数参数(跨过程)⇒ 那类落进 `KNOWN_UNRESOLVED_CHECKS`(方向安全:多登记不会漏);
* **不判断某条具体判据该不该改** —— 逐条升级仍是人工活(模板见附一百三十九 §5)。

## 本文件的普查工具也犯过三次同类错误(记下来,免得下次重犯)

1. 只认**字面量**路径 ⇒ 经**模块常量**传的全都落进"未知" ⇒ 差点被读成"没有这类判据";
2. 路径是**多段拼的**(`REPO_ROOT / "core" / "dual_price.py"`)而只取**第一段** ⇒
   把源码判据误判成"产物内容" ⇒ 一次性少算了 **5 倍**(56 vs 289);
3. 把"读的是 `read_text` 的实参 `encoding=\"utf-8\"`"也当成路径段。
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS = REPO_ROOT / "tests"

#: 有**正面证据**指向源码的存量(冻结)。**只许变短**;清零就从表里删掉。
KNOWN_TEXT_SHAPED_CHECKS: dict[str, int] = {
    "test_short_reversal_adj_close_indicator.py": 13,
    "test_equity_curve_csv.py": 12,
    "test_nav_gate_cycle_price_action.py": 12,
    "test_limit_up_guard_cross_engine.py": 10,
    "test_raw_prev_close_data_layer.py": 10,
    "test_volume_cap_low_bar.py": 9,
    "test_metrics_per_preset.py": 7,
    "test_short_reversal_volume_cap.py": 7,
    "test_annualization_basis.py": 5,
    "test_short_reversal_window_gate.py": 5,
    "test_backtrader_engine_net_return_entry_commission.py": 4,
    "test_cycle_limit_down_exit_guard.py": 4,
    "test_cycle_price_action_slippage_atr.py": 4,
    "test_pit_universe_4engine.py": 4,
    "test_cycle_signals_adj_close.py": 3,
    "test_fast_scanner_matches_engine.py": 3,
    "test_nav_gate_cross_preset.py": 3,
    "test_wfv_eval_oos_discipline.py": 3,
    "test_core_walkforward.py": 2,
    "test_corporate_actions_dividend_deposit.py": 2,
    "test_cycle_exit_contract.py": 2,
    "test_cycle_price_action_invested_entry_fee.py": 2,
    "test_fail_fast_cross_engine.py": 2,
    "test_output_schema_canonical.py": 2,
    "test_round30_cycle_limit_up_guard.py": 2,
    "test_run_all_backtests_html_renders.py": 2,
    "test_backtest_data_integrity.py": 1,
    "test_chase_up_no_lookahead.py": 1,
    "test_cycle_backtest_fail_fast.py": 1,
    "test_cycle_main.py": 1,
    "test_equity_curve_cash_walk_output.py": 1,
    "test_final_capital_uses_nav.py": 1,
    "test_section4_microstructure_gap.py": 1,
    "test_short_reversal_signal_purity.py": 1,
}

#: 路径**静态解析不出**的存量(冻结)。同样是棘轮;单独一张表是因为它们"判不了"而不是"已知是源码"。
KNOWN_UNRESOLVED_CHECKS: dict[str, int] = {
    "test_trade_report.py": 18,
    "test_dsr_sweep_contract_cross_engine.py": 15,
    "test_retired_clauses_are_not_quoted_as_current.py": 11,
    "test_dual_price_cross_engine.py": 9,
    "test_raw_prev_close_data_layer.py": 8,
    "test_intraday_tiebreak_cycle_plumbing.py": 6,
    "test_research_scripts_reference_live_presets.py": 6,
    "test_nav_gate_cross_preset.py": 5,
    "test_section4_microstructure_gap.py": 5,
    "test_settlement_isolation_gap.py": 5,
    "test_limit_up_threshold_single_source.py": 4,
    "test_phantom_tool_detects_both_domains.py": 4,
    "test_tp_sl_are_relative_percentages.py": 4,
    "test_wfv_rigor_gap.py": 4,
    "test_3layer_architecture_gap.py": 3,
    "test_atr_slip_scale_cross_preset.py": 3,
    "test_dsr_trial_basis.py": 3,
    "test_limit_up_guard_cross_engine.py": 3,
    "test_reproducibility_audit.py": 3,
    "test_benchmark_attribution.py": 2,
    "test_chase_up_sweep_discloses_in_sample.py": 2,
    "test_corporate_actions_dividend_deposit.py": 2,
    "test_cost_model_canonical.py": 2,
    "test_pit_universe_library_signature.py": 2,
    "test_reserve_and_fee_float_drift_tolerance.py": 2,
    "test_single_window_selection_is_disclosed.py": 2,
    "test_slippage_declaration_required.py": 2,
    "test_sweep_axes_are_live.py": 2,
    "test_sweep_thresholds_oos_compliance.py": 2,
    "test_wfv_eval_oos_discipline.py": 2,
    "test_adjusted_views_do_not_silently_revert_to_raw.py": 1,
    "test_exception_specificity_audit.py": 1,
    "test_preset_subdict_splats_conform_to_signatures.py": 1,
    "test_sharpe_basis_labeled.py": 1,
    "test_slippage_policy_single_source.py": 1,
    "test_st_filter_fails_closed.py": 1,
}

_SOURCE_READERS = frozenset({"read_text", "read_bytes"})
_AST_READERS = frozenset({"getsource", "getsourcefile"})
_REGEX_FUNCS = frozenset({"search", "findall", "match", "count"})


def _module_path_constants(tree: ast.AST) -> dict[str, str]:
    """模块顶层形如 `X = "a/b.py"` 的路径常量(不认这类常量会把源码误判成"未知")。"""
    consts: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            literals = [inner.value for inner in ast.walk(node.value)
                        if isinstance(inner, ast.Constant) and isinstance(inner.value, str)
                        and ("/" in inner.value or inner.value.endswith(".py"))]
            if literals:
                consts[node.targets[0].id] = literals[0]
    return consts


def _classify(tree: ast.AST) -> dict[str, str]:
    """局部名 → `source` / `unresolved` / `artifact`。链式赋值迭代到不动点。"""
    consts = _module_path_constants(tree)
    kinds: dict[str, str] = {}
    for _ in range(4):
        grew = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            name, value = target.id, node.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
                attr = value.func.attr
                if attr in _AST_READERS:
                    kinds[name] = "source"
                    grew = True
                    continue
                if attr in _SOURCE_READERS:
                    # 只看**被读的那个对象**;不要把 `encoding="utf-8"` 这类实参当路径段。
                    read_expr = value.func.value
                    hints = [x.value for x in ast.walk(read_expr)
                             if isinstance(x, ast.Constant) and isinstance(x.value, str)]
                    hints += [consts[x.id] for x in ast.walk(read_expr)
                              if isinstance(x, ast.Name) and x.id in consts]
                    # 路径可能是**多段拼的**:任一段以 .py 结尾才算源码(取第一段会少算数倍)。
                    if any(h.endswith(".py") for h in hints):
                        kinds[name] = "source"
                    elif hints:
                        kinds[name] = "artifact"
                    else:
                        kinds[name] = "unresolved"
                    grew = True
            elif isinstance(value, ast.Name) and value.id in kinds and name not in kinds:
                kinds[name] = kinds[value.id]
                grew = True
        if not grew:
            break
    return kinds


def _text_shaped_checks_in(source: str) -> tuple[int, int]:
    """一份源码里「按源码文本下结论」的处数:`(有证据指向源码, 路径解析不出)`。"""
    tree = ast.parse(source)
    kinds = _classify(tree)
    if not kinds:
        return 0, 0
    found = {"source": 0, "unresolved": 0}

    def note(node: ast.AST) -> None:
        target: str | None = None
        if isinstance(node, ast.Compare) and any(
            isinstance(op, (ast.In, ast.NotIn)) for op in node.ops
        ):
            for operand in [node.left, *node.comparators]:
                if isinstance(operand, ast.Name) and kinds.get(operand.id) in found:
                    target = kinds[operand.id]
                    break
        elif (isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute)
              and node.func.attr in _REGEX_FUNCS
              and len(node.args) >= 2
              and isinstance(node.args[-1], ast.Name)
              and kinds.get(node.args[-1].id) in found):
            target = kinds[node.args[-1].id]
        if target:
            found[target] += 1

    for node in ast.walk(tree):
        note(node)
    return found["source"], found["unresolved"]


def unparsable_test_files() -> list[str]:
    """解析不了的 `test_*.py`。

    (把"炸在 `ast.parse` 的 traceback"变成一条**具名**判据:注入时若把某条断言截断成语法错,
     上一版会让三条判据一起红、而没人知道为什么 —— 实测栽过一次。)
    """
    bad: list[str] = []
    for path in sorted(TESTS.glob("test_*.py")):
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            bad.append(f"{path.name}: {type(exc).__name__}: {exc}")
    return bad


def current_counts() -> tuple[dict[str, int], dict[str, int]]:
    """普查当前存量:`(源码证据, 解析不出)` 两张表,只列非零。"""
    source: dict[str, int] = {}
    unresolved: dict[str, int] = {}
    for path in sorted(TESTS.glob("test_*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        try:
            s, u = _text_shaped_checks_in(text)
        except SyntaxError:
            continue  # 由 test_every_test_file_parses 具名报出,不在普查里炸
        if s:
            source[path.name] = s
        if u:
            unresolved[path.name] = u
    return source, unresolved


def test_every_test_file_parses() -> None:
    """普查的输入必须都能解析 —— 否则普查会静默少算那些文件(未扫到的与合规的一样)。"""
    bad = unparsable_test_files()
    assert not bad, "这些测试文件解析不了,普查无法覆盖它们:\n  " + "\n  ".join(bad)


def _growth(current: dict[str, int], frozen: dict[str, int]) -> dict[str, tuple[int, int]]:
    return {name: (frozen.get(name, 0), n)
            for name, n in current.items() if n > frozen.get(name, 0)}


def test_no_new_text_shaped_behaviour_checks() -> None:
    """**棘轮**:不许新增「按源码文本判行为」的判据(两类分开报)。

    新写一条时请改用 **AST**(查 `Call.func` / `Assign.targets` / `Compare`),并配一条
    **反向样本**(列出来的合法写法 + 列出来的非使用写法)—— 模板见附一百三十九 §5。
    """
    source, unresolved = current_counts()
    grown_source = _growth(source, KNOWN_TEXT_SHAPED_CHECKS)
    grown_unresolved = _growth(unresolved, KNOWN_UNRESOLVED_CHECKS)
    assert not grown_source and not grown_unresolved, (
        "有**新增**的「按源码文本判行为」判据(文件: 冻结 → 现在)\n"
        "  [有证据指向源码]\n    "
        + ("\n    ".join(f"{k}: {o} → {n}" for k, (o, n) in sorted(grown_source.items())) or "(无)")
        + "\n  [路径解析不出 —— 若它读的其实是产物,请把路径写成字面量让分类器看得见]\n    "
        + ("\n    ".join(f"{k}: {o} → {n}" for k, (o, n) in sorted(grown_unresolved.items())) or "(无)")
        + "\n这类判据对**注释**敏感(注释能满足它)、对**合法重构**不耐受(假红)。请改成 AST。"
    )


def test_the_registries_have_no_stale_entries() -> None:
    """登记表**只许变短**:清零的文件必须从表里删掉(否则冻结值会变成噪音)。"""
    source, unresolved = current_counts()
    stale = sorted(
        [f"KNOWN_TEXT_SHAPED_CHECKS: {n}" for n in KNOWN_TEXT_SHAPED_CHECKS if not source.get(n)]
        + [f"KNOWN_UNRESOLVED_CHECKS: {n}" for n in KNOWN_UNRESOLVED_CHECKS
           if not unresolved.get(n)]
    )
    assert not stale, f"这些条目已清零(或文件被删/改名),请从登记表删掉:{stale}"


def test_the_census_is_not_vacuous() -> None:
    """**非空转**:普查必须真的扫到东西 —— 解析器坏掉会让上面两条恒真。"""
    source, _unresolved = current_counts()
    assert source, "一处「有证据指向源码」的都没扫到 —— 解析器坏了,棘轮失效"


def test_the_census_classifier_has_teeth() -> None:
    """分类器本身:三类的判定各测一遍(含"多段拼路径"这个把上一版坑惨的形态)。"""
    src = (
        "import inspect, pathlib\n"
        "a = inspect.getsource(mod)\n"                                  # source(getsource)
        "b = pathlib.Path('x/y.py').read_text()\n"                      # source(.py 单段)
        "c = (ROOT / 'core' / 'dual_price.py').read_text(encoding='utf-8')\n"  # source(多段拼)
        "d = pathlib.Path('r.html').read_text()\n"                      # artifact
        "e = pathlib.Path(some_var).read_text()\n"                      # unresolved
        "assert 'a' in a\n"
        "assert 'b' in b\n"
        "assert 'c' in c\n"
        "assert 'd' in d\n"
        "assert 'e' in e\n"
    )
    assert _text_shaped_checks_in(src) == (3, 1), (
        "应判:3 处源码(a/b/c)+ 1 处解析不出(e);d 读的是 .html,不算"
    )
    assert _text_shaped_checks_in("assert 'x' in a_list\n") == (0, 0)
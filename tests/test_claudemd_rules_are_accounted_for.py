"""附九十四 —— 把**标准本身**对账:CLAUDE.md §1–§7 的每条 MUST/NEVER,谁在守它?

## 为什么需要它

前面十几轮反复出现同一个形态:**某条规则的实现散在四个引擎里,而"谁在守它"从没被清点过**
(附八十五~八十八、九十、九十一)。跨引擎契约矩阵解决了"一条规则 × N 个实现"的**存在性**,
但矩阵的**行**是人挑的 —— 没有任何东西保证"CLAUDE.md 里的规范句都被挑到了"。

这条守卫把那份名单**从标准里抽出来**:§1–§7 里凡是带 MUST / NEVER / ALWAYS / Banned 的
加粗规则名,**每一条都必须落进一张登记表**,登记它是

* `("guard", <测试文件>)` —— 有具名机械守卫;或
* `("matrix", <矩阵行名>)` —— 由跨引擎契约矩阵覆盖;或
* `("registered", <为什么不能机械检查>)` —— 显式登记,带理由。

⇒ 新增一条 MUST 而没人管它 ⇒ **红**;某条规则从标准里删掉而登记表还留着 ⇒ **红**。

## 它同时是一份**诚实的能力清单**

登记的结果(本节实测):

| | 条数 |
|---|---|
| §1–§7 的规范句 | **13** |
| 有具名守卫或矩阵覆盖 | **10** |
| 有实现但**没有任何具名守卫** | **3** |
| 显式登记为"不能机械检查 / 待决策" | 1(含在上面 13 内) |

**那 3 条没有守卫的,本节不改代码,只如实登记** —— 加一条守卫是工作量,而"哪些没被守"
这个事实本身必须先在记录里。这与本仓库一贯的"登记表必须等于实际集合"同型。

## 判据的边界(如实声明)

抽取靠**加粗规则名 + 关键词**的正则 —— 它抓的是 CLAUDE.md 的**书写格式**,不是语义。
若有人把某条 MUST 写成没有加粗标题的散文,**抽取不到它,本守卫也不会红**。
这不是能用正则补的洞;能补的是**每次改 CLAUDE.md 时跑一遍**(这正是"登记表跟着现实走"的用法)。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDEMD = REPO_ROOT / "CLAUDE.md"

_SECTION_START = "## 1. Temporal Determinism"
#: §7 是文件的最后一节 ⇒ 抽到文末。**边界靠这个常量**,改了它要同步改 docstring。
_SECTION_END: str | None = None
_NORMATIVE = re.compile(r"\b(ALWAYS|NEVER|MUST|Banned|banned)\b")
_BOLD = re.compile(r"^\s*-\s*\*\*(.+?):?\*\*")


def normative_rule_labels() -> list[str]:
    """从 CLAUDE.md §1–§7 抽出"带 MUST/NEVER/ALWAYS/Banned 的加粗规则名"。"""
    src = CLAUDEMD.read_text(encoding="utf-8")
    lo = src.index(_SECTION_START)
    hi = src.index(_SECTION_END) if _SECTION_END else len(src)
    body = src[lo:hi]
    out: list[str] = []
    for line in body.splitlines():
        m = _BOLD.match(line)
        if m and _NORMATIVE.search(line):
            out.append(m.group(1).rstrip(":").strip())
    return out


#: 规则名 → `("guard" | "matrix" | "registered" | "unguarded", 指向, 说明)`
RULE_COVERAGE: dict[str, tuple[str, str, str]] = {
    "The `AsOf(Time)` Rule": (
        "guard", "tests/test_pit_universe_4engine.py",
        "四个引擎的 PIT 成员判定;另有 3 个 `test_pit_universe_*` 与每族的 `*_no_lookahead` 同族",
    ),
    "Banned Functions": (
        "guard", "tests/test_banned_functions_section1.py",
        "`.bfill()` / `.ffill()` / `.shift(-N)` / `.rolling(center=True)` 逐个钉住",
    ),
    "Banned Global State": (
        "guard", "tests/test_banned_functions_section1.py",
        "同一条规则的姊妹项 —— **该文件的 docstring 同时引了这两条**,故两行指向同一守卫",
    ),
    "Suspension & Missing-Bar Semantics": (
        "guard", "tests/test_suspension_mark_and_no_fill.py",
        "停牌按 last raw_close 盯市、不产生成交",
    ),
    "Single-Bullet Execution (单发子弹机制)": (
        "matrix", "容量闸门: 持仓已达上限则丢弃本 bar 剩余信号 (§2)",
        "矩阵覆盖**丢弃**那半;排序那半散在 chase/uptrend 的 `sort_values([\"date\", \"score\"])` "
        "与 short_reversal 的 `v68_conviction` 预设。**cycle 按构造不适用** —— 它是"
        "**逐股独立账户**(`for code, slice in universe.items(): cerebro = ...`),每账户容量恒 1,"
        "不存在「同一账户里并发信号抢容量」的时刻",
    ),
    "Canonical Cost Model": (
        "matrix", "成本模型单源 (§2: MAX(notional × rate, min_fee),常量只在 core 定义一次)",
        "常量来自 `core.dual_price`;四族各自套用,拼法四种(见矩阵行)",
    ),
    "Partial Fill Tolerance": (
        "unguarded", "",
        "**有实现、没有具名守卫**:IOC 不排队见 `cycle_price_action/replay_broker.py` 的停牌分支注释;"
        "未用现金回退 Free_Cash 由 `tests/test_all_in_sizing_fraction_preservation.py` 间接覆盖,**不专门**",
    ),
    "Slippage as a Function of Volatility (Execution Only)": (
        "registered", "附七十九 §4 表 #1",
        "全库 100/100 preset 的 `atr_slip_scale` 都是 0 ⇒ 已发布结果全部零滑点;"
        "换算成真实标定值会改变每一个成交价,属**研究决策**,已登记待口径",
    ),
    "Exit Thresholds (TP/SL) & Target Projection": (
        "unguarded", "",
        "**有实现、没有具名守卫**:四族都以**相对百分比**表达(各引擎 `tp_pct` / `sl_pct`,"
        "且 `if tp_pct <= 0: raise` fail-fast);但**没有一条守卫**钉「不许退回绝对价差」",
    ),
    "Intraday Blindness": (
        "matrix", "同 bar 双触发取 SL 优先 (§4 Intraday Blindness)",
        "三族 fail-fast 拒绝其它 tiebreak 取值;cycle 把顺序编码在 `try_exit_with_intraday_check` 内",
    ),
    "T+1": ("matrix", "T+1: 入场当日不得退出 (CLAUDE.md §4)", "见矩阵该行(四种拼法)"),
    "Limit-Up / Limit-Down No-Fill": (
        "matrix", "涨停买入不成交 (§4: 封板买不进)",
        "同一条规则在矩阵里是**两行**(买向涨停 + 卖向跌停)—— 因为 §4 把它们写成一句但它有两个方向",
    ),
    "Banned In-Sample Grids": (
        "guard", "tests/test_single_window_selection_is_disclosed.py",
        "**机械代理**:凡调用 DSR 且**不含窗口遍历**的脚本(实测 9 个)必须声明 in-sample 并"
        "**指名**滚动窗口版本(附九十六 补上 附十七 只做了 2/9 的那一半)。"
        "⚠️ 仍未覆盖的那半:§5 的禁令本是「**拒绝写**一个直接报 max Sharpe 的网格搜索」—— "
        "「不许存在某种脚本」很难用守卫表达,故只守住「若存在则必须声明」",
    ),
    "Iterative-Tuning Accounting": (
        "guard", "tests/test_dsr_trial_basis.py",
        "每条 preset 必须声明正整数 `n_comparisons`,且必须**有消费者**;"
        "附八十九 另加了「声明上界 vs 自家 sweep 枚举数」的登记表",
    ),
    "Attribution Mandate": (
        "guard", "tests/test_attribution.py",
        "基准相对超额与 `attribute()` 的口径;四引擎的 `_benchmark_block` 由它钉住",
    ),
    "Results Stay Local": (
        "guard", "tests/test_artifact_hygiene_section7.py",
        "①结果类产物不得被 git 跟踪 ②§7 点名的每一类必须真的被 .gitignore 覆盖",
    ),
    "No Numbers in Docs": (
        "guard", "tests/test_artifact_hygiene_section7.py",
        "README / `docs/*.md` 里不得把**指标名**与**数值**写在同一行",
    ),
    "Short-Side Feasibility": (
        "unguarded", "",
        "**有声明、没有具名守卫**:`short_reversal/presets.py` 的 `BORROW_ASSUMPTION`"
        "(含 `borrow_cost_model` / `borrow_cost_rate` 与 A 股券源稀缺的现实差距说明);"
        "但**没有任何测试**断言它还在、或断言没有它就不许跑",
    ),
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def test_every_normative_rule_in_claudemd_is_accounted_for() -> None:
    """§1–§4 里带 MUST/NEVER/ALWAYS/Banned 的规则,每一条都必须登记。

    (新增一条规范句而没人管它 ⇒ 红。这是"把标准本身对账",而不是"挑几条查"。)
    """
    known = {_norm(k) for k in RULE_COVERAGE}
    missing = [r for r in normative_rule_labels() if _norm(r) not in known]
    assert not missing, (
        "§0: CLAUDE.md §1–§7 里以下规范句**没有登记谁来守它**:\n  "
        + "\n  ".join(missing)
        + "\n登记成 (guard, 测试文件) / (matrix, 矩阵行) / (registered, 为什么不能机械检查) 三者之一。"
    )


def test_the_rule_registry_has_no_stale_entries() -> None:
    """登记表必须跟着标准走:规则名被改写/删除,条目就要删。"""
    actual = {_norm(r) for r in normative_rule_labels()}
    stale = [k for k in RULE_COVERAGE if _norm(k) not in actual]
    assert not stale, (
        "以下登记项在 CLAUDE.md §1–§7 里**已不存在**(规则被改写或删除)—— 请删除或改名:\n  "
        + "\n  ".join(stale)
    )


def test_guard_links_point_at_real_tests() -> None:
    """`guard` 指向的测试文件必须存在。"""
    bad = [ref for kind, ref, _ in RULE_COVERAGE.values()
           if kind == "guard" and not (REPO_ROOT / ref).exists()]
    assert not bad, f"§0: 登记表指向了不存在的守卫文件:{bad}"


def test_matrix_links_name_a_real_row() -> None:
    """`matrix` 指向的必须是跨引擎契约矩阵里**真实存在的行名**。

    (没有这条,登记表可以写一个好听的行名,而矩阵里根本没有那一行。)
    """
    from tests.test_cross_engine_contract_matrix import CONTRACTS

    bad = [ref for kind, ref, _ in RULE_COVERAGE.values()
           if kind == "matrix" and ref not in CONTRACTS]
    assert not bad, (
        f"§0: 登记表指向了矩阵里不存在的行:{bad}\n现有行:{sorted(CONTRACTS)}"
    )


def test_unguarded_rules_are_registered_with_a_reason() -> None:
    """`unguarded` / `registered` 两类必须写明**理由**,且必须有非空指向或说明。

    这一条防的是"把不知道的东西写成 unguarded 混过去":两类都要有一句人读得懂的话。
    """
    bad = []
    for rule, (kind, ref, note) in RULE_COVERAGE.items():
        if kind not in ("unguarded", "registered"):
            continue
        if len(note.strip()) < 20:
            bad.append(f"{rule}: 理由太短")
        if kind == "registered" and not ref.strip():
            bad.append(f"{rule}: registered 必须写指向(登记在哪)")
    assert not bad, "§0: 未覆盖项的理由不足:\n  " + "\n  ".join(bad)


@pytest.mark.parametrize("kind", ["guard", "matrix", "registered", "unguarded"])
def test_every_kind_is_used(kind: str) -> None:
    """四种归类都真的用到 —— 否则说明抽取或归类退化成了单值。"""
    assert any(k == kind for k, _, _ in RULE_COVERAGE.values()), f"没有任何规则被归为 {kind}"

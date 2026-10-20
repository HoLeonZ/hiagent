r"""§6 守卫:**登记在案的未结事项必须可解析、可复现、有归属**。

## 缺陷(附一百一十二,实测)

§6 原文:「*Pre-existing failures are registered debt **with an owner**, not background noise.*」

仓库的**代码内**登记表(`KNOWN_DEAD_REFERENCES` / `KNOWN_UNRECORDED_TRIAL_COUNTS` /
`KNOWN_HOME_PATH_EXCEPTIONS` / `KNOWN_ADJUSTED_RETURN_ARTIFACT_ROWS` / `KNOWN_FAITHFUL`)
都带**对账**(只许变短)⇒ "registered" 这一半做得比条款要求的还好。

**但有一批债是"登记在文档里"的**,而它们全部指向同一句:

    「… 属未结事项,登记于审计报告 §8。」

实测三件事,合起来说明这三条**不可解析、不可证伪**:

1. 描述它们的词 —— `22-metric` / `逐 bar 序列` / `equity_curve.csv writer` ——
   在审计文档里出现 **0 次**;而 §8 是 **P0–P4 修复计划**(19 条优先级清单),
   **不是**未结事项的登记处;
2. 那份文档**只存在于 `audit/strategy-discipline` 分支**,跑测试的这个分支上**没有它**
   ⇒ 读 skip 的人**打不开那个引用**;
3. **没有任何门禁**校验这些引用(仓库里没有 `test_handoff*` / 类似的锚校验)。

⇒ 这三条债的实际形态是:**一句 skip 消息里的文字**。它可以被"修好"而无人察觉,
也可以永远挂着 —— 这正是 §6 要防的 *background noise*。

## 本文件的判据

登记改为**代码内、带 token**:

| 字段 | 作用 |
|---|---|
| token | skip 消息里引用它(`[OPEN:<TOKEN>]`),不再指向"§8"这种**整节**引用 |
| 缺什么 | 一句话 |
| **什么条件下消失** | 这条债的**可观测关闭条件** —— 比"owner 是谁"更能防它变成噪音 |
| owner | **显式字段**;空串 = 未指派,而"未指派"的**条数**记在 `KNOWN_UNASSIGNED_OWNERS`(只许变短) |

四条用例:①凡被引用的 token 必须已登记(新债不能绕过);②凡已登记的 token 必须仍被引用
(只许变短);③每条必须写清"什么条件下消失";④未指派 owner 的条数 == 登记常数
(把 §6 缺的那半**变成可见的、只许变短的数**,而不是继续静默缺席)。

## ⚠️ 关于 owner:我没有编一个名字

这个仓库的 owner 只有使用者一个人 ⇒ 把 `owner` 填成任何字符串都是**编造**。
本文件的做法是**记录"未指派"并把条数固定住**,于是:要么使用者填名字(那会红,要求同步改常数),
要么这些条目**一直显式地**未指派 —— 不会像原来那样"看起来登记过了"。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: 未结事项登记:`token -> (缺什么, **什么条件下消失**, owner)`。
#: `owner=""` = 未指派(见文件头:不编名字)。
OPEN_ITEMS: dict[str, tuple[str, str, str]] = {
    "EQUITY-CURVE-WRITER": (
        "某些引擎的 `results/` 下没有 `equity_curve.csv` —— 缺 writer。"
        "§2 的实质要求(NAV 恒等式 + 现金守恒)已有内存守卫 "
        "(`test_nav_cash_ledger_invariants.py`),缺的只是**产物**。",
        "该引擎的 `main` 能写出 `equity_curve.csv` ⇒ 那条 skip 变成真校验(产物型守卫变绿)。",
        "",
    ),
    "METRICS-22-AGG-SHORT": (
        "`short_reversal/results/backtest.json` 未产出 canonical **22-metric** 聚合 metrics。",
        "`short_reversal/results/backtest.json` 含全部 22 个 canonical 指标 ⇒ "
        "`test_short_reversal_json_has_aggregated_metrics` 变成真校验。",
        "",
    ),
    "METRICS-22-AGG-CYCLE": (
        "`cycle_price_action/results/backtest.json` 未产出 canonical **22-metric** 聚合 metrics。",
        "`cycle_price_action/results/backtest.json` 含全部 22 个 canonical 指标 ⇒ "
        "`test_cycle_price_action_backtest_json_exists_or_documented_gap` 变成真校验。",
        "",
    ),
    "CYCLE-BAR-EQUITY": (
        "`cycle_price_action` 仍缺**组合级**逐 bar 权益序列(其余三族已有)。",
        "`cycle_price_action` 的产物里出现组合级逐 bar 权益曲线 ⇒ 本条删除。",
        "",
    ),
}

#: **未指派 owner 的条数**(只许变短:填了 owner 就把它减 1)。
#: 存在的理由见文件头:§6 要求 "with an owner",而这个仓库的 owner 只有使用者一人 ——
#: 与其编一个名字,不如把这个缺口做成一个**会红、且只许变短**的数。
KNOWN_UNASSIGNED_OWNERS = 4

_CITED = re.compile(r"\[OPEN:([A-Z0-9-]+)\]")


def _test_files() -> list[Path]:
    return [p for p in sorted((REPO_ROOT / "tests").glob("*.py")) if p != Path(__file__)]


def _cited_tokens() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in _test_files():
        for m in _CITED.finditer(p.read_text(encoding="utf-8")):
            out.setdefault(m.group(1), []).append(str(p.relative_to(REPO_ROOT)))
    return out


def test_every_cited_token_is_registered() -> None:
    """① 凡被引用的 token 必须已登记 —— 新债不能靠写一句 skip 就"登记"了。"""
    cited = _cited_tokens()
    ghosts = sorted(set(cited) - set(OPEN_ITEMS))
    assert not ghosts, (
        "§6:以下 token 被 skip/docstring 引用,却**不在** `OPEN_ITEMS` 里 —— "
        "那等于用一句文字当登记:\n  "
        + "\n  ".join(f"[OPEN:{t}] 见于 {cited[t]}" for t in ghosts)
        + "\n请登记到 `OPEN_ITEMS`(缺什么 / 什么条件下消失 / owner)。"
    )
    assert cited, (
        "一条 `[OPEN:…]` 都没扫到 —— 要么登记被删光了,要么引用形态变了(本判据已空转)"
    )


def test_every_registered_token_is_still_cited() -> None:
    """② 凡已登记的 token 必须**仍被引用**(否则它已经不是"登记在案的债")。"""
    cited = set(_cited_tokens())
    stale = sorted(set(OPEN_ITEMS) - cited)
    assert not stale, (
        "以下登记项已经没有任何地方引用了 —— 说明那条债被修好或措辞改了,"
        "请从 `OPEN_ITEMS` 删掉(登记表只应当变短):\n  " + "\n  ".join(stale)
    )


def test_every_entry_says_what_would_close_it() -> None:
    """③ 每条必须写清**可观测的关闭条件**(这比"owner 是谁"更能防它变成噪音)。"""
    bad = [
        f"{t}: 关闭条件为空或太短({len(why) if why else 0} 字符)"
        for t, (_what, why, _o) in OPEN_ITEMS.items()
        if not why or len(why) < 20
    ]
    assert not bad, (
        "§6:以下登记项没有说清「什么条件下这条债消失」 —— "
        "没有关闭条件的登记,就是永久噪音:\n  " + "\n  ".join(bad)
    )


def test_no_bare_doc_registration_without_a_token() -> None:
    """⑤ **禁止裸的文档式登记**:凡出现「登记于审计报告 / 登记于审计 §」的字面量,
    同一个字面量里必须带 `[OPEN:…]` token。

    为什么要有这一条:**①②③④ 只查 token** —— 而本批要修的历史形态恰恰是
    **没有 token 的裸引用**(`"…属未结事项,登记于审计报告 §8。"`)⇒ 光有前四条,
    那种写法可以**原样再来一遍**。故把那个**动词短语**本身也钉住。

    为什么不误伤:仓库里另有一类正当引用是**出处**而非开放债 ——
    例如「审计 §8 #7b,2026-10-16 复核确认」「审计 §8 早已把…**登记为**未结事项」
    (那条已由附三十九 完成)。它们用的是「审计 §N …复核确认」/「登记**为**(早已)」,
    **不是**「登记**于**」这种"指向某处当登记册"的措辞。故判据只认 `登记于`。
    """
    import ast

    bad = []
    for p in _test_files():
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if ("登记于审计报告" in node.value or "登记于审计 §" in node.value) and not _CITED.search(node.value):
                bad.append(f"{p.relative_to(REPO_ROOT)}:{node.lineno}  …{node.value[-40:]}")
    assert not bad, (
        "§6:以下字面量用「登记**于**<某文档>」当登记册,却没有可解析的 token —— "
        "这种登记**不可证伪**,正是本批要修掉的形态:\n  "
        + "\n  ".join(bad)
        + "\n改为 `[OPEN:<TOKEN>]` 并登记到 `OPEN_ITEMS`(缺什么 / 什么条件下消失 / owner)。"
    )


def test_the_unassigned_owner_count_is_explicit_and_shrink_only() -> None:
    """④ §6 的「**with an owner**」这半:未指派的条数必须**显式**且只许变短。

    (填了 owner ⇒ 这里会红 ⇒ 逼着把常数减 1。不填 ⇒ 它一直显式地未指派,
     而不是像原来那样"看起来登记过了"。)
    """
    unassigned = [t for t, (_w, _why, o) in OPEN_ITEMS.items() if not o]
    assert len(unassigned) == KNOWN_UNASSIGNED_OWNERS, (
        f"未指派 owner 的条数从 {KNOWN_UNASSIGNED_OWNERS} 变成了 {len(unassigned)}"
        f"({sorted(unassigned)})—— 若你刚填了 owner,请把 `KNOWN_UNASSIGNED_OWNERS` 减 1;"
        "若是新登记项,请一并再加 1(并考虑把 owner 填上)。"
    )
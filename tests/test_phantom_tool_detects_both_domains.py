r"""附一百零六 —— phantom 检测工具的**两处盲区**(已实测),以及修法。

## 工具做什么

`audit_phantom.py` 的用途:检出"出场价取自**某个复权域**、而执行域应当是**原始价**"的成交
(§3 的双价铁律被违反)。它读 trades.csv,对每一笔去库里取当日的 qfq / raw open 比对。

## 盲区一:只比对 **qfq** 一个复权域

旧判据 `abs(ep - qo) < 0.01 and abs(qo - ro) > 0.5` 只拿 **qfq** 当参照。
而**今天的信号域是 hfq**(附七十六 更正过标注、附一百零二 量过四族分用两个域)——
"出场价取自信号域"这类错误会落在 **hfq** 上。

**实测(合成 trades,真实行情)**:

| exit 取自 | 旧判据 | 应当 |
|---|---|---|
| `qfq_open`(历史 bug 的域) | **报** ✓ | 报 |
| `hfq_open`(**今天的信号域**) | **不报** ✗ | **报** |
| `raw_open`(正确的执行域) | 不报 ✓ | 不报 |

## 盲区二:两个阈值都是**绝对元值**

`abs(ep - qo) < 0.01`(0.01 元)与 `abs(qo - ro) > 0.5`(0.5 元)—— 与**股价量级耦合**。
实测按价格分档(全库 10,364,755 个(票,日)):

| 股价档 | 有复权差异的行 | 其中 \|qfq−raw\| > 0.5 元 | ⇒ 工具**看不见**的比例 |
|---|---|---|---|
| [0, 5) 元 | 56.40% | **12.55%** | **≈ 77%** |
| [5, 20) 元 | 80.67% | 41.48% | ≈ 49% |
| [20, 100) 元 | 87.79% | 68.07% | ≈ 22% |
| [100, ∞) 元 | 88.19% | 80.67% | ≈ 9% |

⇒ **低价股上它几乎失明**,而那正是"qfq 与 raw 差零点几元"最容易被人忽略的地方。

**一个具体用例**(测试里用它钉住):`600795.SH 2025-09-26` ——
`qfq=4.7522 raw=4.9900`:**绝对差 0.2378 元(< 0.5 ⇒ 旧判据漏)**,相对差 **4.77%**。

## 修法(只动**检测器**,不动任何回测语义)

* 阈值改**相对**:`|exit/adj_open − 1| < 1e-4`、`|adj_open/raw_open − 1| > 5e-3`;
* **两个复权域都查**(qfq 与 hfq),命中任一即报,并在示例里注明命中哪个域。

工具不是回测路径 —— 这个改动**不改变任何回测结果**,只改变"检测器能不能看见"。
"""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from tests.conftest import require_market_db

REPO_ROOT = Path(__file__).resolve().parents[1]


#: 读 trades.csv 的 phantom 检测器 —— **一族两个**(附一百零七):
#: `uptrend_pullback/audit_phantom.py` 自称与 chase 版"同构",实测确实同构 ⇒ 同款盲区同款修。
#: (`cycle_price_action/audit_phantom.py` 是**另一种**:它做的是**源码级**审计(`checks[...]`),
#:  不读交易明细,故不在本族内。)
TRADE_CSV_TOOLS = ("chase_up.audit_phantom", "uptrend_pullback.audit_phantom")


def _tool(mod_name: str):
    return importlib.import_module(mod_name)


def _opens(code: str, d: str) -> tuple[float, float, float]:
    import duckdb

    from hiagent_config import get_db_path

    con = duckdb.connect(str(get_db_path()), read_only=True)
    try:
        row = con.execute(
            """SELECT q.open, r.open, h.open
               FROM v_daily_qfq q
               JOIN raw_kline_daily r USING (thscode, date)
               JOIN v_daily_hfq h USING (thscode, date)
               WHERE q.thscode=? AND q.date=?""",
            [code, d],
        ).fetchone()
    finally:
        con.close()
    assert row is not None, f"夹具失效:{code} {d} 在库里找不到"
    return float(row[0]), float(row[1]), float(row[2])


def _run(tmp_path: Path, mod_name: str, code: str, d: str, exit_price: float) -> int:
    p = tmp_path / f"{mod_name.replace('.', '_')}.csv"
    pd.DataFrame([{
        "thscode": code, "entry_date": d, "exit_date": d,
        "exit_price": exit_price, "exit_reason": "TP",
    }]).to_csv(p, index=False)
    return int(_tool(mod_name).audit_trades_csv(p).get("phantom", -1))


#: 高价票:旧判据在这里**能**触发(qfq 与 raw 差 601 元) ⇒ 用来钉"域"这一半。
_HIGH = ("688256.SH", "2026-05-07")
#: 低价票:绝对差 0.2378 元 < 旧阈值 0.5 ⇒ 旧判据**漏**;相对差 4.77% ⇒ 新判据抓。
#: 用来钉"相对化"那一半,并**当场证明那个修法是必要的**。
_LOW = ("600795.SH", "2025-09-26")


@pytest.mark.parametrize("mod_name", TRADE_CSV_TOOLS)
@pytest.mark.parametrize("code_date", [_HIGH, _LOW], ids=["高价票", "低价票"])
@pytest.mark.slow
def test_both_adjusted_domains_are_detected_but_raw_is_not(tmp_path, mod_name, code_date) -> None:
    require_market_db()
    code, d = code_date
    qfq, raw, hfq = _opens(code, d)

    assert _run(tmp_path, mod_name, code, d, qfq) >= 1, f"{mod_name} {code} {d}: qfq 域未报"
    if abs(hfq / raw - 1.0) > 5e-3:
        assert _run(tmp_path, mod_name, code, d, hfq) >= 1, (
            f"{mod_name} {code} {d}: 出场价取自 **hfq**(今天的**信号**域)却未报"
        )
    assert _run(tmp_path, mod_name, code, d, raw) == 0, (
        f"{mod_name} {code} {d}: 出场价取自 **raw**(正确的执行域)却被误报"
    )


@pytest.mark.parametrize("mod_name", TRADE_CSV_TOOLS)
@pytest.mark.slow
def test_the_relative_threshold_is_necessary_on_low_priced_names(tmp_path, mod_name) -> None:
    """**证明那个修法是必要的**:低价票上,旧判据的两个绝对阈值都不成立 ⇒ 它必然漏。

    (这条不打桩、不 mock —— 直接算旧判据的两个条件,让"它漏"这件事本身成为断言。
     若哪天数据变了、这组阈值恰好都成立,本用例会红,提醒换样本。)
    """
    require_market_db()
    code, d = _LOW
    qfq, raw, hfq = _opens(code, d)
    # 旧判据:`abs(ep - qo) < 0.01 and abs(qo - ro) > 0.5`
    old_gap_significant = abs(qfq - raw) > 0.5
    assert not old_gap_significant, (
        f"夹具失效:{code} {d} 的 |qfq-raw| = {abs(qfq - raw):.4f} 已 > 0.5,"
        "旧的绝对阈值也能触发 ⇒ 本用例证明不了'相对化是必要的'"
    )
    assert abs(qfq / raw - 1.0) > 5e-3, "夹具失效:该样本的相对差不够大"
    # ⇒ 旧判据在这只票上必然漏,而新判据(相对)照常命中
    assert _run(tmp_path, mod_name, code, d, qfq) >= 1, "新判据在这只低价票上未命中"


def test_every_trade_csv_phantom_tool_uses_the_relative_dual_domain_rule() -> None:
    """**族守卫**:凡读 trades.csv 的 phantom 检测器,都必须用**相对**阈值 + **两个**复权域。

    (附一百零六 只修了 chase 版;附一百零七 发现 uptrend 版**同构且同盲**。
     这条把"族"钉住 —— 第三个同类工具不能悄悄带着绝对阈值进来。)
    """
    import re

    family = []
    for f in sorted(REPO_ROOT.glob("*/audit_phantom.py")):
        src = f.read_text(encoding="utf-8")
        if "read_csv" in src:          # 读交易明细的那种;源码级审计(cycle)不在族内
            family.append((f, src))
    assert len(family) == len(TRADE_CSV_TOOLS), (
        f"读 trades.csv 的 phantom 工具实际有 {len(family)} 个({[f.name for f, _ in family]}),"
        f"而 TRADE_CSV_TOOLS 里写了 {len(TRADE_CSV_TOOLS)} 个 —— 族变了,请同步"
    )
    bad = []
    for f, src in family:
        problems = []
        # ⚠️ 判据要落在**用法**上,不是"常量有没有声明":实测第一版查的是
        # "_PRICE_MATCH_REL 出现过" + "hfq_open 出现过",而把判据退回旧版时这两样**都还在**
        # (常量仍声明、查询仍取 hfq_open)⇒ 它**没红**。这正是本会话反复记的那条:
        # 守卫要盯"有没有在用",不是"有没有那个名字"。
        if not re.search(r"<\s*_PRICE_MATCH_REL", src):
            problems.append("判据没在用相对阈值 `_PRICE_MATCH_REL`")
        if not re.search(r"<=\s*_MIN_ADJ_GAP_REL", src):
            problems.append("没在用 `_MIN_ADJ_GAP_REL`")
        # 两个复权域都要**进循环**(qfq 与 hfq 同时出现在同一个 for 的元组里)
        if not re.search(r'for name, adj_open in \(\(\s*"qfq".*"hfq"', src, re.S):
            problems.append("判据没有同时对 qfq 与 hfq 两个域求值")
        if not re.search(r"abs\(ep\s*/\s*adj_open", src):
            problems.append("价格匹配不是**相对**判据(未见 `abs(ep / adj_open` )")
        if problems:
            bad.append(f"{f.relative_to(REPO_ROOT)}: {';'.join(problems)}")
    assert not bad, (
        "§3: 以下 phantom 检测器**没有在用**「相对阈值 + 双复权域」的判据"
        "(低价股上会静默失明、hfq 域的错误看不见):\n  " + "\n  ".join(bad)
    )

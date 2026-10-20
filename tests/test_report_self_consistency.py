"""报告层**自洽**守卫(附七十三):标题声称的排序/方向必须与**表体**一致。

## 为什么需要一条通用的

本轮的三个消费端发现全落在报告层(附六十一 的日期反推、七十一 的 `sharpe_kind` 不渲染、
七十二 的**标题与表相反** + 旧快照混排)。引擎那一侧有 golden 基线守着,**报告层没有** ——
所以这类债会积在那里,而且**逐个工具人工核是抓不完的**:我刚把回撤榜的方向修好,
转头又在另一个工具里把"改排序键却忘了改声称"重犯了一遍。

故这里钉**性质**而不是逐个数字:

  1. **标题 ↔ 表体**:凡 `<h3>按 <列> …排序</h3>` 后的那张表,表体必须在**该列**上单调;
     标题若写明方向(升序/降序/最小在前),单调方向必须**与之一致**。
  2. **打印的声称 ↔ 实际顺序**:榜单第一行形如 `(Sharpe DESC, CAGR DESC, max_dd DESC)`,
     解析后逐键与实际顺序比对(可机检的声称;改键而忘改声称 ⇒ 红)。
  3. **单元格不漏 NaN/inf/None**(本仓库真出过:`bar_pct` 绕过 `_fmt_pct` 把 `width:nan%`
     写进 HTML,见 `run_all_backtests_html.py` 里那段 §0 注释)。
  4. **表头列数与每行单元格数一致**(行里有锚点标签时允许 ≥,但不得少于表头)。
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_TAG = re.compile(r"<[^>]+>")
_TABLE = re.compile(r"<table>(.*?)</table>", re.S)
_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
_TH = re.compile(r"<th[^>]*>(.*?)</th>", re.S)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_H3 = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)


def _load(rel: str, name: str):
    path = REPO_ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"无法加载 {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text(html_fragment: str) -> str:
    return _TAG.sub(" ", html_fragment).replace(" ", " ").strip()


def _num(s: str) -> float | None:
    t = _text(s).replace(",", "").replace("%", "").replace("+", "")
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    return float(m.group(0)) if m else None


# ---------------------------------------------------------------------------
# 夹具:各工具的渲染产物
# ---------------------------------------------------------------------------


def _html_tool():
    return _load("tools/run_all_backtests_html.py", "run_all_bt")


def _rerun_tool():
    return _load("tools/rerun_top_presets.py", "rerun_top")


def _row(preset, sharpe=1.0, cagr=0.1, dd=-0.05, kind="daily_returns_annualized",
         vintage="fresh"):
    return {"preset": preset, "sharpe": sharpe, "cagr": cagr, "max_dd": dd,
            "sharpe_kind": kind, "data_vintage": vintage, "trades": 10,
            "win_rate": 0.5}


def _cross_strategy_html(rows) -> str:
    mod = _html_tool()
    return mod._render_cross_strategy(
        {"strategies": [{"name": "s", "title": "T", "rows": rows}]}
    )


# ---------------------------------------------------------------------------
# 1 · 标题 ↔ 表体
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rows", [
    # 回撤差异明显(附七十二 的那组)
    [_row("small_dd", dd=-0.05), _row("BIG_dd", dd=-0.30)],
    # 三个指标各自有显著差异
    [dict(_row("a"), sharpe=0.5, cagr=0.02, max_dd=-0.40),
     dict(_row("b"), sharpe=3.0, cagr=0.90, max_dd=-0.05)],
])
def test_heading_direction_matches_the_table_body(rows) -> None:
    """`<h3>按 X …</h3>` 后的表必须在 X 列上单调,且方向与标题一致。"""
    html = _cross_strategy_html(rows)
    headings = [(m.start(), _text(m.group(1))) for m in _H3.finditer(html)]
    tables = [(m.start(), m.group(1)) for m in _TABLE.finditer(html)]
    assert headings and tables, "渲染里没有找到 h3/table,选择器可能失效"

    checked = 0
    for pos, title in headings:
        m = re.search(r"按\s*(\w+)\s*", title)
        if not m:
            continue
        col_name = m.group(1)
        after = [t for p, t in tables if p > pos]
        assert after, f"标题「{title}」后面没有表"
        body, header = after[0], None
        header_cells = [_text(c) for c in _TH.findall(body)]
        idx = next((i for i, h in enumerate(header_cells)
                    if col_name.lower() in h.lower()), None)
        assert idx is not None, f"标题提到 {col_name},但表头 {header_cells} 里没有这一列"
        vals = [v for v in (_num(c) for row in _ROW.findall(body)[1:]
                            for c in [_TD.findall(row)[idx]] if _TD.findall(row))
                if v is not None]
        assert len(vals) >= 2, f"{col_name} 列取不到可比的值:{vals}"

        non_increasing = all(a >= b - 1e-12 for a, b in zip(vals, vals[1:]))
        non_decreasing = all(a <= b + 1e-12 for a, b in zip(vals, vals[1:]))
        assert non_increasing or non_decreasing, (
            f"标题「{title}」声称按 {col_name} 排序,但表体 {vals} 既不升也不降"
        )
        if "降序" in title or "最小在前" in title:
            assert non_increasing, f"标题「{title}」但表体 {vals} 不是降序"
        if "升序" in title:
            assert non_decreasing, f"标题「{title}」但表体 {vals} 不是升序"
        checked += 1
    assert checked >= 3, f"只核到 {checked} 张带方向声称的表,覆盖不足"


# ---------------------------------------------------------------------------
# 2 · 打印的声称 ↔ 实际顺序(rerun 工具)
# ---------------------------------------------------------------------------


def _claimed_keys(claim_line: str) -> list[tuple[str, bool]]:
    """解析 `(Sharpe DESC, CAGR DESC, max_dd DESC)` → [(列, 是否降序)]。"""
    inner = re.search(r"\((.*)\)", claim_line)
    assert inner, f"声称行格式不认识:{claim_line}"
    out = []
    for part in inner.group(1).split(","):
        bits = part.strip().split()
        assert len(bits) == 2, f"声称项格式不认识:{part!r}"
        name, direction = bits[0], bits[1].upper()
        assert direction in ("ASC", "DESC"), f"方向不认识:{direction}"
        out.append((name, direction == "DESC"))
    return out


def test_printed_rank_claim_matches_the_actual_order() -> None:
    """榜单的**可机检声称**必须与实际顺序一致(改键忘改声称 ⇒ 红)。

    这正是附七十三 的起因:我把 max_dd 的键改成降序后,这一行**还写着 ASC** ——
    刚在隔壁那张表修掉"标题与表相反",转头自己又造了一遍。
    """
    mod = _rerun_tool()
    claims = _claimed_keys(mod._TOP5_CAVEAT[0])
    rows = [
        _row("a", sharpe=2.0, cagr=0.10, dd=-0.05),
        _row("b", sharpe=2.0, cagr=0.10, dd=-0.30),   # 与 a 只在回撤上不同
        _row("c", sharpe=2.0, cagr=0.50, dd=-0.10),
        _row("d", sharpe=1.0, cagr=0.99, dd=-0.01),
    ]
    ranked = mod.rank_presets(rows)

    # 判据必须按**键元组**比对,而不是"每个键各自全局单调":
    # 后两个键只在**并列时**起作用 —— 我第一版就是这么写错的,于是跨 Sharpe 分组时
    # CAGR 自然不单调,断言假红。(这正是本审计反复记的"判据本身写错"。)
    # 声称里用的是**展示名**(Sharpe / CAGR / max_dd),数据键是小写:
    # 大小写不敏感地解析到真实键(解析不到就直接报错,而不是静默跳过这一列 ——
    # 静默跳过会让"声称了一个不存在的列"也变成绿的)。
    def key_of_claim(name: str) -> str:
        for k in rows[0]:
            if k.lower() == name.lower():
                return k
        raise AssertionError(f"声称里的列 {name!r} 在数据里找不到(可用键:{sorted(rows[0])})")

    resolved = [(key_of_claim(n), d) for n, d in claims]

    def key_of(r):
        return tuple(-r[k] if desc else r[k] for k, desc in resolved)

    expect = [r["preset"] for r in sorted(rows, key=key_of)]
    got = [r["preset"] for r in ranked]
    assert got == expect, (
        f"声称 {[f'{n} {"DESC" if d else "ASC"}' for n, d in claims]} "
        f"⇒ 应为 {expect},实际 {got}"
    )


# ---------------------------------------------------------------------------
# 3/4 · 两条对**任何**渲染产物都成立的不变量
# ---------------------------------------------------------------------------


def _all_tables(html: str) -> list[str]:
    return _TABLE.findall(html)


@pytest.mark.parametrize("which", ["cross_strategy", "full_page"])
def test_no_nan_inf_or_none_leaks_into_cells(which: str) -> None:
    """单元格里不得出现 nan / inf / None / NaT 字样。

    (`bar_pct` 曾绕过 `_fmt_pct` 把 `width:nan%` 写进 HTML —— 那条是**局部**修的;
    这里把它变成对**整份产物**的检查。)
    """
    rows = [_row("ok"), dict(_row("bad"), cagr=float("nan"),
                             sharpe=float("inf"), max_dd=None)]
    if which == "cross_strategy":
        html = _cross_strategy_html(rows)
    else:
        html = _html_tool().render_html({
            "started_at": "x", "elapsed_seconds": 1.0, "start": "a", "end": "b",
            "db_path": "c", "error_count": 0,
            "strategies": [{"name": "s", "title": "T", "engine": "e",
                            "description": "d", "rows": rows}],
        })
    cells = [_text(c) for c in _TD.findall(html)] + [_text(c) for c in _TH.findall(html)]
    bad = [c for c in cells
           if re.search(r"\b(nan|inf|-inf|none|nat)\b", c, re.I) and c.strip() not in ("", "-")]
    assert not bad, f"渲染产物里泄漏了非法值:{bad[:5]}"


@pytest.mark.parametrize("which", ["cross_strategy", "full_page"])
def test_every_row_has_at_least_as_many_cells_as_the_header(which: str) -> None:
    """每行单元格数不得少于表头列数(少了就是表结构坏了)。"""
    rows = [_row("a"), _row("b")]
    html = _cross_strategy_html(rows) if which == "cross_strategy" else \
        _html_tool().render_html({
            "started_at": "x", "elapsed_seconds": 1.0, "start": "a", "end": "b",
            "db_path": "c", "error_count": 0,
            "strategies": [{"name": "s", "title": "T", "engine": "e",
                            "description": "d", "rows": rows}],
        })
    for t in _all_tables(html):
        trs = _ROW.findall(t)
        assert trs, "空表"
        header_n = len(_TH.findall(trs[0]))
        if header_n == 0:
            continue
        for tr in trs[1:]:
            assert len(_TD.findall(tr)) >= header_n, (
                f"某行只有 {len(_TD.findall(tr))} 格,表头有 {header_n} 列"
            )

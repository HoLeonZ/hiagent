"""§0/§5:网格**有没有真的在扫**(CLAUDE.md §2/§5 单源)。

## 为什么需要它

一个 sweep 报表看起来像"敏感性表":每行一个参数取值,每列一个指标。**但它可能是平的** ——
所有 combo 产出**逐位相同**的结果,而报表照样把它印成一张表,读者会据此得出
"这个参数不敏感"的结论。

实测(附八十七,`uptrend_pullback/results/sweep_v33_long.json` 这份**已经落盘的产物**):

| 网格 | combo 数 | 不同结果数 |
|---|---|---|
| `fixed_tp_sl` | 30 | **1** |
| `loosen_signals` | 36 | **1** |

两条轴的失效原因**不同**,而**表面上都看不出来**:

1. `fixed_tp_sl` 变的是 `tp_pct`/`sl_pct`,而该脚本的 base 里 `atr_tp_mult`/`atr_sl_mult`
   都有值 ⇒ 引擎的 `use_atr` 为真时**按设计忽略**这两个键(base 自己都注释了
   「占位,当 atr 模式时不使用」)⇒ 30 个 combo 完全等价;
2. `loosen_signals` 把键写成了 `min_above_ma60_ratio`(顶层),而信号函数收到的是
   `**cfg["signal"]` ⇒ 三个键**从来没被传进去** ⇒ 36 个 combo 完全等价。
   (正确拼法是 `signal.min_above_ma60_ratio`;同目录 v2~v5 都这么写。)

### 判据为什么是"结果相同"而不是"键有没有生效"

"这个键引擎认不认"要**按引擎逐条推**(而且会随引擎演进而变)。"结果是否相同"是**观测**,
不依赖任何关于引擎的知识,也不会因为引擎改了而失效。代价:一个**真正的**平台期
(参数确实不敏感)也会被报出来 —— 所以本函数只**报警**,不判违规;报出来的网格需要人看一眼。

这与 §0 的"静默的零"是同一条:**不许把一个没有发生的效果,印成一张看起来发生了的表。**
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

#: 默认用来判"两个 combo 是不是同一个结果"的指标列。
#: 取"足以刻画一次回测结果"的量的并集 —— 少取会低估重复(把两张不同的表判成同一张),
#: 多取会把"真的相同"拆开(浮点尾数不同)。各脚本可按自己发布的列覆盖。
DEFAULT_METRIC_KEYS: tuple[str, ...] = (
    "cagr", "sharpe", "total_yield", "max_dd", "trades_count", "trades",
    "win_rate", "signals", "final_equity", "final_capital",
)


def distinct_result_count(
    rows: Sequence[Mapping], metric_keys: Sequence[str]
) -> int:
    """`rows` 里按 `metric_keys` 去重后的**不同结果数**。

    `metric_keys` 取"足以刻画一次回测结果"的量的并集 —— 少取会低估重复
    (把两张不同的表判成同一张),多取会把"真的相同"拆开。
    """
    seen = set()
    for r in rows:
        seen.add(tuple(r.get(k) for k in metric_keys))
    return len(seen)


def collapsed_grids(
    grids: Mapping[str, Sequence[Mapping]], metric_keys: Sequence[str]
) -> list[tuple[str, int]]:
    """返回 `[(网格名, combo 数), …]` —— 那些**所有 combo 结果逐位相同**的网格。

    只报 `combo 数 > 1` 的;单 combo 的网格不算"塌"(它本来就没打算比)。
    """
    out: list[tuple[str, int]] = []
    for name, rows in grids.items():
        if len(rows) > 1 and distinct_result_count(rows, metric_keys) == 1:
            out.append((name, len(rows)))
    return out


def collapsed_grid_warning(
    grids: Mapping[str, Sequence[Mapping]], metric_keys: Sequence[str]
) -> str:
    """给"塌掉的网格"一句可直接打印的话;没有则返回空串。"""
    bad = collapsed_grids(grids, metric_keys)
    if not bad:
        return ""
    lines = [
        "  ⚠️ 以下网格的**所有 combo 结果逐位相同** —— 这条轴**没有生效**,"
        "不能当成敏感性表读:"
    ]
    lines += [f"      {name}: {n} 个 combo,1 个结果" for name, n in bad]
    lines.append(
        "    常见两种原因:①该键被 base 里的别的键**盖住**(如 atr 模式下 tp_pct/sl_pct 无效);"
        "②键路径写错了(信号参数要写 `signal.xxx`,写成顶层就不会被传给信号函数)。"
    )
    return "\n".join(lines)


__all__ = ["DEFAULT_METRIC_KEYS", "distinct_result_count", "collapsed_grids",
           "collapsed_grid_warning"]

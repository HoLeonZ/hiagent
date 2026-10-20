"""§5 Attribution Mandate — 归因(基准相对超额收益)。

CLAUDE.md §5 逐字要求:
  "**Attribution Mandate:** Headline returns MUST be reported alongside
   benchmark-relative excess return (index or style basket). Pure style-beta
   replication (e.g. size/momentum factor exposure) MUST NOT be presented as
   alpha."

为什么需要:绝对收益里混着**市场 beta**。一个在牛市里跑赢现金的策略并不因此有
alpha;把止损/择时带来的 beta 暴露当作 alpha 汇报,是审计在 §5 上点名的失败形态。

本模块是**纯函数 + 零外部依赖**(与 `core.dual_price`、`core.corporate_actions`
同约定)。基准序列由调用方注入 —— 数据获取属各引擎的数据层,不在此处。

⚠️ 当前数据缺口(必须先解决才能用)
  本地市场库(`hithink-finance data sync` 维护的 `market.duckdb`)里**只有个股日线**
  (`dim_symbol.asset_type` 全为 `a-share`),**没有任何指数序列** —— 实测
  `v_daily` / `v_daily_qfq` / `v_daily_hfq` 的代码前缀全是个股(300/002/600/…),
  查不到 000300/000905/399006 之类。因此**归因在当前数据条件下无法真正计算**。

  补齐方式(需使用者决定选哪个基准 —— 那是研究决策,不应由代码替他选):
      hithink-finance index catalog                    # 浏览可选指数
      hithink-finance index history --code 000300.SH … # 拉取日线
  CLI 具备该能力(`index catalog|constituents|snapshot|history`),但取数是**联网 +
  写入行情库**的动作,应由数据管道拥有者执行。

  在基准到位之前,任何只报绝对收益的结论都应显式标注为"未归因"。

**本模块当前是"已实现但未接线"**(2026-10-18,附六十二):`attribute()` 有完整测试
(`tests/test_attribution.py`)但**没有任何生产代码导入它** —— 它要的是**指数**收益序列。
**已接线**的那一支是 `core/benchmark.py`(风格篮子 = 该窗口 PIT 宇宙等权买入持有),
由各引擎随每次回测发布 `benchmark_kind / benchmark_return / excess_return`。
`tests/test_attribution.py::test_the_dormant_module_is_not_wired_is_registered`
把"未接线"这个现状**登记**下来:一旦有人接上,那条守卫会变红,提示同步更新本段说明。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


class BenchmarkUnavailable(ValueError):
    """基准序列缺失/不可用 —— 归因无法计算(§5)。"""


@dataclass(frozen=True)
class Attribution:
    """一次归因的结果(不可变)。"""

    benchmark_id: str
    strategy_return: float
    benchmark_return: float
    excess_return: float
    beta: float | None
    n_periods: int


def compound_return(returns: Sequence[float]) -> float:
    """按复利把逐期收益合成为区间收益: prod(1+r) - 1。"""
    acc = 1.0
    for r in returns:
        acc *= (1.0 + float(r))
    return acc - 1.0


def attribute(
    strategy_returns: Sequence[float],
    benchmark_returns: Sequence[float],
    *,
    benchmark_id: str,
) -> Attribution:
    """§5 归因:策略 vs 基准的区间收益、超额收益与 beta。

    - `excess_return = strategy_return - benchmark_return`(复利口径)
    - `beta = cov(r_s, r_b) / var(r_b)`;基准方差为 0 时返回 None 并**不伪造**数值
      (常量基准无法定义 beta,静默给 0 会把"无法计算"伪装成"无暴露")。
    - 缺基准 / 长度不一致 / 序列为空 → fail-fast,不返回一个看起来合理的残缺结果。
    """
    s = [float(x) for x in strategy_returns]
    b = [float(x) for x in benchmark_returns]

    if not benchmark_id or benchmark_id == BENCHMARK_NONE_ACKNOWLEDGED:
        raise BenchmarkUnavailable(
            "§5: 未提供可用基准 —— 头条收益必须附基准相对超额收益。"
            "若确无基准,请显式标注结论为『未归因』,而不是省略这一步。"
        )
    if not s or not b:
        raise BenchmarkUnavailable(
            f"§5: 收益序列为空(strategy={len(s)}, benchmark={len(b)})"
        )
    if len(s) != len(b):
        raise BenchmarkUnavailable(
            f"§5: 策略与基准的观测期数不一致({len(s)} vs {len(b)})—— "
            "逐期对齐后才能计算 beta 与超额"
        )

    sr = compound_return(s)
    br = compound_return(b)
    mean_s = sum(s) / len(s)
    mean_b = sum(b) / len(b)
    cov = sum((x - mean_s) * (y - mean_b) for x, y in zip(s, b)) / (len(s) - 1)
    var_b = sum((y - mean_b) ** 2 for y in b) / (len(b) - 1)
    beta = (cov / var_b) if var_b > 0 else None

    return Attribution(
        benchmark_id=benchmark_id,
        strategy_return=sr,
        benchmark_return=br,
        excess_return=sr - br,
        beta=beta,
        n_periods=len(s),
    )


#: 显式"确认无基准"的登记值。与 `SLIP_NONE_ACKNOWLEDGED` 同构:让缺口**被枚举、
#: 可审计**,而不是靠沉默存在。使用它意味着该结论只能报绝对收益,且必须如此标注。
BENCHMARK_NONE_ACKNOWLEDGED = "none-acknowledged"

__all__ = [
    "Attribution",
    "BenchmarkUnavailable",
    "BENCHMARK_NONE_ACKNOWLEDGED",
    "attribute",
    "compound_return",
]

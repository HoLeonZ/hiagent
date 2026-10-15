"""backtrader 数据源。

AShareData: 在 PandasData 基础上加 `amount`（成交额）line + V3a raw_* lines，
            供 Am60 indicator 与 dual-price execution 用。

build_per_stock_feeds: 把 DuckDB 拉出的 panel 切成 per-stock feeds 喂给 cerebro。

V3a (2026-09-22, CLAUDE.md §3): 添加 raw_open/raw_high/raw_low/raw_close lines,
strategy 在 price_source_for_execution="raw_close" 时切换 SL/TP/intraday
trigger 价格到 raw_* lines。raw_* 缺失 (NaN, LEFT JOIN miss) → fallback 到
adj open/high/low/close, baseline parity 保留。
"""
from __future__ import annotations

import backtrader as bt
import pandas as pd


class AShareData(bt.feeds.PandasData):
    """PandasData + amount line + V3a adj_* lines (v3 dual-price)。

    V3a (2026-09-22, CLAUDE.md §3) 注解:
      - short_reversal engine.py 从 v_daily 读 raw + LEFT JOIN v_daily_hfq 加 adj 列
      - Lines (in declaration order, matching params mapping):
          open, high, low, close, volume, openinterest (default) — v_daily raw
          amount (A 股特有)
          adj_open, adj_high, adj_low, adj_close (V3a, v_daily_hfq back-adjusted)
      - 当前 strategy 仍读 raw (v_daily IS raw) 作 baseline parity。完整 V3a
        信号迁移需 strategy 切到 d.adj_close 系列 — golden baseline 重生成。
      - dataname 缺 adj_* 列时, 自动注入 NaN 占位 → backtrader feed 不报错。
        Strategy 仍走 raw=close 默认路径, baseline parity 保留。
    """

    lines = (
        "amount",
        "adj_open", "adj_high", "adj_low", "adj_close",
    )
    params = (
        ("amount", "amount"),
        ("adj_open", "adj_open"),
        ("adj_high", "adj_high"),
        ("adj_low", "adj_low"),
        ("adj_close", "adj_close"),
        ("datetime", "date"),
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "close"),
        ("volume", "volume"),
        ("openinterest", -1),
    )

    def start(self):
        """V3a (2026-09-22, CLAUDE.md §3): super().start() 会通过
        colnames.index(v) 找列位置。legacy 测试 panel 缺 adj_* 列时
        ValueError。这里在 super() 之前预注入 NaN 占位列 → start() 不抛错,
        strategy 仍读 raw 域, baseline parity 保留。
        """
        if not hasattr(self.p, "dataname") or self.p.dataname is None:
            super().start()
            return
        cols = self.p.dataname.columns
        for col in ("adj_open", "adj_high", "adj_low", "adj_close"):
            if col not in cols:
                # 补 NaN 占位列 — super().start() 之后的 _load 会读到 NaN,
                # 策略仍走 raw (默认列) 路径, 不影响任何交易。
                self.p.dataname[col] = float("nan")
        super().start()


def build_per_stock_feeds(
    panel: pd.DataFrame,
    codes: list[str],
    min_bars: int = 200,
) -> list[tuple[str, AShareData]]:
    """按代码切片 panel，构建 (thscode, AShareData) 列表。

    跳过太短的序列（< min_bars bars）以免指标永远 NaN。
    默认 200 与历史一致；2-month 滚动窗口期间 panel 跨春节可能只有 ~197
    trading days,这时调用方可传 min_bars=150 等更低门槛,指标 NaN gate
    会自动剔除尚未暖够的 bar,不会引入未来函数。

    V3a (2026-09-22, CLAUDE.md §3): 当 panel 缺 adj_* 列 (legacy 测试 panel),
    注入 NaN adj_* 让 backtrader feed 不报错 (NaN 会被 strategy 当 missing 处理,
    baseline parity 保留)。
    """
    feeds: list[tuple[str, AShareData]] = []
    # V3a: 检测 panel 是否含 adj_* 列, 缺则补 NaN 占位
    needs_adj = "adj_close" not in panel.columns
    for code in codes:
        sub = (
            panel[panel["thscode"] == code]
            .sort_values("date")
            .reset_index(drop=True)
        )
        if len(sub) < min_bars:
            continue
        if needs_adj:
            for col in ("adj_open", "adj_high", "adj_low", "adj_close"):
                sub[col] = float("nan")
        # 不设 fromdate/todate: 窗口边界由 strategy 侧显式约束。
        # §1 (audit, 2026-10-15): 在 backtrader 1.9.78.123 + pandas 3.0.5 栈下
        # `feed.fromdate = pd.Timestamp(...)` 会抛 TypeError,故不在 feed 层做
        # 裁剪,改为把窗口下发到策略(Phase3V3Strategy.window_start/window_end,
        # 由 engine.py 传入)并在入场决策处强制。
        # ⚠️ 本注释此前写成「边界由 indicator NaN gate + entry 时点检查保证
        # (LAHEAD-001 实证 pre_window_entry_count == 0)」—— 那句话有两处不实:
        #   1) 策略里从来没有 entry 时点/窗口检查(现补上,见 _in_window);
        #   2) 引用的 LAHEAD-001 用例当时因 harness 分叉而常年 ERROR,等于零覆盖
        #      (harness 已修为委托生产实现,该不变量现被真正验证)。
        feed = AShareData(dataname=sub, plot=False)
        feeds.append((code, feed))
    return feeds

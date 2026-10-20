"""backtrader 数据源。

AShareData: 在 PandasData 基础上加 `amount`（成交额）line、V3a `adj_*` 四条线,
            以及公司行为事件列(div_per_share / bonus_ratio / rights_ratio)。

build_per_stock_feeds: 把 DuckDB 拉出的 panel 切成 per-stock feeds 喂给 cerebro。

§3 双价域(2026-10-17 更正本 docstring):本 feed **不带 raw_* lines**,而且**不需要**:
`v_daily` 本身就是**原始价**,所以 raw 域执行直接用默认的 `close` line;
复权域另开 `adj_open/adj_high/adj_low/adj_close`(LEFT JOIN v_daily_hfq)。
`price_source_for_execution="raw_close"` 的含义正是"用默认(原始)列",strategy 侧
没有任何地方读 `d.raw_close`(实测全模块 grep 零命中)。

更正它不只是为了准确 —— 原先这里写着「添加 raw_open/raw_high/raw_low/raw_close
lines,strategy 在 price_source_for_execution="raw_close" 时切换 SL/TP 到 raw_*
lines」,与 `lines` 元组的实际内容不符,会让人(或 agent)以为 `d.lines.raw_close`
存在(进而写出 AttributeError),或据此对价格域下错结论 —— 而"短反转的 close 到底是
raw 还是 adj"正是审计 §3 反复要钉住的前提。
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
        # §3 (audit P2-10, 2026-10-15): 公司行为事件列
        "div_per_share", "bonus_ratio", "rights_ratio",
    )
    params = (
        ("amount", "amount"),
        ("adj_open", "adj_open"),
        ("adj_high", "adj_high"),
        ("adj_low", "adj_low"),
        ("adj_close", "adj_close"),
        ("div_per_share", "div_per_share"),
        ("bonus_ratio", "bonus_ratio"),
        ("rights_ratio", "rights_ratio"),
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
        for col in ("adj_open", "adj_high", "adj_low", "adj_close",
                    "div_per_share", "bonus_ratio", "rights_ratio"):
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
    # ----- §13.111 (2026-10-19): **O(n_codes × n_rows) → 一次 groupby** -----
    # 旧写法是 `panel[panel["thscode"] == code]` —— **对每只票全表扫一遍**。
    # 实测 (~5,000 只票, 1 个月窗口): **43.5s**, 其中 99.2% 在这条布尔掩码里;
    # 而 `panel["thscode"]` 是 pandas **`string` dtype** ⇒ `==` 走
    # `_cmp_method` → `_isna_string_dtype` 这条最差的路径 (单这一项 21.0s)。
    # ⚠️ 逐 preset 无关: `v35_agg_pctchg_04_09` 与对照 `v50_slope` **同速**
    #    (42.1 / 47.9 / 179.5 s for 1/2/3 个月) ⇒ **55 个 preset 全都付这个代价**
    #    (55 × 2 窗口 × ~180s ≈ 5.5 小时, 这就是普查跑不完的原因)。
    # **零漂移**: `get_group` 给出与掩码**逐行相同**的子表 (随后照旧 sort_values +
    # reset_index); 遍历 `codes` 保证 `feeds` 的**顺序不变**。
    # 缺失的 code 在掩码下得到空表 (随后 `len < min_bars` 跳过), 这里等价处理。
    _by_code = panel.groupby("thscode", sort=False)
    for code in codes:
        try:
            sub = (
                _by_code.get_group(code)
                .sort_values("date")
                .reset_index(drop=True)
            )
        except KeyError:      # 该票不在面板里 —— 旧写法会给空表, 语义相同
            continue
        if len(sub) < min_bars:
            continue
        if needs_adj:
            for col in ("adj_open", "adj_high", "adj_low", "adj_close"):
                sub[col] = float("nan")
        # §3 (audit P2-10): 事件列缺失(旧测试 panel)→ 补 **0.0** 而非 NaN。
        # 0.0 = "该 bar 无公司行为",NaN 会让"是否有事件"的判定失真。
        for col in ("div_per_share", "bonus_ratio", "rights_ratio"):
            if col not in sub.columns:
                sub[col] = 0.0
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

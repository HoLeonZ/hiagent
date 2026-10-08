# hiagent

A 股量化策略回测系统。绝对确定性优先(时间不可逆、资金物理、禁未来函数)。

## 架构概览

4 个策略 + 2 个共享核心层 + 1 个数据层:

```
hiagent/
├── core/                      # 跨策略共享领域层(纯函数,零 I/O)
│   ├── dual_price.py          # 双价系统(adj_close / raw_close 契约)
│   ├── trade_schema.py        # TRADE_COLS 成交记录 schema
│   └── walkforward.py         # WFV 公共工具
│
├── chase_up/                  # 策略 1:追涨(long)
├── uptrend_pullback/          # 策略 2:趋势回调(long)
├── short_reversal/            # 策略 3:做空反转(short)
├── cycle_price_action/        # 策略 4:周期/价格行为(long)
│
├── dna_data/                  # 数据访问层(DuckDB I/O)
│   ├── dual_price_loader.py   # v_daily_dual view 装载器
│   └── dual_price_resolver.py # price_source_for_* → 列名解析
├── dna_stats/                 # 统计层
│   ├── deflated.py            # Deflated Sharpe Ratio
│   └── walkforward_report.py
│
├── sql/migrate_v_daily_dual.sql  # v_daily_dual view 定义
├── tools/                     # DB 维护脚本
├── tests/                     # 136 个测试文件
└── data/exclude_thscodes.txt  # 排除股票清单(样本)
```

策略内部统一三层架构(详见 [`CLAUDE.md`](./CLAUDE.md) §6):
1. **Control Plane** —— `main.py` / `backtest.py` / `backtrader_engine.py`,时间步进 + PIT 数据派发
2. **Strategy / Inference** —— `signals.py` / `indicators_bt.py`,纯函数,无网络/DB 访问
3. **Execution Broker** —— `portfolio.py` / `replay_broker.py`,滑点 + 流动性上限 + 原子现金锁

## 快速开始(全新 macOS)

### 1. 克隆仓库

```bash
git clone git@github.com:HoLeonZ/hiagent.git
cd hiagent
```

### 2. 安装 Python 依赖

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> **Python 版本**:实测 3.14.6 可运行。3.10+ 应均兼容。
> **首次安装约 60-90 秒**。

### 3. 准备数据(关键 —— 不在仓库内)

本仓库**不包含行情数据**。所有策略都依赖本机 DuckDB 中的真实 A 股 K 线。

**默认路径**:`~/Library/Application Support/hithink-finance/data/market.duckdb`

数据库需包含以下视图/表:

| 对象 | 来源 | 说明 |
|---|---|---|
| `raw_kline_daily` | 外部 ETL(Financial-API) | 原始日 K 线(未复权) |
| `v_daily_hfq` | 外部 ETL | 复权后日 K |
| `v_daily` / `v_daily_qfq` | 外部 ETL | 单价视图 |
| `v_daily_dual` | 本仓库 `sql/migrate_v_daily_dual.sql` | 双价 join view,CLAUDE.md §3 必须 |

**首次启用 v_daily_dual**:

```bash
duckdb ~/Library/Application\ Support/hithink-finance/data/market.duckdb < sql/migrate_v_daily_dual.sql
```

**自定义数据库路径**(测试/CI 覆盖):

```bash
export DNA_STRAT_DB=/path/to/your.duckdb
```

### 4. 跑测试

```bash
pytest tests/ -v
```

> 完整测试套 136 文件,**部分 pre-existing 失败**(chase_up 缺 `is_limit_up` import、cycle 缺 §4 limit-up 守卫、2 处 partial-NaN edge case)—— 与本 README 无关,见 git log。

## 重要设计约束

来自 [`CLAUDE.md`](./CLAUDE.md):

- **§1 时间确定性** —— 所有数据访问必须显式 `as_of_time` 参数,禁 `bfill` / `shift(-x)` / 中心化 rolling
- **§2 资金确定性** —— 三池隔离(Free_Cash / Locked_Margin / Settling_Funds),2026-09-21 起 All-In Sizing(尾风险在退出层吸收)
- **§3 数据完整性** —— 双价系统:adj_close 给指标,raw_close 给 SL/TP/M2M
- **§4 微结构** —— 流动性上限 10% bar volume,SL/TP 阈值是策略选择不是执行成本
- **§5 统计严谨性** —— 禁 in-sample grid,必须 WFV,多参数扫描必须报告 DSR/Bonferroni

## 工具脚本

### tools/update_db_direct.py —— DB 增量更新

绕开 `marketdb` Python 包(来自外部私有仓库 `Financial-API`,本机无),用 `requests + duckdb` 直接调 REST API 拉数据并 `INSERT OR IGNORE` 进 `raw_kline_daily`。仅依赖环境变量:

```bash
export FINANCIAL_API_BASE_URL=https://fuyao.aicubes.cn
export FINANCIAL_API_KEY=sk-...
python3 -m tools.update_db_direct --db "$DNA_STRAT_DB" --target 2026-09-30 --days 14
```

> 替代 2026-09 之前基于 `marketdb` 的 `tools/update_db.py`(已删除;该脚本在本机因 `ModuleNotFoundError: No module named 'marketdb'` 无法运行)。

## 已知缺口(本仓库不提供)

| 缺口 | 解决方向 |
|---|---|
| 行情数据本体(DB 13 GB+) | 不进 git;用户自行 ETL 或 `git-lfs` 单独管理 |
| 测试数据 fixture | 当前测试依赖真实 DuckDB;离线 mock 在 TODO |

## 项目元信息

- **远程仓库**:`git@github.com:HoLeonZ/hiagent.git`
- **Python**:3.10+ (实测 3.14.6)
- **关键依赖**:duckdb / pandas / numpy / backtrader / pytest
- **测试**:136 文件,部分 pre-existing 失败(见 git log)
- **审计历史**:R1-R171 累计,见 `docs/` 目录及 commit log

## 详细文档

- [`CLAUDE.md`](./CLAUDE.md) —— 核心哲学与设计约束(必读)
- [`docs/`](./docs/) —— 历次审计报告(claudemd_full_audit_2026_09_22 等)
- 各策略目录下的 `README.md` —— 策略特定说明
# hiagent — A 股下降趋势反弹做空策略

策略仓库。完整 7 模块 + 主入口 + 单测在本目录，运行时所需的 DuckDB / marketdb 由 `~/code/Financial-API/` 提供（不在本仓库打包）。

## 工作区布局

```
~/code/
├── hiagent/                          # 本仓库（策略代码 + 文档）
│   ├── dna_strat/                    # 策略核心包
│   │   ├── __init__.py
│   │   ├── universe.py               # 沪深主板筛选 + 黑名单
│   │   ├── signals.py                # 指标计算 + A∧B∧C 入场信号
│   │   ├── trades.py                 # 持仓循环（全局单 key 锁，满仓单只）
│   │   ├── feed.py                   # 合成 backtrader feed
│   │   ├── broker.py                 # AShareBroker（万 2.5 / 万 1 / 100 股整手）
│   │   └── strategy.py               # TradeReplayStrategy（融券 8.6% 按日扣）
│   ├── backtest_downtrend_short.py   # 主入口（Phase 1 + Phase 2 端到端）
│   ├── tests/
│   │   └── test_downtrend_short.py   # 20 单元测试（用合成数据，无外部依赖）
│   ├── data/
│   │   └── exclude_thscodes.txt      # 黑名单（一行一 thscode，# 注释）
│   ├── docs/                         # 内部 spec/plan — 不推远端
│   ├── .gitignore                    # 屏蔽 docs/superpowers/ + .superpowers/ + .pytest_cache
│   └── CLAUDE.md
│
└── Financial-API/                    # 运行时依赖（不入本仓库）
    ├── python/                       # marketdb 0.1.0（pip install -e 安装点）
    └── data/
        └── market.duckdb             # 本地 DuckDB（10 年 A 股 K 线）
```

## 运行条件

| 依赖 | 来源 | 必需 |
| --- | --- | --- |
| `marketdb` 0.1.0 | `pip install -e ~/code/Financial-API/python` | 跑真实回测时 |
| DuckDB `market.duckdb` | `~/code/Financial-API/data/market.duckdb` | 跑真实回测时 |
| `backtrader` 1.9.78.123 | pip | 跑真实回测 + 部分单测 |
| `matplotlib` 3.10.x | conda base | 出图 |

DB 路径可通过环境变量 `DNA_STRAT_DB` 覆盖（`backtest_downtrend_short.py` 顶部 `DB_PATH`）。

## 测试 / 运行

```bash
# 单测（无外部依赖，20/20）
python3 -m pytest tests/test_downtrend_short.py -v

# 真实端到端回测
python3 backtest_downtrend_short.py
# 默认区间：end = DuckDB 最大日期，start = end - 365 天
# 产物：data/exports/trades_*.parquet、logs/backtest_*.log、figures/downtrend_short_*.png
```

## 凭据（仅运行 `hithink-finance-cli` 数据同步时需要）

API Key `HITHINK_FINANCE_API_KEY` 写在三处：

1. **`~/.zshrc` + `~/.zshenv`** — shell 环境变量
2. **系统 keyring**（通过 `hithink-finance auth login --api-key-stdin --replace` 写入）
3. **`~/Library/Application Support/hithink-finance/credentials.env`**（兼容 fallback）

读取优先级：操作临时输入 > 环境变量 > 用户级凭据文件 > 旧名 `FUYAO_TOKEN` / `API_KEY`。

CLI：`@hithink-tech/hithink-finance-cli` v0.1.8（Node 22，文档 `https://fuyao.aicubes.cn/admin`）。

# hiagent


## 工作区布局

```
~/code/
├── hiagent/               # 本项目（仅承载 CLAUDE.md 与备忘，无代码）
└── Financial-API/         # 实际工作区
    ├── python/            # marketdb + fuyao 源码（pip install -e 安装点）
    ├── data/
    │   ├── market.duckdb  # 本地 DuckDB（10 年 A 股 K 线）
    │   ├── .cache/        # marketdb auto-sync 下载缓存
    │   └── exports/       # 落盘导出（Parquet 等）
    ├── backtest_demo.py   # hithink DuckDB → Backtrader 最小 demo
    ├── backtest_demo_equity.png
    └── (其他 monorepo 原始文件)
```

## 技术栈

### 远端数据
- **`@hithink-tech/hithink-finance-cli` v0.1.8**（npm 全局，Node 22.23.1）
  - 子命令：`version / auth / config / symbol / market / special / financials / index / fund / valuation / capabilities / schema / skills / update / uninstall / doctor / data / db`
  - 入口文档：`https://fuyao.aicubes.cn/admin`
- **Node 默认 22**（`nvm alias default 22`，`~/.zshrc` 末尾加 `nvm use default`）

### 本地数据 / Python SDK
- **Python 3.14.3**（conda base `/Users/zhl/ENTER/bin/python3`）
- **`marketdb` 0.1.0**（`pip install -e ~/code/Financial-API/python`，CLI + Python SDK）
- **Fuyao Python toolkit**（同 monorepo 内）
- 依赖：`duckdb 1.5.5`、`pandas 3.0.5`、`pyarrow 24.0.0`、`numpy 2.4.3`、`rich 13.9.4`、`typer`、`click`

### 回测
- **`backtrader` 1.9.78.123**（pip 装的纯 Python 包，无原生依赖，Python 3.14 兼容）
- **`matplotlib` 3.10.9**（conda base 自带，3.11.1 也有 cp314 wheel 可升级）
- 可选：`quantstats`（风险指标增强）

## 凭据

API Key `HITHINK_FINANCE_API_KEY` 写在三处：

1. **`~/.zshrc` + `~/.zshenv`** — shell 环境变量
2. **系统 keyring**（通过 `hithink-finance auth login --api-key-stdin --replace` 写入）
3. **`~/Library/Application Support/hithink-finance/credentials.env`**（兼容 fallback）

读取优先级（按 CLI 文档）：操作临时输入 > 环境变量 > 用户级凭据文件 > 旧名 `FUYAO_TOKEN` / `API_KEY`。


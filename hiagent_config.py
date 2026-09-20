"""hiagent 全局配置 — 单一可配置项:本地 DuckDB 路径。

优先级:
  1. 环境变量 ``DNA_STRAT_DB``(CLI / 测试覆盖用)
  2. ``DEFAULT_DB_PATH``(本机默认;修改这里即可换库)

使用:
    from hiagent_config import DB_PATH, get_db_path
"""
from __future__ import annotations

import os
from pathlib import Path

# 本机默认库路径(由 ``hithink-finance data sync`` 维护)。
DEFAULT_DB_PATH: Path = (
    Path.home() / "Library/Application Support/hithink-finance/data/market.duckdb"
)


def get_db_path() -> Path:
    """返回当前生效的 DuckDB 路径(每次调用重新读环境变量)。"""
    override = os.environ.get("DNA_STRAT_DB")
    return Path(override) if override else DEFAULT_DB_PATH


# 模块加载时求值;绝大多数场景够用,需运行时切换可调 get_db_path()。
DB_PATH: Path = get_db_path()
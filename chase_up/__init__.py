"""chase_up 追涨策略 — 平台突破 + 动量加速 + 均线金叉 OR 融合,ATR 自适应出场。"""
from __future__ import annotations


class ChaseUpError(Exception):
    pass
# 归档：v33 早期脚本（2026-09-09 起不再维护）

这些脚本已被 `short_reversal/` 包重写并替代：

- `strategy_v33_final.py` / `strategy_v33_mainboard.py` → `python -m short_reversal.main --preset v33_mainboard`
- `scan_today_signals.py` → `python -m short_reversal.scan --preset v33_mainboard --date YYYY-MM-DD`
- `audit_today_signals.py` / `audit_v33_tp6.py` → `python -m short_reversal.audit --preset v33_mainboard --date YYYY-MM-DD`
- `grid_search_v33_*.py` → `python -m short_reversal.grid --preset v33_mainboard --tp 0.02,0.03,0.04,0.05,0.06`
- `render_today_signals_html.py` → `python -m short_reversal.render --preset v33_mainboard --date YYYY-MM-DD`

保留原因：作为 parity 测试的 baseline 参考源。

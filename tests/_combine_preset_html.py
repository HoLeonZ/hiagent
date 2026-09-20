"""Merge per-preset trades/trend HTML into a single self-contained HTML per preset.

Output:
  tests/golden/<preset>_report.html — one HTML per preset, contains:
    - Summary card (final capital, CAGR, win rate, DD, Sharpe)
    - Trades table with inline K-line + signal/entry/exit markers
    - Rolling metrics trend (DD, win rate, exit reason mix)
"""
from __future__ import annotations

import sys
from pathlib import Path

GOLDEN = Path("/Users/holeon/code/hiagent/tests/golden")
PRESETS = [
    "v33_mainboard_tp2_sl05_dneg",
    "v33_mainboard_tp6_sl005_mh5_realistic",
]


def merge(preset: str) -> Path:
    trades_html = (GOLDEN / f"{preset}_trades.html").read_text(encoding="utf-8")
    trend_html = (GOLDEN / f"{preset}_trend.html").read_text(encoding="utf-8")

    # Extract <body>...</body> from each subpage
    def extract_body(html: str) -> str:
        start = html.find("<body>")
        end = html.find("</body>")
        if start < 0 or end < 0:
            raise RuntimeError(f"missing <body> in sub-HTML (preset={preset})")
        return html[start + len("<body>"):end].strip()

    # Extract all <style>…</style> blocks from the head so per-page rules
    # (e.g. `table.kline th { text-align: right }`) survive the merge.
    def extract_styles(html: str) -> str:
        out: list[str] = []
        i = 0
        while True:
            s = html.find("<style>", i)
            if s < 0:
                break
            e = html.find("</style>", s)
            if e < 0:
                break
            out.append(html[s + len("<style>"):e])
            i = e + len("</style>")
        return "\n".join(out)

    sub_styles = extract_styles(trades_html) + "\n" + extract_styles(trend_html)

    trades_body = extract_body(trades_html)
    trend_body = extract_body(trend_html)

    # Build tabbed shell — single HTML file with in-page anchors + sticky nav
    merged = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{preset} — short_reversal report</title>
<style>
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         margin: 0; padding: 0; background: #f8fafc; color: #0f172a; }}
  .sticky-nav {{ position: sticky; top: 0; z-index: 100;
                 background: rgba(255,255,255,0.95);
                 backdrop-filter: blur(8px);
                 border-bottom: 1px solid #e2e8f0;
                 padding: 12px 24px;
                 display: flex; gap: 16px; align-items: center;
                 box-shadow: 0 1px 3px rgba(0,0,0,0.04); }}
  .preset-tag {{ font-weight: 700; color: #1e293b; font-size: 14px;
                 background: #dbeafe; padding: 4px 10px; border-radius: 4px; }}
  .nav-tab {{ color: #475569; text-decoration: none; font-size: 14px;
              padding: 6px 12px; border-radius: 4px; transition: background 0.15s; }}
  .nav-tab:hover {{ background: #f1f5f9; }}
  .section {{ padding: 24px 32px; }}
  h1, h2 {{ color: #0f172a; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 12px;
           background: white; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }}
  th, td {{ padding: 8px 12px; border-bottom: 1px solid #e2e8f0;
            text-align: left; font-size: 13px; }}
  th {{ background: #f1f5f9; font-weight: 600; color: #334155; }}
{sub_styles}
</style>
</head>
<body>
<div class="sticky-nav">
  <span class="preset-tag">{preset}</span>
  <a class="nav-tab" href="#trades">交易明细</a>
  <a class="nav-tab" href="#trend">滚动指标</a>
</div>

<div class="section" id="trades">
{trades_body}
</div>

<div class="section" id="trend">
{trend_body}
</div>

</body>
</html>
"""
    out = GOLDEN / f"{preset}_report.html"
    out.write_text(merged, encoding="utf-8")
    return out


def main() -> None:
    out_files = []
    for preset in PRESETS:
        if not (GOLDEN / f"{preset}_trades.html").exists():
            print(f"SKIP {preset}: trades HTML missing — run render_html_report.py first")
            continue
        out_files.append(merge(preset))
        print(f"WROTE {out_files[-1].name}")
    print(f"\nGenerated {len(out_files)} report HTML(s)")


if __name__ == "__main__":
    main()

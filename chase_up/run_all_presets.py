"""Loop all 22 chase_up presets through backtest main, aggregate metrics."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

OUT_DIR = Path("/tmp/chase_up_all_presets")
OUT_DIR.mkdir(parents=True, exist_ok=True)
SUMMARY_PATH = OUT_DIR / "summary.md"
JSON_PATH = OUT_DIR / "summary.json"

START = "2025-09-19"
END = "2026-09-19"
ENGINE = "simulate"

# Pull preset names from chase_up.presets.PRESETS
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from chase_up.presets import PRESETS

presets = list(PRESETS.keys())
print(f"Running {len(presets)} presets × engine={ENGINE}")

rows: list[dict] = []
t0 = time.time()
for i, name in enumerate(presets, 1):
    out_json = OUT_DIR / f"{name}.json"
    cmd = [
        "python3", "-m", "chase_up.main",
        "--engine", ENGINE,
        "--preset", name,
        "--start", START,
        "--end", END,
        "--out", str(out_json),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        print(f"[{i:>2}/{len(presets)}] {name}  FAILED rc={proc.returncode}")
        print("  stderr tail:", proc.stderr.splitlines()[-3:] if proc.stderr else "")
        rows.append({"preset": name, "error": f"rc={proc.returncode}", "trades": 0})
        continue

    payload = json.loads(out_json.read_text()) if out_json.exists() else {}
    metrics = payload.get("metrics", payload)
    rows.append({"preset": name, **metrics})
    elapsed = time.time() - t0
    avg = elapsed / i
    eta = avg * (len(presets) - i)
    print(
        f"[{i:>2}/{len(presets)}] {name:<55} "
        f"trades={metrics.get('trades',0):>3} "
        f"WR={metrics.get('win_rate',0)*100:>5.1f}% "
        f"CAGR={metrics.get('cagr',0)*100:>+8.2f}% "
        f"Sharpe={metrics.get('sharpe',0):>5.2f} "
        f"DD={metrics.get('max_dd',0)*100:>6.2f}% "
        f"[{elapsed:>5.1f}s, ETA {eta:>4.1f}s]"
    )

total = time.time() - t0
print(f"\nAll {len(presets)} presets finished in {total:.1f}s ({total/len(presets):.1f}s avg)")

# Persist JSON
JSON_PATH.write_text(json.dumps(rows, indent=2, ensure_ascii=False))

# Build markdown summary
def _pct(x: float) -> str:
    return f"{x*100:+.2f}%" if isinstance(x, (int, float)) else "n/a"


md = [
    "# chase_up — All Presets Backtest Summary",
    "",
    f"Engine: `{ENGINE}`  Window: {START} → {END}  Initial capital: 1,000,000",
    "",
    f"Total presets: **{len(rows)}**  Total wall time: {total:.1f}s",
    "",
    "| # | preset | trades | WR | CAGR | Sharpe | maxDD | final_equity | avg_hold | TP/SL/time/eod |",
    "|---|--------|-------:|----:|-----:|-------:|------:|-------------:|---------:|----------------|",
]
for i, r in enumerate(rows, 1):
    if "error" in r:
        md.append(f"| {i} | `{r['preset']}` | ERR | — | — | — | — | — | — | — |")
        continue
    trades = r.get("trades", 0)
    wr = _pct(r.get("win_rate", 0))
    cagr = _pct(r.get("cagr", 0))
    sharpe = f"{r.get('sharpe', 0):.2f}"
    dd = _pct(r.get("max_dd", 0))
    eq = f"{r.get('final_equity', 0):,.0f}"
    hold = f"{r.get('avg_hold_days', 0):.1f}"
    tp = r.get("tp_count", 0)
    sl = r.get("sl_count", 0)
    tm = r.get("time_count", 0)
    eod = r.get("eod_count", 0)
    md.append(f"| {i} | `{r['preset']}` | {trades} | {wr} | {cagr} | {sharpe} | {dd} | {eq} | {hold} | {tp}/{sl}/{tm}/{eod} |")

SUMMARY_PATH.write_text("\n".join(md) + "\n")
print(f"\nSummary written:\n  {SUMMARY_PATH}\n  {JSON_PATH}")
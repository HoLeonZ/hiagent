"""Loop every preset across 4 strategies through its CLI on a 2-year window.

聚合位置:``/tmp/hiagent_all_presets_2yr/``(CLAUDE.md §7 — 不进 repo, results/ 已
gitignored;本脚本为临时协调脚本(**它确实在 git 里** —— 原句说反了,附一百一十一 更正))。

Window:
  start = 2024-10-10(2 年前同日 ±1)
  end   = 2026-10-09(DB raw_kline_daily MAX(date))

Strategy CLI 合约:
  chase_up            : --engine backtrader --preset <name> --start <s> --end <e> --out <o>
  uptrend_pullback    : --engine backtrader --preset <name> --start <s> --end <e> --out <o>
  short_reversal      : --preset <name> --start <s> --end <e> --out <o>
  cycle_price_action  : --preset v1 --start <s> --end <e> run --out-dir <d>

所有 CLI 失败视为 fail-fast(per CLAUDE.md §0):非零 rc + error 行落入 summary,
但仍继续跑完所有 preset(非阻塞),汇总在末尾统一呈现。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

# §0/§6 (附一百一十一): 此前硬编码的是**另一个用户**的家目录 ⇒ 在任何别的
# checkout 上都指向不存在的地方。
REPO = Path(__file__).resolve().parents[1]
OUT_DIR = Path("/tmp/hiagent_all_presets_2yr")
OUT_DIR.mkdir(parents=True, exist_ok=True)
SUMMARY_MD = OUT_DIR / "summary.md"
SUMMARY_JSON = OUT_DIR / "summary.json"

START = "2024-10-10"
END = "2026-10-09"
TIMEOUT_S = 600  # 2-yr backtest single preset worst-case ceiling

sys.path.insert(0, str(REPO))

# --- import preset registries lazily ---
from chase_up.presets import PRESETS as CHASE_PRESETS          # noqa: E402
from uptrend_pullback.presets import PRESETS as UPTREND_PRESETS  # noqa: E402
from short_reversal.presets import PRESETS as SHORT_PRESETS      # noqa: E402
import importlib                                                          # noqa: E402

cycle_mod = importlib.import_module("cycle_price_action.presets")
# cycle_price_action.presets exposes PRESET_V1 only — run as one preset.
cycle_preset_names = [n for n in dir(cycle_mod) if n.startswith("PRESET_") and not n.startswith("_")]


# --- build the work list ---
WORK: list[tuple[str, str, list[str]]] = []

for name in CHASE_PRESETS:
    out_json = OUT_DIR / f"chase_up_{name}.json"
    cmd = [
        sys.executable, "-m", "chase_up.main",
        "--engine", "backtrader",
        "--preset", name,
        "--start", START, "--end", END,
        "--out", str(out_json),
    ]
    WORK.append(("chase_up", name, cmd))

for name in UPTREND_PRESETS:
    out_json = OUT_DIR / f"uptrend_pullback_{name}.json"
    cmd = [
        sys.executable, "-m", "uptrend_pullback.main",
        "--engine", "backtrader",
        "--preset", name,
        "--start", START, "--end", END,
        "--out", str(out_json),
    ]
    WORK.append(("uptrend_pullback", name, cmd))

for name in SHORT_PRESETS:
    out_json = OUT_DIR / f"short_reversal_{name}.json"
    cmd = [
        sys.executable, "-m", "short_reversal.main",
        "--preset", name,
        "--start", START, "--end", END,
        "--out", str(out_json),
    ]
    WORK.append(("short_reversal", name, cmd))

for name in cycle_preset_names:
    cmd = [
        sys.executable, "-m", "cycle_price_action.main",
        "--preset", "v1",  # cycle CLI only accepts "v1"
        "--start", START, "--end", END,
        "run", "--out-dir", str(OUT_DIR / "cycle_price_action_v1"),
    ]
    WORK.append(("cycle_price_action", "v1", cmd))


# --- dispatch ---
rows: list[dict] = []
t0 = time.time()
total = len(WORK)


def _pct(x: float | None) -> str:
    if not isinstance(x, (int, float)):
        return "n/a"
    return f"{x * 100:+.2f}%"


def _fmt_metric(metrics: dict, key: str, default=0) -> float | int:
    v = metrics.get(key, default)
    return v if v is not None else default


for i, (strategy, preset, cmd) in enumerate(WORK, 1):
    label = f"[{strategy}] {preset}"
    print(f"\n→ {i}/{total} {label}", flush=True)
    try:
        proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        rows.append({"strategy": strategy, "preset": preset, "error": f"timeout>{TIMEOUT_S}s"})
        print(f"   ❌ timeout after {TIMEOUT_S}s")
        continue

    if proc.returncode != 0:
        rows.append({
            "strategy": strategy, "preset": preset,
            "error": f"rc={proc.returncode}",
            "stderr_tail": proc.stderr.splitlines()[-3:] if proc.stderr else [],
        })
        print(f"   ❌ rc={proc.returncode}")
        if proc.stderr:
            print("   stderr tail:", proc.stderr.splitlines()[-3:])
        continue

    # locate the metrics json we just wrote
    if strategy == "cycle_price_action":
        metrics_path = OUT_DIR / "cycle_price_action_v1" / f"{preset}_metrics.json"
        if not metrics_path.exists():
            metrics_path = OUT_DIR / "cycle_price_action_v1" / "v1_metrics.json"
    else:
        metrics_path = OUT_DIR / f"{strategy}_{preset}.json"

    if not metrics_path.exists():
        rows.append({"strategy": strategy, "preset": preset, "error": f"metrics file missing: {metrics_path}"})
        print(f"   ⚠️  metrics file missing at {metrics_path}")
        continue

    try:
        payload = json.loads(metrics_path.read_text())
    except json.JSONDecodeError as e:
        rows.append({"strategy": strategy, "preset": preset, "error": f"json parse: {e}"})
        continue

    metrics = payload.get("metrics", payload)
    row = {"strategy": strategy, "preset": preset, **metrics}
    rows.append(row)
    elapsed = time.time() - t0
    avg = elapsed / i
    eta = avg * (total - i)
    print(
        f"   trades={_fmt_metric(metrics,'trades', 0):>4} "
        f"WR={_pct(metrics.get('win_rate')):>7} "
        f"CAGR={_pct(metrics.get('cagr')):>8} "
        f"Sharpe={metrics.get('sharpe', 0):>6.2f} "
        f"DD={_pct(metrics.get('max_dd')):>7} "
        f"[{elapsed:>5.1f}s, ETA {eta:>4.1f}s]"
    )

total_elapsed = time.time() - t0
print(f"\n=== All {total} presets finished in {total_elapsed:.1f}s ({total_elapsed/total:.1f}s avg) ===\n")

# --- aggregate stats per strategy ---
SUMMARY_JSON.write_text(json.dumps({
    "start": START, "end": END, "presets": rows, "elapsed_s": total_elapsed,
}, indent=2, ensure_ascii=False, default=str))

# --- rank + format markdown ---
def _safe_get(m: dict, k: str, default=0):
    v = m.get(k, default)
    return v if isinstance(v, (int, float)) else default


sorted_rows = sorted(
    [r for r in rows if "error" not in r],
    key=lambda r: (_safe_get(r, "sharpe"), _safe_get(r, "cagr")),
    reverse=True,
)
errors = [r for r in rows if "error" in r]

md = [
    "# hiagent — All Presets 2-Year Backtest",
    "",
    f"Window: **{START} → {END}**  (≈2 calendar years, anchored to DB `MAX(date)=2026-10-09`)",
    f"Initial capital: 1,000,000  Engine: `backtrader` (chase_up / uptrend_pullback), v3 (short_reversal), custom (cycle_price_action)",
    "",
    f"Total presets: **{total}**  Successful: **{len(sorted_rows)}**  Failed: **{len(errors)}**",
    f"Wall time: {total_elapsed:.1f}s ({total_elapsed/total:.1f}s avg per preset)",
    "",
    "## Top 10 by Sharpe",
    "",
    "| # | strategy | preset | trades | WR | CAGR | Sharpe | maxDD | final_eq |",
    "|---|----------|--------|-------:|----:|-----:|-------:|------:|---------:|",
]
for i, r in enumerate(sorted_rows[:10], 1):
    md.append(
        f"| {i} | {r['strategy']} | `{r['preset']}` | "
        f"{int(_safe_get(r,'trades',0))} | {_pct(r.get('win_rate'))} | "
        f"{_pct(r.get('cagr'))} | {_safe_get(r,'sharpe',0):.2f} | "
        f"{_pct(r.get('max_dd'))} | "
        f"{_safe_get(r,'final_equity',0):,.0f} |"
    )

md.append("")
md.append(f"## All results ({len(sorted_rows)} presets, sorted by Sharpe desc)")
md.append("")
md.append("| strategy | preset | trades | WR | CAGR | Sharpe | DD | final_eq |")
md.append("|----------|--------|-------:|----:|-----:|-------:|----:|---------:|")
for r in sorted_rows:
    md.append(
        f"| {r['strategy']} | `{r['preset']}` | "
        f"{int(_safe_get(r,'trades',0))} | {_pct(r.get('win_rate'))} | "
        f"{_pct(r.get('cagr'))} | {_safe_get(r,'sharpe',0):.2f} | "
        f"{_pct(r.get('max_dd'))} | "
        f"{_safe_get(r,'final_equity',0):,.0f} |"
    )

if errors:
    md.append("")
    md.append(f"## Failures ({len(errors)})")
    md.append("")
    for r in errors:
        md.append(f"- {r['strategy']}/{r['preset']}: {r.get('error','?')}")

SUMMARY_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
print(f"\nSummary written to:\n  {SUMMARY_MD}\n  {SUMMARY_JSON}")

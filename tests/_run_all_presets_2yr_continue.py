"""Continue _run_all_presets_2yr.py after a kill: skip finished, finish the rest, aggregate all 36.

Field-schema fix from the kill analysis:
  - chase_up, uptrend_pullback, cycle_price_action: metric key is `trades`
  - short_reversal: metric key is `trades_count`, `final_capital` (not `final_equity`)

Aggregation normalizes both into `trades` / `final_equity` for the unified summary.

Output: /tmp/hiagent_all_presets_2yr/ — same dir as the killed runner so existing JSONs are reused.
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
TIMEOUT_S = 1200  # 20 min ceiling per preset (short_reversal worst case ~7 min)

sys.path.insert(0, str(REPO))
from chase_up.presets import PRESETS as CHASE_PRESETS            # noqa: E402
from uptrend_pullback.presets import PRESETS as UPTREND_PRESETS  # noqa: E402
from short_reversal.presets import PRESETS as SHORT_PRESETS      # noqa: E402

# --- normalize metric keys across engines ---
KEY_ALIASES = {
    "trades": "trades",
    "trades_count": "trades",
    "final_equity": "final_equity",
    "final_capital": "final_equity",
}


def _normalize(m: dict) -> dict:
    out = {}
    for k, v in m.items():
        if k in KEY_ALIASES:
            out[KEY_ALIASES[k]] = v
        else:
            out[k] = v
    return out


def _already_done(strategy: str, preset: str) -> bool:
    p = OUT_DIR / f"{strategy}_{preset}.json"
    if strategy == "cycle_price_action":
        p2 = OUT_DIR / "cycle_price_action_v1" / f"{preset}_metrics.json"
        return p.exists() or p2.exists()
    return p.exists()


# --- build work list, skipping finished ---
PENDING: list[tuple[str, str, list[str]]] = []

for name in CHASE_PRESETS:
    if _already_done("chase_up", name):
        continue
    out_json = OUT_DIR / f"chase_up_{name}.json"
    cmd = [sys.executable, "-m", "chase_up.main", "--engine", "backtrader",
           "--preset", name, "--start", START, "--end", END, "--out", str(out_json)]
    PENDING.append(("chase_up", name, cmd))

for name in UPTREND_PRESETS:
    if _already_done("uptrend_pullback", name):
        continue
    out_json = OUT_DIR / f"uptrend_pullback_{name}.json"
    cmd = [sys.executable, "-m", "uptrend_pullback.main", "--engine", "backtrader",
           "--preset", name, "--start", START, "--end", END, "--out", str(out_json)]
    PENDING.append(("uptrend_pullback", name, cmd))

for name in SHORT_PRESETS:
    if _already_done("short_reversal", name):
        continue
    out_json = OUT_DIR / f"short_reversal_{name}.json"
    cmd = [sys.executable, "-m", "short_reversal.main",
           "--preset", name, "--start", START, "--end", END, "--out", str(out_json)]
    PENDING.append(("short_reversal", name, cmd))

cycle_dir = OUT_DIR / "cycle_price_action_v1"
for name in ["v1"]:
    if not _already_done("cycle_price_action", name):
        cmd = [sys.executable, "-m", "cycle_price_action.main",
               "--preset", "v1", "--start", START, "--end", END,
               "run", "--out-dir", str(cycle_dir)]
        PENDING.append(("cycle_price_action", "v1", cmd))


# --- also collect already-finished rows for aggregation ---
DONE: list[tuple[str, str, Path]] = []
for strategy, presets in [
    ("chase_up", CHASE_PRESETS),
    ("uptrend_pullback", UPTREND_PRESETS),
    ("short_reversal", SHORT_PRESETS),
    ("cycle_price_action", ["v1"]),
]:
    for name in presets:
        if _already_done(strategy, name) and (strategy, name) not in [(s, p) for s, p, _ in PENDING]:
            p = OUT_DIR / f"{strategy}_{name}.json"
            if strategy == "cycle_price_action":
                p2 = cycle_dir / f"{name}_metrics.json"
                if p2.exists():
                    p = p2
            if p.exists():
                DONE.append((strategy, name, p))


def _row(strategy, preset, payload):
    metrics = payload.get("metrics", payload) if isinstance(payload, dict) else {}
    return {"strategy": strategy, "preset": preset, **_normalize(metrics)}


def _pct(x):
    if not isinstance(x, (int, float)):
        return "n/a"
    return f"{x*100:+.2f}%"


def _safe_get(m, k, default=0):
    v = m.get(k, default)
    return v if isinstance(v, (int, float)) else default


print(f"Already finished: {len(DONE)}, pending: {len(PENDING)}", flush=True)

# --- run pending ---
t0 = time.time()
new_rows: list[dict] = []
errors: list[dict] = []
for i, (strategy, preset, cmd) in enumerate(PENDING, 1):
    label = f"[{strategy}] {preset}"
    print(f"\n→ {i}/{len(PENDING)} {label}", flush=True)
    try:
        proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        errors.append({"strategy": strategy, "preset": preset, "error": f"timeout>{TIMEOUT_S}s"})
        print(f"   ❌ timeout after {TIMEOUT_S}s")
        continue

    if proc.returncode != 0:
        errors.append({"strategy": strategy, "preset": preset, "error": f"rc={proc.returncode}",
                       "stderr_tail": proc.stderr.splitlines()[-3:] if proc.stderr else []})
        print(f"   ❌ rc={proc.returncode}")
        if proc.stderr:
            print("   stderr tail:", proc.stderr.splitlines()[-3:])
        continue

    if strategy == "cycle_price_action":
        mp = cycle_dir / "v1_metrics.json"
        if not mp.exists():
            mp = OUT_DIR / "cycle_price_action_v1" / f"{preset}_metrics.json"
    else:
        mp = OUT_DIR / f"{strategy}_{preset}.json"

    try:
        payload = json.loads(mp.read_text())
    except Exception as e:
        errors.append({"strategy": strategy, "preset": preset, "error": f"read: {e}"})
        continue

    row = _row(strategy, preset, payload)
    new_rows.append(row)
    print(
        f"   trades={int(_safe_get(row,'trades',0)):>4} "
        f"WR={_pct(row.get('win_rate')):>7} "
        f"CAGR={_pct(row.get('cagr')):>8} "
        f"Sharpe={row.get('sharpe',0):>6.2f} "
        f"DD={_pct(row.get('max_dd')):>7}"
    )

elapsed = time.time() - t0
print(f"\nContinuation: {len(new_rows)} success, {len(errors)} fail in {elapsed:.1f}s", flush=True)


# --- aggregate everything ---
all_rows: list[dict] = []
for strategy, preset, path in DONE:
    try:
        payload = json.loads(path.read_text())
        all_rows.append(_row(strategy, preset, payload))
    except Exception as e:
        errors.append({"strategy": strategy, "preset": preset, "error": f"final read: {e}"})

all_rows.extend(new_rows)

# sort by strategy then by preset name
all_rows.sort(key=lambda r: (r["strategy"], r["preset"]))

SUMMARY_JSON.write_text(json.dumps({
    "start": START, "end": END,
    "total_presets": len(all_rows),
    "presets": all_rows,
    "errors": errors,
    "continuation_elapsed_s": elapsed,
    "previously_finished": len(DONE),
    "newly_finished": len(new_rows),
}, indent=2, ensure_ascii=False, default=str))

# --- markdown summary ---
sorted_by_sharpe = sorted(all_rows, key=lambda r: (_safe_get(r, "sharpe"), _safe_get(r, "cagr")), reverse=True)
md = [
    "# hiagent — All Presets 2-Year Backtest",
    "",
    f"Window: **{START} → {END}**  (~2 calendar years, anchored to DB MAX(date)=2026-10-09)",
    f"Initial capital: 1,000,000  Engines: backtrader (chase_up/uptrend_pullback), v3 (short_reversal), custom (cycle_price_action)",
    "",
    f"Presets written: **{len(all_rows)}**  Errors: **{len(errors)}**",
    "",
    "## Top 15 by Sharpe",
    "",
    "| # | strategy | preset | trades | WR | CAGR | Sharpe | maxDD | final_eq | TP/SL/time |",
    "|---|----------|--------|-------:|----:|-----:|-------:|------:|---------:|------------|",
]
for i, r in enumerate(sorted_by_sharpe[:15], 1):
    tp = int(_safe_get(r, "tp_count", 0))
    sl = int(_safe_get(r, "sl_count", 0))
    tm = int(_safe_get(r, "time_count", 0))
    md.append(
        f"| {i} | {r['strategy']} | `{r['preset']}` | "
        f"{int(_safe_get(r,'trades',0))} | {_pct(r.get('win_rate'))} | "
        f"{_pct(r.get('cagr'))} | {_safe_get(r,'sharpe',0):.2f} | "
        f"{_pct(r.get('max_dd'))} | "
        f"{_safe_get(r,'final_equity',0):,.0f} | {tp}/{sl}/{tm} |"
    )

md.append("")
md.append(f"## All ({len(all_rows)}) presets, by strategy then preset name")
md.append("")
md.append("| strategy | preset | trades | WR | CAGR | Sharpe | DD | final_eq |")
md.append("|----------|--------|-------:|----:|-----:|-------:|----:|---------:|")
for r in all_rows:
    md.append(
        f"| {r['strategy']} | `{r['preset']}` | "
        f"{int(_safe_get(r,'trades',0))} | {_pct(r.get('win_rate'))} | "
        f"{_pct(r.get('cagr'))} | {_safe_get(r,'sharpe',0):.2f} | "
        f"{_pct(r.get('max_dd'))} | "
        f"{_safe_get(r,'final_equity',0):,.0f} |"
    )

if errors:
    md.append("")
    md.append(f"## Errors ({len(errors)})")
    md.append("")
    for r in errors:
        md.append(f"- {r['strategy']}/{r['preset']}: {r.get('error','?')}")

SUMMARY_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
print(f"\nSummary written:\n  {SUMMARY_MD}\n  {SUMMARY_JSON}")

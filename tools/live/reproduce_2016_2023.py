"""2017-2023 cross-window reproduction gate (spec §5.6; CLAUDE.md §5).

Re-runs the SAME candidates as `compare_ensembles` on a SECOND window and
records a `verdict`, because `presets.py:1645-1658` warns that the 2024-2026
baseline window is prone to overfitting: a candidate that is only good on
2024-2026 and NOT significant on 2017-2023 must not be adopted.

This window is a CROSS-WINDOW CONSISTENCY check, NOT an out-of-sample holdout.
`presets.py:712-713` records the v44 ablation on `2017-H2 / 2022-H2 / 2019-H2 /
2021-H1 / 2018-H2` — all inside `[2017-06-01, 2023-12-29]` — and `:531` records
a "2016-2023 mean delta Calmar +0.75 (7 windows)". So these legs' selection
already used this window, and CLAUDE.md §5's "a holdout window that participated
in no iteration" is NOT satisfiable with the available data (the floor is
`2016-10-10`). Do NOT describe this gate as out-of-sample / independent / 样本外.

Window start is `2017-06-01` and MUST NOT be earlier. `raw_kline_daily.min(date)`
is 2016-10-10; any earlier as-of makes `load_universe_asof` return an EMPTY
universe. `run_backtest_v3` NOW RAISES a named `ValueError` on an empty universe
(§0 fail-fast), so an earlier start is a hard error rather than a silent no-op
that looks like "the candidates don't work early". 2017-06-01 additionally gives
the buffered panel `[start-180d, end+60d]` a warm-up landing after 2016-12-03
(enough data for MA60) and a non-empty universe.

Writes its OWN `repro.json` (isomorphic to `compare.json` + `verdict`). It MUST
NOT write `compare.json`: the two scripts are launched concurrently against the
same `--out` dir, so writing the same filename would silently clobber one.

Run:
    python3 -u -m tools.live.reproduce_2016_2023 --out /tmp/hiagent_live_runs
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hiagent_config import get_db_path

from tools.live.compare_ensembles import (
    ALL_PRESETS,
    CANDIDATE_PRESETS,
    MIN_BARS,
    OUTPUT_NAME as _COMPARE_OUTPUT_NAME,  # for the module-level race assertion
    REFERENCE_PRESET,
    run_comparison,
    write_json,
)

# Each module owns its output filename; the contract test pins that the two
# differ so the concurrent runs cannot race on one file.
OUTPUT_NAME: str = "repro.json"

# Guard against a future edit accidentally aliasing the two filenames.
assert OUTPUT_NAME != _COMPARE_OUTPUT_NAME, (
    f"reproduce_2016_2023 must not write {_COMPARE_OUTPUT_NAME!r} — it runs "
    f"concurrently with compare_ensembles against the same --out dir"
)

DEFAULT_START: str = "2017-06-01"
DEFAULT_END: str = "2023-12-29"

# DSR is a probability that the true Sharpe exceeds the expected maximum under
# the null at honest_n_trials; >= 0.95 is the §5 significance bar here.
DSR_SIGNIFICANCE: float = 0.95


def decide(payload: dict) -> str:
    """Return "adopt" / "reject" for the reproduction gate.

    Rule (spec §5.6, hardening presets.py:1645-1658): a candidate that is only
    strong on 2024-2026 and NOT significant on 2017-2023 must not be adopted.
    The gate adopts iff at least one decision candidate is significant on this
    cross-window check (NOT an out-of-sample holdout — see the module docstring).
    The reference candidate never decides — it is water-mark.
    """
    qualified = []
    for cand in payload["candidates"]:
        if cand["is_reference"]:
            continue
        dsr = cand.get("dsr")
        if dsr is not None and dsr >= DSR_SIGNIFICANCE:
            qualified.append(cand["preset"])
    verdict = "adopt" if qualified else "reject"
    print(
        f"repro verdict = {verdict} "
        f"(decision candidates significant at dsr>={DSR_SIGNIFICANCE}: "
        f"{qualified or 'none'})",
        flush=True,
    )
    for cand in payload["candidates"]:
        print(
            f"  {cand['preset']:<20} dsr={cand.get('dsr')} "
            f"bonferroni_p={cand.get('bonferroni_p')} "
            f"is_reference={cand['is_reference']}",
            flush=True,
        )
    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--min-bars", type=int, default=MIN_BARS)
    args = parser.parse_args(argv)

    db_path = get_db_path()
    print(f"reproduce_2016_2023: db={db_path} "
          f"window=[{args.start}, {args.end}] min_bars={args.min_bars}", flush=True)
    print(f"candidates: {ALL_PRESETS} (reference={REFERENCE_PRESET}, "
          f"decision={CANDIDATE_PRESETS})", flush=True)

    payload = run_comparison(args.start, args.end, db_path, args.min_bars)
    payload["window"] = [args.start, args.end]
    payload["verdict"] = decide(payload)

    path = write_json(payload, args.out, OUTPUT_NAME)
    print(f"wrote {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

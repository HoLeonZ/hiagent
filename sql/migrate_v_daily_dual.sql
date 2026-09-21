-- V3a (2026-09-22, CLAUDE.md §3): Dual-Price System.
-- Create v_daily_dual view joining forward-adjusted (v_daily_hfq) with
-- raw (raw_kline_daily) prices so strategies can:
--   * Compute indicators (MACD / Wyckoff / Volatility) on adj_close.
--   * Evaluate SL/TP triggers and portfolio mark-to-market on raw_close.
--
-- Columns:
--   thscode, date, volume, amount  — shared (same in both feeds)
--   adj_open/adj_high/adj_low/adj_close  — v_daily_hfq (forward-adjusted)
--   raw_open/raw_high/raw_low/raw_close  — raw_kline_daily (real historical)
--   adj_prev_close / raw_prev_close      — for limit-up detection
--
-- Use INNER JOIN on (thscode, date) to ensure both feeds present.
-- PIT: both feeds are timestamped at the day level (no look-ahead bias).
--
-- Idempotent: CREATE OR REPLACE VIEW.

CREATE OR REPLACE VIEW v_daily_dual AS
SELECT
    h.thscode                                          AS thscode,
    h.date                                             AS date,
    h.open                                             AS adj_open,
    h.high                                             AS adj_high,
    h.low                                              AS adj_low,
    h.close                                            AS adj_close,
    r.open                                             AS raw_open,
    r.high                                             AS raw_high,
    r.low                                              AS raw_low,
    r.close                                            AS raw_close,
    -- raw_prev_close computed via window function (raw_kline_daily.prev_close
    -- column is NULL in upstream schema). Caller may also compute prev_close
    -- client-side via DataFrame.groupby('thscode')['raw_close'].shift(1).
    LAG(r.close, 1) OVER (
        PARTITION BY r.thscode ORDER BY r.date
    )                                                  AS raw_prev_close,
    h.volume                                           AS volume,
    h.amount                                           AS amount
FROM v_daily_hfq h
INNER JOIN raw_kline_daily r
    ON h.thscode = r.thscode AND h.date = r.date;

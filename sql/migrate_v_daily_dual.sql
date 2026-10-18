-- V3a (2026-09-22, CLAUDE.md §3): Dual-Price System.
-- Create v_daily_dual view joining **backward-adjusted / 后复权** (v_daily_hfq) with
--
-- ⚠️ 2026-10-18 更正(附七十六):此处原写 "forward-adjusted (v_daily_hfq)" ——
-- `hfq` 是**后复权**(backward-adjusted),`qfq` 才是前复权。实测:v_daily_dual.adj_close
-- 与 v_daily_hfq.close **100.00%** 一致(10,364,755 行全中),与 v_daily_qfq.close 只有 5.06%。
-- 这个错标传播到了 dna_data/dual_price_loader.py 的 docstring 与
-- tools/*/audit_phantom.py 的 qfq 校准(附五十八 §4 已登记)。
-- 选后复权是对的:**前复权的历史价位会随之后每次分红而变**(同一份代码在不同日期
-- 跑出不同数字),而后复权不会 —— 与 §0 的可复现性要求一致。
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

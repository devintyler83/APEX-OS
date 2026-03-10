-- ============================================================
-- DraftOS Migration 0035 — Divergence Rank-Relative Columns
-- File: draftos/db/migrations/0035_divergence_rank_delta.sql
-- Apply via: python migrate.py
-- Additive only — no drops, no modifications to existing columns
-- ============================================================

PRAGMA foreign_keys = ON;

-- Add rank-relative divergence delta (new primary signal)
-- Positive = APEX ranks prospect higher than consensus
-- Negative = consensus ranks prospect higher than APEX
ALTER TABLE divergence_flags ADD COLUMN divergence_rank_delta INTEGER;

-- Preserve raw score delta as diagnostic field
-- apex_composite - consensus_implied_score (old method, retained for diagnostics)
ALTER TABLE divergence_flags ADD COLUMN divergence_raw_delta REAL;

-- Position tier for filtering actionable vs. structural divergence
-- 'premium' = QB, CB, EDGE, OT, S (actionable divergence)
-- 'non_premium' = ILB, OLB, OG, C, TE, RB, IDL, WR (PVC-structural discount expected)
ALTER TABLE divergence_flags ADD COLUMN position_tier TEXT;

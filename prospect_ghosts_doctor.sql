-- prospect_ghosts_doctor.sql
-- Read-only checks for PID ghosts / duplicates
-- Runs against DraftOS v2.3 schema, season_id = 1 only.
-- No writes. Safe to run anytime.

.mode column
.headers on

-- 1) One active PID per display_name + season guard
-- This is the core invariant: for the 2026 season, at most one active PID
-- per (display_name, school_canonical) should be feeding the board.
.print ''
.print '=== CHECK 1: Active PID duplicates per (display_name, school_canonical) ==='
.print ''

WITH active_2026 AS (
  SELECT
      prospect_id,
      display_name,
      school_canonical,
      position_group,
      is_active
  FROM prospects
  WHERE season_id = 1
    AND is_active = 1
),
dupe_names AS (
  SELECT
      display_name,
      school_canonical,
      COUNT(*) AS pid_count
  FROM active_2026
  GROUP BY display_name, school_canonical
  HAVING COUNT(*) > 1
)
SELECT
    a.display_name,
    a.school_canonical,
    a.position_group,
    a.prospect_id,
    a.is_active
FROM active_2026 a
JOIN dupe_names d
  ON d.display_name      = a.display_name
 AND d.school_canonical  = a.school_canonical
ORDER BY
    a.display_name,
    a.school_canonical,
    a.prospect_id;

-- 2) Ghosts feeding snapshots: more than one PID per name in snapshot rows
-- This detects “board ghosts” directly on the snapshot layer, regardless
-- of whether the underlying prospects are active/inactive.
.print ''
.print '=== CHECK 2: Multi-PID board ghosts inside snapshots ==='
.print ''

WITH snap_rows AS (
  SELECT
      r.snapshot_id,
      r.prospect_id,
      r.rank_overall,
      p.display_name,
      p.school_canonical,
      p.position_group,
      p.is_active
  FROM prospect_board_snapshot_rows r
  JOIN prospects p
    ON p.prospect_id = r.prospect_id
  WHERE p.season_id = 1
),
name_pid_counts AS (
  SELECT
      snapshot_id,
      display_name,
      school_canonical,
      COUNT(DISTINCT prospect_id) AS pid_count
  FROM snap_rows
  GROUP BY snapshot_id, display_name, school_canonical
  HAVING COUNT(DISTINCT prospect_id) > 1
)
SELECT
    s.snapshot_id,
    s.display_name,
    s.school_canonical,
    s.position_group,
    s.prospect_id,
    s.rank_overall,
    s.is_active
FROM snap_rows s
JOIN name_pid_counts n
  ON n.snapshot_id       = s.snapshot_id
 AND n.display_name      = s.display_name
 AND n.school_canonical  = s.school_canonical
ORDER BY
    s.snapshot_id,
    s.display_name,
    s.school_canonical,
    s.prospect_id;

-- 3) Dedup marker heuristic: __dedup_* school_canonical rows
-- Flags any dedup marker rows that are still active or still present
-- in snapshot rows.
.print ''
.print '=== CHECK 3: __dedup_* rows still active or on board ==='
.print ''

-- 3a) Active __dedup_* prospects (should generally be is_active = 0)
SELECT
    prospect_id,
    display_name,
    school_canonical,
    position_group,
    is_active
FROM prospects
WHERE season_id = 1
  AND school_canonical LIKE '__dedup_%'
ORDER BY
    is_active DESC,
    prospect_id;

.print ''
.print '--- 3b) __dedup_* rows present in snapshot rows ---'
.print ''

SELECT
    r.snapshot_id,
    r.prospect_id,
    p.display_name,
    p.school_canonical,
    p.position_group,
    r.rank_overall,
    p.is_active
FROM prospect_board_snapshot_rows r
JOIN prospects p
  ON p.prospect_id = r.prospect_id
WHERE p.season_id = 1
  AND p.school_canonical LIKE '__dedup_%'
ORDER BY
    r.snapshot_id,
    r.rank_overall;

-- 4) Safety check: inactive PIDs leaking into snapshots
-- Invariant: snapshots should only contain is_active = 1 prospects.
.print ''
.print '=== CHECK 4: Inactive prospects present in snapshot rows ==='
.print ''

SELECT
    r.snapshot_id,
    r.prospect_id,
    p.display_name,
    p.school_canonical,
    p.position_group,
    r.rank_overall,
    p.is_active
FROM prospect_board_snapshot_rows r
JOIN prospects p
  ON p.prospect_id = r.prospect_id
WHERE p.season_id = 1
  AND p.is_active = 0
ORDER BY
    r.snapshot_id,
    r.rank_overall;
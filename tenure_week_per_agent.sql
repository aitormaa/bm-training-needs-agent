-- ============================================================
-- TENURE WEEK PER AGENT
-- Derived from raw BigQuery data — no manual spreadsheet dependency
-- W1 = first week of live contacts (go-live date after nesting)
-- W1–W8 = New Hire | W9+ = Tenured
-- ============================================================

WITH first_live_message AS (
  SELECT
    m.INTERCOM_MESSAGE_ASSIGNEE_ID                          AS agent_id,
    m.INTERCOM_MESSAGE_ASSIGNEE_NAME                        AS agent_name,
    MIN(DATE(m.DATETIME_CREATION_INTERCOM_MESSAGE))         AS go_live_date
  FROM `datamart-prod-20220914.care.fact_intercom_messages` m
  JOIN `datamart-prod-20220914.care.dim_intercom_agents`    a
    ON m.INTERCOM_MESSAGE_ASSIGNEE_ID = a.INTERCOM_ADMIN_ID
  WHERE m.INTERCOM_MESSAGE_AUTHOR_TYPE = 'admin'
    AND a.INTERCOM_TEAM_NAME_LIST      LIKE '%Training%'
    AND m.DATETIME_CREATION_INTERCOM_MESSAGE >= '2026-01-01'
  GROUP BY 1, 2
),

agent_meta AS (
  SELECT
    INTERCOM_ADMIN_ID,
    OKTA_USER_CITY_NAME                                     AS site,
    OKTA_USER_ORGANIZATION_NAME                             AS bpo,
    -- Derive market from team name list
    CASE
      WHEN INTERCOM_TEAM_NAME_LIST LIKE '%| US |%'         THEN 'NA'
      WHEN INTERCOM_TEAM_NAME_LIST LIKE '%FD | US%'        THEN 'NA'
      WHEN INTERCOM_TEAM_NAME_LIST LIKE '%CX | US%'        THEN 'NA'
      WHEN INTERCOM_TEAM_NAME_LIST LIKE '%| JP |%'         THEN 'AP'
      WHEN INTERCOM_TEAM_NAME_LIST LIKE '%| AU |%'         THEN 'AP'
      ELSE 'EU'
    END                                                     AS market,
    -- Derive BPO from team name
    CASE
      WHEN INTERCOM_TEAM_NAME_LIST LIKE '%Foundever%'      THEN 'Foundever'
      WHEN INTERCOM_TEAM_NAME_LIST LIKE 'FD |%'            THEN 'Foundever'
      WHEN INTERCOM_TEAM_NAME_LIST LIKE '%Concentrix%'     THEN 'Concentrix'
      WHEN INTERCOM_TEAM_NAME_LIST LIKE 'CX |%'            THEN 'Concentrix'
      WHEN INTERCOM_TEAM_NAME_LIST LIKE '%Altius%'         THEN 'Altius'
      ELSE 'Internal'
    END                                                     AS bpo_derived,
    INTERCOM_TEAM_NAME_LIST
  FROM `datamart-prod-20220914.care.dim_intercom_agents`
  WHERE INTERCOM_TEAM_NAME_LIST LIKE '%Training%'
)

SELECT
  f.agent_id,
  f.agent_name,
  a.site,
  COALESCE(a.bpo, a.bpo_derived)                                          AS bpo,
  a.market,
  f.go_live_date,
  -- Cohort = go-live ISO week + site (for cohort-level grouping)
  CONCAT(FORMAT_DATE('%G-W%V', f.go_live_date), ' · ', COALESCE(a.site, a.bpo_derived)) AS cohort_id,
  -- Tenure week: W1 = first week after go-live
  DATE_DIFF(CURRENT_DATE(), f.go_live_date, WEEK) + 1                     AS tenure_week_current,
  -- For weekly analysis: tenure week at any given week
  -- Usage: DATE_DIFF(analysis_week_date, f.go_live_date, WEEK) + 1
  CASE
    WHEN DATE_DIFF(CURRENT_DATE(), f.go_live_date, WEEK) + 1 <= 8        THEN 'NEW_HIRE'
    ELSE 'TENURED'
  END                                                                       AS seniority,
  -- Benchmark lookups: map tenure week to benchmark values
  CASE DATE_DIFF(CURRENT_DATE(), f.go_live_date, WEEK) + 1
    WHEN 1 THEN 56.0 WHEN 2 THEN 59.0 WHEN 3 THEN 63.0 WHEN 4 THEN 67.0
    WHEN 5 THEN 72.0 WHEN 6 THEN 74.0 WHEN 7 THEN 76.0 WHEN 8 THEN 78.0
    ELSE 80.0
  END                                                                       AS star_target_pct,
  CASE DATE_DIFF(CURRENT_DATE(), f.go_live_date, WEEK) + 1
    WHEN 1 THEN 11.1 WHEN 2 THEN 10.0 WHEN 3 THEN 8.5  WHEN 4 THEN 8.0
    WHEN 5 THEN 6.6  WHEN 6 THEN 6.5  WHEN 7 THEN 6.4  WHEN 8 THEN 6.2
    ELSE 6.0
  END                                                                       AS lrr_target_pct,
  CASE DATE_DIFF(CURRENT_DATE(), f.go_live_date, WEEK) + 1
    WHEN 1 THEN 38.85 WHEN 2 THEN 36.0 WHEN 3 THEN 33.0 WHEN 4 THEN 29.0
    WHEN 5 THEN 23.1  WHEN 6 THEN 22.5 WHEN 7 THEN 21.5 WHEN 8 THEN 21.2
    ELSE 21.0
  END                                                                       AS aht_target_mins
FROM first_live_message f
JOIN agent_meta          a
  ON f.agent_id = a.INTERCOM_ADMIN_ID
ORDER BY a.site, f.go_live_date DESC

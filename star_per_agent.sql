-- STAR per agent per week (last 8 weeks)
-- NH flag: INTERCOM_TEAM_NAME_LIST LIKE '%Training%'
-- Join with dim_intercom_agents to filter NH only

SELECT
  s.INTERCOM_ADMIN_ID                                                  AS agent_id,
  a.INTERCOM_ADMIN_NAME                                                AS agent_name,
  DATE_TRUNC(DATE(s.DATETIME_CREATION_STAR_SURVEY), WEEK(MONDAY))     AS week_start,
  FORMAT_DATE('%G-W%V', s.DATETIME_CREATION_STAR_SURVEY)              AS iso_week,
  ROUND(AVG(s.STAR_RATING) * 100, 1)                                  AS star_pct,
  COUNT(*)                                                             AS nb_surveys
FROM `datamart-prod-20220914.care.fact_intercom_star_surveys` s
JOIN `datamart-prod-20220914.care.dim_intercom_agents`        a
  ON s.INTERCOM_ADMIN_ID = a.INTERCOM_ADMIN_ID
WHERE s.DATETIME_CREATION_STAR_SURVEY >= DATE_SUB(CURRENT_DATE(), INTERVAL 8 WEEK)
  AND a.INTERCOM_TEAM_NAME_LIST LIKE '%Training%'
GROUP BY 1, 2, 3, 4
ORDER BY week_start DESC, agent_name

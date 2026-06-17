-- LRR (Late Reply Rate) per agent per week (last 8 weeks)
-- Formula: SUM(LATE) / SUM(NEEDS_ANSWER)
-- NH flag: INTERCOM_TEAM_NAME_LIST LIKE '%Training%'

SELECT
  m.INTERCOM_MESSAGE_ASSIGNEE_ID                                            AS agent_id,
  m.INTERCOM_MESSAGE_ASSIGNEE_NAME                                          AS agent_name,
  DATE_TRUNC(DATE(m.DATETIME_CREATION_INTERCOM_MESSAGE), WEEK(MONDAY))      AS week_start,
  FORMAT_DATE('%G-W%V', m.DATETIME_CREATION_INTERCOM_MESSAGE)               AS iso_week,
  ROUND(
    SAFE_DIVIDE(
      SUM(CAST(m.INTERCOM_MESSAGE_LATE         AS INT64)),
      NULLIF(SUM(CAST(m.INTERCOM_MESSAGE_NEEDS_ANSWER AS INT64)), 0)
    ) * 100, 1
  )                                                                          AS lrr_pct,
  SUM(CAST(m.INTERCOM_MESSAGE_NEEDS_ANSWER AS INT64))                       AS nb_messages_needing_reply
FROM `datamart-prod-20220914.care.fact_intercom_messages`  m
JOIN `datamart-prod-20220914.care.dim_intercom_agents`     a
  ON m.INTERCOM_MESSAGE_ASSIGNEE_ID = a.INTERCOM_ADMIN_ID
WHERE m.INTERCOM_MESSAGE_AUTHOR_TYPE        = 'admin'
  AND m.INTERCOM_MESSAGE_NEEDS_ANSWER       = TRUE
  AND a.INTERCOM_TEAM_NAME_LIST LIKE '%Training%'
  AND m.DATETIME_CREATION_INTERCOM_MESSAGE >= DATE_SUB(CURRENT_DATE(), INTERVAL 8 WEEK)
GROUP BY 1, 2, 3, 4
HAVING nb_messages_needing_reply >= 5
ORDER BY week_start DESC, agent_name

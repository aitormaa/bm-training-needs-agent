-- ============================================================
-- TRAINING FLAGS TABLE  v2
-- Written by the Dust Training Needs Agent every Monday 08:00 CET.
-- Mayday article content is fetched by the MaydayKBNavigator sub-agent
-- and stored here — Streamlit reads it directly, no Mayday API needed.
-- Create once before first agent run.
-- ============================================================

CREATE TABLE IF NOT EXISTS `data-champions-prod-230414.training_needs.training_flags`
(
  -- Identity
  pipeline_week               STRING    NOT NULL,  -- "2026-W24"
  agent_id                    STRING,
  agent_name                  STRING    NOT NULL,
  site                        STRING,
  bpo                         STRING,
  market                      STRING,
  cohort_id                   STRING,              -- "2026-W19 · Bogotá"

  -- Tenure (derived from raw BigQuery, no spreadsheet)
  go_live_date                DATE,
  tenure_week                 INT64,
  seniority                   STRING,              -- NEW_HIRE | TENURED

  -- KPI actuals (last completed week)
  star_actual                 FLOAT64,
  star_target                 FLOAT64,
  lrr_actual                  FLOAT64,
  lrr_target                  FLOAT64,
  aht_actual                  FLOAT64,
  qa_score                    FLOAT64,

  -- TNA Classification
  priority                    STRING    NOT NULL,  -- P0 | P1 | P2 | P3
  root_cause                  STRING,              -- Process Compliance | Ownership | Communication | Efficiency | Tool | Multi-Gap | Critical Risk
  weeks_repeated              INT64,
  pattern_type                STRING,              -- First | Repeat | Systemic | Multi-gap
  trajectory_alert            BOOL,

  -- Recommendation (from Recommendation Engine)
  recommended_intervention    STRING,
  explanation_text            STRING,              -- quoted from AI QA explanation field
  failing_categories          STRING,              -- from LIST_CUSTOMER_ISSUES_CATEGORIES

  -- Mayday article (fetched by MaydayKBNavigator sub-agent)
  -- Only populated when root_cause = 'Process Compliance'
  mayday_article_title        STRING,              -- article title
  mayday_article_url          STRING,              -- direct link to article in Mayday
  mayday_article_steps        STRING,              -- relevant steps as plain text (decision trees flattened)
  mayday_article_missed_step  STRING,              -- the specific step the agent missed (quoted)
  mayday_locale               STRING,              -- locale used for search e.g. "fr", "en", "de"

  -- Meta
  created_at                  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE_TRUNC(DATE(created_at), WEEK)
OPTIONS (
  description = "Weekly TNA flags from Dust Training Needs Agent. Mayday articles fetched via MaydayKBNavigator sub-agent.",
  labels = [("team", "cx-training"), ("source", "dust-agent")]
);

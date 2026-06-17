Back Market — CX Training Needs Identification Agent

    Autonomous weekly agent that queries BigQuery, classifies agent performance gaps, detects repeated failure patterns, calls MaydayKBNavigator for process failures, and recommends precise training interventions — every Monday at 08:00 CET without human input.

What This Is
A Dust-based autonomous agent that replaces two manual workflows at Back Market CX:

    Weekly QA calibration sessions — previously 10–12 hours/market manager/week, now automated
    BPO DSTAR/performance exports — previously manually shared by Concentrix via Google Sheets, now queried directly from BigQuery

The agent covers all markets (EU, NA, AP), all sites (Bogotá, Izmir, Antananarivo, Braga, Managua, Abidjan, Sendai, Internal), all BPOs (Foundever, Concentrix, Altius, Internal Care), and all 2026 training cohorts starting from post-nesting (W1 = go-live date).
Repository Structure

bm-training-needs-agent/
├── README.md
├── app.py                        # Streamlit dashboard — main entry point
├── requirements.txt              # Python dependencies
├── config.toml                   # Streamlit theme (Back Market brand)
├── training_flags_schema.sql     # BigQuery table created once before first run
├── queries/
│   ├── tenure_week_per_agent.sql
│   ├── star_per_agent.sql
│   └── lrr_per_agent.sql
└── agent/
    └── system_prompt_v2.md       # Dust agent system prompt — full logic

Architecture

Every Monday 08:00 CET
        │
        ▼
  Dust Wake-up trigger (wak_NuzxXDd0Vfcx)
        │
        ▼
  care-TrainingNeedsAgent (Dust — Claude Sonnet, temperature 0)
        │
        ├── BigQuery: AI QA Score per agent     (data-champions-prod-230414)
        ├── BigQuery: STAR per agent × 5 weeks  (datamart-prod-20220914.care)
        ├── BigQuery: LRR per agent × 5 weeks   (datamart-prod-20220914.care)
        ├── BigQuery: AHT group level × 5 weeks (analysts-prod-230317.CCBM_PERFORMANCE)
        ├── BigQuery: FRT per agent × 5 weeks   (datamart-prod-20220914.care)
        └── BigQuery: Tenure week per agent      (datamart-prod-20220914.care — derived)
        │
        ▼
  TNA Loop: Collect → Analyze → Prioritize → Act → Evaluate
        │
        ├── Root Cause Classification (6 types)
        ├── Repeat Pattern Detection (4-week rolling)
        ├── Trajectory Detection (5-week rolling, 3 signals)
        ├── care-MaydayKBNavigator sub-agent (sId=KUvpl8xLF0)
        │     └── called when PROCESS_COMPLIANCE = NO
        │         fetches live Mayday article + missed step
        └── Training Recommendation Engine (logic tree → 8 intervention formats)
        │
        ▼
  Weekly Output:
  ├── Part A: Priority Alert Table (P0/P1/P2)
  ├── Part B: Weekly Summary Narrative
  ├── Part C: Repeat Pattern Table
  ├── Part D: Trajectory Watch List
  └── Part E: Full Agent List (all agents including P3 On Track)
        │
        ├── → Append to TNA_Flags tab (Google Sheets)
        │         └── BigQuery Data Transfer syncs → training_flags table
        └── → Post summary to Slack #cx-training (configured separately)

Streamlit Dashboard
Live dashboard that reads directly from BigQuery. Deployed on Streamlit Cloud.

streamlit run app.py

Tab	Content
Agent Table	Per-agent RAG table — P1 agents expand to show AI explanation + Mayday article
Learning Curves	NH STAR weekly trend vs. Fast Track benchmark by market
AHT	Group-level AHT by market with 21-min target line
TNA Flags	Agent output: P0/P1/P2/P3 with explanation + Mayday step + recommendation
Streamlit Cloud deploy: connect this GitHub repo, set main file to app.py, add [gcp_service_account] secret (see deploy instructions below).
Data Sources
BigQuery Tables
Table	Project	Purpose	Refresh	Status
care.fact_intercom_star_surveys	datamart-prod-20220914	STAR per agent per ticket	Real-time	✅ Active
care.fact_intercom_messages	datamart-prod-20220914	LRR per agent · FRT	Real-time	✅ Active
care.dim_intercom_agents	datamart-prod-20220914	Agent metadata: site, BPO, team list, tenure derivation	Weekly	✅ Active
CCBM_PERFORMANCE.internal_care_perf_monitoring_tracker	analysts-prod-230317	Group-level AHT	Monday	✅ Active
QA_Evaluation_AI.AI_QA_Assessments	data-champions-prod-230414	AI QA Score V2: 9 criteria + explanations	Monday	✅ Active
training_needs.training_flags	data-champions-prod-230414	TNA flags written by agent every Monday	Monday	✅ Active — run training_flags_schema.sql once to create
Blocked / Pending
Table	Blocker	Impact
UNIVERS_ZENDESK.* in analysts-prod-230317	Access request submitted	Per-agent AHT (vs. group-level only)
Intercom MCP (mcp.intercom.com)	Request submitted	Ticket retrieval for P1 calibration
Deprecated
Table	Reason
datamart-prod-20220914.care.fact_live_chat	Data stops November 2025. No longer updated.
Key Filters & Business Logic
New Hire detection

INTERCOM_TEAM_NAME_LIST LIKE '%Training%'
-- Concentrix Training | Foundever Training | Altius Training
-- Covers all BPO sites: Izmir, Bogotá, Managua, Antananarivo, Abidjan, Braga, Sendai

Tenure week (W1 = go-live date, derived from raw data)

WITH first_live AS (
  SELECT
    m.INTERCOM_MESSAGE_ASSIGNEE_ID,
    MIN(DATE(m.DATETIME_CREATION_INTERCOM_MESSAGE)) AS go_live_date
  FROM `datamart-prod-20220914.care.fact_intercom_messages` m
  JOIN `datamart-prod-20220914.care.dim_intercom_agents` a
    ON m.INTERCOM_MESSAGE_ASSIGNEE_ID = a.INTERCOM_ADMIN_ID
  WHERE m.INTERCOM_MESSAGE_AUTHOR_TYPE = 'admin'
    AND a.INTERCOM_TEAM_NAME_LIST LIKE '%Training%'
    AND m.DATETIME_CREATION_INTERCOM_MESSAGE >= '2026-01-01'
  GROUP BY 1
)
SELECT
  INTERCOM_MESSAGE_ASSIGNEE_ID,
  go_live_date,
  DATE_DIFF(CURRENT_DATE(), go_live_date, WEEK) + 1 AS tenure_week,
  CASE
    WHEN DATE_DIFF(CURRENT_DATE(), go_live_date, WEEK) + 1 <= 8 THEN 'NEW_HIRE'
    ELSE 'TENURED'
  END AS seniority
FROM first_live

W1–W8 = New Hire. W9+ = Tenured. W1 = first week of live contacts (post-nesting).
Agent Logic — TNA Loop
Root Cause Classification
Root Cause	Primary signal	Training type
Process Compliance	PROCESS_COMPLIANCE = NO	Brief process → Self-study (Mayday article) → Refresher
Ownership / Resolution	CRITICAL_FAIL_RESOLVED_WITHOUT_SOLVING	Shadowing + Refresher
Communication Skills	PERSONALIZATION = NO, TONE = NO, CLARITY = NO	Role play + Shadowing
Process Efficiency	PROCESS_EFFICIENCY = NO or AHT above target	Scenario practice + Coaching
Tool / Status	TICKET_STATUS_COMPLIANCE = NO	Tool refresher + Quiz
Multi-Gap	2+ root causes	Multi-track plan
Critical Risk	CRITICAL_FAIL_OVERALL = YES or GDPR_COMPLIANT = NO	P0 escalation
Priority Tiering
Tier	Condition
P0 Escalate	Critical Fail or GDPR violation
P1 Urgent	2+ dimensions below target + 1 KPI below benchmark OR systemic (3+ weeks)
P2 Watch	1 dimension below target OR 1 KPI below benchmark OR declining trajectory
P3 On Track	All dimensions and KPIs at or above benchmark
Learning Curve Benchmarks
Week	STAR	LRR	AHT	Phase
W1	56%	11.1%	38.85 min	Post-nesting ramp
W2	59%	10.0%	36.0 min	Post-nesting ramp
W3	63%	8.5%	33.0 min	Post-nesting ramp
W4	67%	8.0%	29.0 min	Post-nesting ramp
W5	72%	6.6%	23.1 min	Post-nesting ramp
W6	74%	6.5%	22.5 min	Post-nesting ramp
W7	76%	6.4%	21.5 min	Post-nesting ramp
W8	78%	6.2%	21.2 min	Post-nesting ramp
W9+	80%	6.0%	21.0 min	Tenured
QA Score pass threshold: 85/100 (all tenures)
Connections Status
Connection	Status	Notes
BigQuery datamart-prod-20220914.care	✅ Active	STAR, LRR, FRT, agent metadata
BigQuery analysts-prod-230317.CCBM_PERFORMANCE	✅ Active	Group-level AHT
BigQuery data-champions-prod-230414.QA_Evaluation_AI	✅ Active	AI QA Score V2
BigQuery data-champions-prod-230414.training_needs	✅ Active	TNA flags write-back (via Sheets → BQ Data Transfer)
Google Sheets — Learning Curve Dashboard	✅ Active	1h9nYtUAM_T2swV0H8nb1z9fHrLHyq56KqzVBWK9ZeFU
Mayday KB	✅ Active	care-MaydayKBNavigator sub-agent (sId=KUvpl8xLF0) — OAuth handled internally
Streamlit Dashboard	✅ Active	Deployed on Streamlit Cloud — reads BigQuery directly
Dust Wake-up	✅ Active	wak_NuzxXDd0Vfcx — Mon 08:00 CET
Slack — CX Training channel	🟡 Ready to configure	Not yet wired
Intercom MCP	🔴 Request submitted	For P1 ticket retrieval
Per-agent AHT (UNIVERS_ZENDESK)	🔴 Access pending	Currently group-level only
Streamlit Deploy Instructions

# Local
gcloud auth application-default login
pip install -r requirements.txt
streamlit run app.py

Streamlit Cloud:

    Go to share.streamlit.io → New app
    Connect this GitHub repo → set main file to app.py
    Settings → Secrets → paste:

[gcp_service_account]
type                        = "service_account"
project_id                  = "datamart-prod-20220914"
private_key_id              = "PASTE_FROM_JSON"
private_key                 = "-----BEGIN RSA PRIVATE KEY-----\nPASTE\n-----END RSA PRIVATE KEY-----\n"
client_email                = "bm-training-dashboard@YOUR_PROJECT.iam.gserviceaccount.com"
client_id                   = "PASTE_FROM_JSON"
auth_uri                    = "https://accounts.google.com/o/oauth2/auth"
token_uri                   = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url        = "https://www.googleapis.com/robot/v1/..."

    Deploy → get permanent URL

Roadmap
Priority	Initiative	Status
🔴 High	Run training_flags_schema.sql in BigQuery	Pending — do once
🔴 High	Configure BigQuery Data Transfer (Sheets → BQ)	Pending — GCP admin
🔴 High	Create GCP service account for Streamlit	Pending — GCP admin
🟡 Medium	Slack auto-post on Monday run	Ready to configure
🟡 Medium	UNIVERS_ZENDESK access for per-agent AHT	Request submitted
🟡 Medium	Intercom MCP for P1 ticket calibration	Request submitted
🟢 Future	360Learning integration for auto-course assignment	Phase 2
🟢 Future	Real-time ticket monitoring (pre-resolution)	Not technically feasible yet
Changelog
v2.1 — June 17, 2026

    Migrated dashboard from static HTML to Streamlit (live BigQuery feed)
    Added Mayday KB integration via care-MaydayKBNavigator sub-agent (sId=KUvpl8xLF0)
    Added training_flags BigQuery table (written by agent via Google Sheets → BQ Data Transfer)
    Added mayday_article_title/url/steps/missed_step columns to training_flags
    Updated repository structure: streamlit/ replaces dashboard/
    Added BigQuery Data Transfer pipeline for write-back
    All 2026 cohorts confirmed: Izmir, Bogotá, Managua, Antananarivo, Abidjan, Braga, Sendai

v2.0 — June 16, 2026

    Added TNA Loop operating model (Collect → Analyze → Prioritize → Act → Evaluate)
    Added root cause classification (6 types)
    Added repeat pattern detection (4-week rolling window)
    Added proactive trajectory detection (5-week rolling, 3 signals)
    Added training recommendation engine (full logic tree, 8 intervention formats)
    Added AI QA Score V2 full schema
    Added tenure week auto-calculation from raw BigQuery data (no manual spreadsheet)
    Added cohort definition logic (go_live_week + site)
    Scope expanded: all 2026 cohorts, all markets/sites/BPOs
    Wake-up scheduled: Monday 08:00 CET (wak_NuzxXDd0Vfcx)

v1.1 — June 2026

    Added autonomous mode
    Added calibration mode (ticket-level QA comparison)

v1.0 — Initial build

    Manual invocation mode
    QA Score + NH Performance sheet input
    Basic root cause table
    Priority tiering P0–P3

Authors
Aitor Martin — CX Training & Quality, Back Market
Built with Dust AI (Claude Sonnet) — June 2026

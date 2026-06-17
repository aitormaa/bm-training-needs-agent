Back Market — CX Training Needs Identification Agent
> Autonomous weekly agent that queries BigQuery, classifies agent performance gaps, detects repeated failure patterns, and recommends precise training interventions — every Monday at 08:00 CET without human input.
---
What This Is
A Dust-based autonomous agent that replaces two manual workflows at Back Market CX:
Weekly QA calibration sessions — previously 10–12 hours/market manager/week, now automated
BPO DSTAR/performance exports — previously manually shared by Concentrix via Google Sheets, now queried directly from BigQuery
The agent covers all markets (EU, NA, AP), all sites (Bogotá, Izmir, Antananarivo, Braga, Managua, Abidjan, Sendai, Internal), all BPOs (Foundever, Concentrix, Altius, Internal Care), and all 2026 training cohorts starting from post-nesting (W1 = go-live date).
---
Repository Structure
```
bm-training-needs-agent/
├── README.md
├── agent/
│   └── system_prompt_v2.md          # Dust agent system prompt — full logic
├── dashboard/
│   └── bm_learning_curve_dashboard_v2.html  # Static HTML dashboard (auto-regenerated)
├── queries/
│   ├── star_per_agent.sql
│   ├── lrr_per_agent.sql
│   ├── aht_group_level.sql
│   ├── frt_per_agent.sql
│   ├── qa_score_weekly.sql
│   ├── repeat_pattern_4w.sql
│   └── tenure_week_per_agent.sql
└── docs/
    ├── data_sources.md
    ├── tna_framework.md
    └── changelog.md
```
---
Architecture
```
Every Monday 08:00 CET
        │
        ▼
  Dust Wake-up trigger (wak_NuzxXDd0Vfcx)
        │
        ▼
  Training Needs Agent (Dust — Claude Sonnet)
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
        └── Training Recommendation Engine (logic tree → 8 intervention formats)
        │
        ▼
  Weekly Output:
  ├── Part A: Priority Alert Table (P0/P1/P2)
  ├── Part B: Weekly Summary Narrative
  ├── Part C: Repeat Pattern Table (B3-style, agents with 2+ consecutive weeks)
  ├── Part D: Trajectory Watch List (above threshold but declining)
  └── Part E: Full Agent List (all agents including P3 On Track)
        │
        ├── → Write to Learning Curve Dashboard (Google Sheets)
        ├── → Regenerate HTML dashboard file
        └── → Post summary to Slack #cx-training
```
---
Data Sources
BigQuery Tables
Table	Project	Purpose	Refresh	Status
`care.fact_intercom_star_surveys`	`datamart-prod-20220914`	STAR per agent per ticket	Real-time	✅ Active
`care.fact_intercom_messages`	`datamart-prod-20220914`	LRR per agent · FRT (`ELAPSED_SECONDS_SINCE_LAST_MESSAGE`)	Real-time	✅ Active
`care.dim_intercom_agents`	`datamart-prod-20220914`	Agent metadata: site, BPO, team list, go-live derivation	Weekly	✅ Active
`CCBM_PERFORMANCE.internal_care_perf_monitoring_tracker`	`analysts-prod-230317`	Group-level AHT (`TOTAL_AVG_HANDLING_TIME_MINS`)	Monday	✅ Active
`QA_Evaluation_AI.AI_QA_Assessments`	`data-champions-prod-230414`	AI QA Score V2: 9 criteria YES/NO + AI explanations, critical fails, GDPR	Monday	✅ Table confirmed — access to verify
Blocked / Pending
Table	Blocker	Impact
`UNIVERS_ZENDESK.*` in `analysts-prod-230317`	Access request submitted	Per-agent AHT (vs. group-level only)
Intercom MCP (`mcp.intercom.com`)	Request submitted	Ticket retrieval for P1 calibration
Mayday KB	Pending MCP server from Mayday team	Process Compliance → specific article cross-reference
Deprecated
Table	Reason
`datamart-prod-20220914.care.fact_live_chat`	Data stops November 2025. No longer updated.
---
Key Filters & Business Logic
New Hire detection
```sql
-- From dim_intercom_agents
INTERCOM_TEAM_NAME_LIST LIKE '%Training%'
-- e.g. 'Foundever Training', 'Concentrix Training', 'Altius Training'
```
Tenure week (W1 = go-live date, derived from raw data)
```sql
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
```
W1–W8 = New Hire (post-nesting ramp). W9+ = Tenured.
W1 = first week of live contacts (go-live date). No manual spreadsheet dependency.
Market mapping
`MARKETPLACE = 'NA'` → US market
BPO from `INTERCOM_TEAM_NAME_LIST`: `FD | ...` → Foundever, `CX | ...` → Concentrix
Site from `OKTA_USER_CITY_NAME` in `dim_intercom_agents`
Cohort definition
```
cohort_id = go_live_week + site
-- e.g. "2026-W18 · Izmir" or "2026-W19 · Bogotá"
```
Agents in the same cohort share training context. Used for cohort-level pattern detection alongside individual analysis.
---
Agent Logic — TNA Loop
1. Operating Model
Every invocation executes the full loop:
Collect → Analyze → Prioritize → Act → Evaluate
2. Root Cause Classification
Root Cause	Primary signal	Training type
Process Compliance	`PROCESS_COMPLIANCE = NO`	Refresher / Self-study / Brief process (by repeat count)
Ownership / Resolution	`CRITICAL_FAIL_RESOLVED_WITHOUT_SOLVING` or `OVERLOOKED_REQUESTS`	Shadowing + Refresher
Communication Skills	`PERSONALIZATION = NO`, `TONE = NO`, `CLARITY = NO`	Role play + Shadowing
Process Efficiency	`PROCESS_EFFICIENCY = NO` or AHT above target for tenure	Scenario practice + Coaching
Tool / Status	`TICKET_STATUS_COMPLIANCE = NO`	Tool refresher + Quiz
Multi-Gap	2+ root causes	Multi-track plan
Critical Risk	`CRITICAL_FAIL_OVERALL = YES` or `GDPR_COMPLIANT = NO`	P0 escalation — not a training pathway
3. Repeat Pattern Detection (4-week rolling)
Pattern	Definition	Action
First occurrence	Root cause in week N only	Targeted intervention
Repeat	Same root cause N and N-1	Coaching alert
Systemic	Same root cause N, N-1, N-2	Formal training (P2 → P1 escalation)
Multi-gap	Root cause changes week over week	Manual review
4. Proactive Trajectory Detection (5-week rolling)
Signal	Condition	Alert type
STAR	Declining ≥ 2pp/week × 2 weeks AND above threshold	WATCH (trajectory)
LRR	Increasing ≥ 1pp/week × 2 weeks AND below threshold	WATCH (trajectory)
QA Score	Declining ≥ 3pts/week × 2 weeks	WATCH (trajectory)
5. Training Recommendation Engine
```
IF critical fail or GDPR → P0 ESCALATION (not training)

IF process compliance fail:
  week 1 → BRIEF PROCESS (specific failed rule)
  week 2 → SELF-STUDY (named Mayday article) + BRIEF PROCESS
  week 3+ → REFRESHER SESSION + QUIZ before live contacts

IF ownership/resolution → SHADOWING (min 2 sessions) + REFRESHER

IF communication skills:
  personalization → ROLE PLAY (adapt generic responses)
  tone → ROLE PLAY (empathy + apology language)
  clarity → ROLE PLAY (simplify explanations)
  + SHADOWING

IF process efficiency → SCENARIO PRACTICE + COACHING

IF tool/status → TOOL REFRESHER + SHORT QUIZ (pass = 80%)

IF multi-gap → COMBINE above in order: Critical > Process > Soft Skills > Efficiency > Tool
```
6. Priority Tiering
Tier	Condition
P0 Escalate	Critical Fail or GDPR violation
P1 Urgent	2+ dimensions below target + 1 KPI below benchmark OR systemic (3+ weeks)
P2 Watch (threshold)	1 dimension below target OR 1 KPI below benchmark
P2 Watch (trajectory)	Above threshold but declining ≥ defined rate for 2 weeks
P3 On Track	All dimensions and KPIs at or above benchmark
---
Learning Curve Benchmarks
Week	STAR	LRR	AHT	Agent Resp.	Phase
W1	56%	11.1%	38.85 min	46.3%	Post-nesting ramp
W2	59%	10.0%	36.0 min	42.0%	Post-nesting ramp
W3	63%	8.5%	33.0 min	38.0%	Post-nesting ramp
W4	67%	8.0%	29.0 min	34.0%	Post-nesting ramp
W5	72%	6.6%	23.1 min	27.5%	Post-nesting ramp
W6	74%	6.5%	22.5 min	26.0%	Post-nesting ramp
W7	76%	6.4%	21.5 min	25.5%	Post-nesting ramp
W8	78%	6.2%	21.2 min	25.2%	Post-nesting ramp
W9+	80%	6.0%	21.0 min	25.0%	Tenured
QA Score pass threshold: 85/100 (all tenures)
---
Connections Status
Connection	Status	Notes
BigQuery `datamart-prod-20220914.care`	✅ Active	All care tables
BigQuery `analysts-prod-230317.CCBM_PERFORMANCE`	✅ Active	AHT tracker
BigQuery `data-champions-prod-230414.QA_Evaluation_AI`	🟡 Pending verification	Table confirmed
Google Sheets — Learning Curve Dashboard	✅ Active	ID: `1h9nYtUAM_T2swV0H8nb1z9fHrLHyq56KqzVBWK9ZeFU`
Google Sheets — NH Performance Template	✅ Active	ID: `1qD4MyIbal6Ix117D_aKgyp2eNGK7OkZnu7eXCVMKyXY`
Slack — CX Training channel	🟡 Available — not yet configured	
Intercom MCP	🔴 Request submitted	For P1 ticket retrieval
Mayday KB	🔴 Pending Mayday MCP server	Process cross-reference
Dust Wake-up	✅ Active	`wak_NuzxXDd0Vfcx` — Mon 08:00 CET
---
Dashboard
File: `dashboard/bm_learning_curve_dashboard_v2.html`
8-tab interactive HTML dashboard. Data currently embedded at generation time. Planned migration to live BigQuery feed (see Roadmap).
Tab	Content
Overview	KPI cards (STAR, LRR, AHT) + trend charts W15–W24
Learning Curve	NH actuals vs. Fast Track benchmarks
AHT & FRT	Group AHT by market + per-agent FRT by site
AI QA Score	Schema reference + 2 query templates
Rec Engine	Logic tree + intervention formats
Patterns & Signals	Repeat detection + trajectory thresholds + report structure
By Dimension	Market / Site / BPO breakdowns
Agents	Per-agent table: STAR, LRR, FRT, QA Score, tenure week
---
Roadmap
Priority	Initiative	Status
🔴 High	Verify `data-champions-prod-230414` BigQuery access	Pending
🔴 High	Replace hardcoded HTML data with live BigQuery feed (Streamlit)	Planned
🔴 High	Cohort-level pattern detection alongside individual analysis	Planned
🟡 Medium	Slack auto-post on Monday run	Ready to configure
🟡 Medium	UNIVERS_ZENDESK access for per-agent AHT	Request submitted
🟡 Medium	Intercom MCP for P1 ticket calibration	Request submitted
🟢 Future	Mayday KB integration via MCP (when available)	Waiting on Mayday team
🟢 Future	360Learning integration for auto-course assignment	Phase 2
🟢 Future	Real-time ticket monitoring (pre-resolution)	Not technically feasible yet
---
Changelog
v2.0 — June 16, 2026
Added TNA Loop operating model (Collect → Analyze → Prioritize → Act → Evaluate)
Added root cause classification (6 types)
Added repeat pattern detection (4-week rolling window)
Added proactive trajectory detection (5-week rolling, 3 signals)
Added training recommendation engine (full logic tree, 8 intervention formats)
Added AI QA Score V2 full schema + 2 BigQuery query templates
Added tenure week auto-calculation from raw BigQuery data (no manual spreadsheet)
Added cohort definition logic (go_live_week + site)
Scope expanded: all 2026 cohorts, all markets/sites/BPOs, W1 = go-live
Wake-up scheduled: Monday 08:00 CET (`wak_NuzxXDd0Vfcx`)
Dashboard v2: 8 tabs (added AI QA Score, Rec Engine, Patterns & Signals)
v1.1 — June 2026 (prior)
Added autonomous mode
Added calibration mode (ticket-level QA comparison)
v1.0 — Initial build
Manual invocation mode
QA Score + NH Performance sheet input
Basic root cause table
Priority tiering P0–P3
---
Authors
Aitor Martin — CX Training & Quality, Back Market
Built with Dust AI (Claude Sonnet) — June 2026

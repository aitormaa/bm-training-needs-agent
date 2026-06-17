"""
Back Market — CX Training Needs Dashboard  v4
Two-layer architecture:
  Layer 1  Visual dashboard — reads raw KPIs + TNA flags from BigQuery
  Layer 2  Dust Training Needs Agent — queries data, calls MaydayKBNavigator
           sub-agent for article lookup, writes everything to training_flags

Mayday:
  All Mayday interaction is handled by the Dust agent via MaydayKBNavigator.
  OAuth is managed inside that sub-agent. Streamlit reads the article content
  directly from training_flags — no Mayday API credentials needed here.

Local:           gcloud auth application-default login → streamlit run app.py
Streamlit Cloud: connect GitHub repo → add [gcp_service_account] secret
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from google.cloud import bigquery
from google.oauth2 import service_account

# ─── PAGE CONFIG ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BM CX Training Needs",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── CONSTANTS ───────────────────────────────────────────────────────────────
COLORS = {
    "purple": "#3D1152", "yellow": "#F5D752", "blue": "#2E4FFF",
    "green":  "#27AE60", "red":    "#E74C3C", "amber": "#F39C12",
}

# Learning curve benchmarks — W1 = go-live (post-nesting), W9+ = Tenured
BENCHMARKS = {
    1: {"star": 56.0, "lrr": 11.1, "aht": 38.85},
    2: {"star": 59.0, "lrr": 10.0, "aht": 36.00},
    3: {"star": 63.0, "lrr":  8.5, "aht": 33.00},
    4: {"star": 67.0, "lrr":  8.0, "aht": 29.00},
    5: {"star": 72.0, "lrr":  6.6, "aht": 23.10},
    6: {"star": 74.0, "lrr":  6.5, "aht": 22.50},
    7: {"star": 76.0, "lrr":  6.4, "aht": 21.50},
    8: {"star": 78.0, "lrr":  6.2, "aht": 21.20},
    9: {"star": 80.0, "lrr":  6.0, "aht": 21.00},
}

PRIORITY_EMOJI = {"P0": "🚨", "P1": "🔴", "P2": "🟡", "P3": "✅"}
GCP_SCOPES     = ["https://www.googleapis.com/auth/bigquery",
                  "https://www.googleapis.com/auth/cloud-platform"]


# ════════════════════════════════════════════════════════════════════════════
#  BIGQUERY CLIENT
#  Auto-detects environment: Streamlit Cloud secret vs. local ADC
# ════════════════════════════════════════════════════════════════════════════

@st.cache_resource
def get_bq_client() -> bigquery.Client:
    """
    Streamlit Cloud → reads [gcp_service_account] from Streamlit Secrets.
    Local           → uses Application Default Credentials.
                      Run once: gcloud auth application-default login

    Streamlit Cloud secret format (Settings → Secrets):

        [gcp_service_account]
        type                        = "service_account"
        project_id                  = "datamart-prod-20220914"
        private_key_id              = "..."
        private_key                 = "-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n"
        client_email                = "bm-dashboard@YOUR_PROJECT.iam.gserviceaccount.com"
        client_id                   = "..."
        auth_uri                    = "https://accounts.google.com/o/oauth2/auth"
        token_uri                   = "https://oauth2.googleapis.com/token"
        auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
        client_x509_cert_url        = "https://www.googleapis.com/robot/v1/..."
    """
    if "gcp_service_account" in st.secrets:
        creds = service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"], scopes=GCP_SCOPES)
        return bigquery.Client(
            credentials=creds,
            project=st.secrets["gcp_service_account"]["project_id"])
    return bigquery.Client()


# ════════════════════════════════════════════════════════════════════════════
#  BIGQUERY QUERIES
# ════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner="Loading agent roster...")
def load_tenure_data() -> pd.DataFrame:
    """
    Every 2026 NH agent with go-live date and current tenure week.
    W1 = first live contact (post-nesting). W1–W8 = NEW_HIRE. W9+ = TENURED.
    Derived entirely from raw BigQuery — no manual spreadsheet dependency.
    """
    sql = """
    WITH first_live AS (
      SELECT
        m.INTERCOM_MESSAGE_ASSIGNEE_ID                  AS agent_id,
        m.INTERCOM_MESSAGE_ASSIGNEE_NAME                AS agent_name,
        MIN(DATE(m.DATETIME_CREATION_INTERCOM_MESSAGE)) AS go_live_date
      FROM `datamart-prod-20220914.care.fact_intercom_messages`  m
      JOIN `datamart-prod-20220914.care.dim_intercom_agents`     a
        ON m.INTERCOM_MESSAGE_ASSIGNEE_ID = a.INTERCOM_ADMIN_ID
      WHERE m.INTERCOM_MESSAGE_AUTHOR_TYPE = 'admin'
        AND a.INTERCOM_TEAM_NAME_LIST LIKE '%Training%'
        AND m.DATETIME_CREATION_INTERCOM_MESSAGE >= '2026-01-01'
      GROUP BY 1, 2
    )
    SELECT
      f.agent_id,
      f.agent_name,
      COALESCE(NULLIF(a.OKTA_USER_CITY_NAME, ''),
        CASE
          WHEN a.INTERCOM_TEAM_NAME_LIST LIKE '%Izmir%'        THEN 'Izmir'
          WHEN a.INTERCOM_TEAM_NAME_LIST LIKE '%Bogot%'        THEN 'Bogotá'
          WHEN a.INTERCOM_TEAM_NAME_LIST LIKE '%Managua%'      THEN 'Managua'
          WHEN a.INTERCOM_TEAM_NAME_LIST LIKE '%Antananarivo%' THEN 'Antananarivo'
          WHEN a.INTERCOM_TEAM_NAME_LIST LIKE '%Abidjan%'      THEN 'Abidjan'
          WHEN a.INTERCOM_TEAM_NAME_LIST LIKE '%Braga%'        THEN 'Braga'
          WHEN a.INTERCOM_TEAM_NAME_LIST LIKE '%Sendai%'       THEN 'Sendai'
          WHEN a.INTERCOM_TEAM_NAME_LIST LIKE '%Barcelona%'    THEN 'Barcelona'
          ELSE 'Unknown'
        END)                                            AS site,
      CASE
        WHEN a.INTERCOM_TEAM_NAME_LIST LIKE '%Foundever%'
          OR a.INTERCOM_TEAM_NAME_LIST LIKE 'FD |%'    THEN 'Foundever'
        WHEN a.INTERCOM_TEAM_NAME_LIST LIKE '%Concentrix%'
          OR a.INTERCOM_TEAM_NAME_LIST LIKE '%CX |%'   THEN 'Concentrix'
        WHEN a.INTERCOM_TEAM_NAME_LIST LIKE '%Altius%' THEN 'Altius'
        ELSE 'Internal'
      END                                               AS bpo,
      CASE
        WHEN a.INTERCOM_TEAM_NAME_LIST LIKE '%| US |%'
          OR a.INTERCOM_TEAM_NAME_LIST LIKE '%FD | US%'
          OR a.INTERCOM_TEAM_NAME_LIST LIKE '%CX | US%' THEN 'NA'
        WHEN a.INTERCOM_TEAM_NAME_LIST LIKE '%| JP |%'
          OR a.INTERCOM_TEAM_NAME_LIST LIKE '%| AU |%'  THEN 'AP'
        ELSE 'EU'
      END                                               AS market,
      f.go_live_date,
      FORMAT_DATE('%G-W%V', f.go_live_date)             AS go_live_week,
      DATE_DIFF(CURRENT_DATE(), f.go_live_date, WEEK) + 1 AS tenure_week,
      CASE
        WHEN DATE_DIFF(CURRENT_DATE(), f.go_live_date, WEEK) + 1 <= 8
          THEN 'NEW_HIRE' ELSE 'TENURED'
      END                                               AS seniority
    FROM first_live f
    JOIN `datamart-prod-20220914.care.dim_intercom_agents` a
      ON f.agent_id = a.INTERCOM_ADMIN_ID
    ORDER BY site, f.go_live_date DESC
    """
    return get_bq_client().query(sql).to_dataframe()


@st.cache_data(ttl=3600, show_spinner="Loading STAR...")
def load_star_data(weeks_back: int = 8) -> pd.DataFrame:
    sql = f"""
    SELECT
      INTERCOM_ADMIN_ID                                                  AS agent_id,
      DATE_TRUNC(DATE(DATETIME_CREATION_STAR_SURVEY), WEEK(MONDAY))     AS week_start,
      ROUND(AVG(STAR_RATING) * 100, 1)                                  AS star_pct,
      COUNT(*)                                                           AS nb_surveys
    FROM `datamart-prod-20220914.care.fact_intercom_star_surveys`
    WHERE DATETIME_CREATION_STAR_SURVEY
          >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks_back} WEEK)
    GROUP BY 1, 2
    """
    return get_bq_client().query(sql).to_dataframe()


@st.cache_data(ttl=3600, show_spinner="Loading LRR...")
def load_lrr_data(weeks_back: int = 8) -> pd.DataFrame:
    sql = f"""
    SELECT
      INTERCOM_MESSAGE_ASSIGNEE_ID                                            AS agent_id,
      DATE_TRUNC(DATE(DATETIME_CREATION_INTERCOM_MESSAGE), WEEK(MONDAY))     AS week_start,
      ROUND(SAFE_DIVIDE(
        SUM(CAST(INTERCOM_MESSAGE_LATE AS INT64)),
        NULLIF(SUM(CAST(INTERCOM_MESSAGE_NEEDS_ANSWER AS INT64)), 0)
      ) * 100, 1)                                                            AS lrr_pct
    FROM `datamart-prod-20220914.care.fact_intercom_messages`
    WHERE INTERCOM_MESSAGE_AUTHOR_TYPE  = 'admin'
      AND INTERCOM_MESSAGE_NEEDS_ANSWER = TRUE
      AND DATETIME_CREATION_INTERCOM_MESSAGE
          >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks_back} WEEK)
    GROUP BY 1, 2
    """
    return get_bq_client().query(sql).to_dataframe()


@st.cache_data(ttl=3600, show_spinner="Loading FRT...")
def load_frt_data(weeks_back: int = 4) -> pd.DataFrame:
    sql = f"""
    SELECT
      INTERCOM_MESSAGE_ASSIGNEE_ID                                            AS agent_id,
      DATE_TRUNC(DATE(DATETIME_CREATION_INTERCOM_MESSAGE), WEEK(MONDAY))     AS week_start,
      ROUND(
        APPROX_QUANTILES(ELAPSED_SECONDS_SINCE_LAST_MESSAGE / 3600.0, 100)[OFFSET(50)],
      2)                                                                      AS frt_median_hrs,
      COUNT(DISTINCT HELP_REQUEST_PUBLIC_ID)                                 AS tickets_handled
    FROM `datamart-prod-20220914.care.fact_intercom_messages`
    WHERE INTERCOM_MESSAGE_AUTHOR_TYPE       = 'admin'
      AND ELAPSED_SECONDS_SINCE_LAST_MESSAGE > 0
      AND DATETIME_CREATION_INTERCOM_MESSAGE
          >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks_back} WEEK)
    GROUP BY 1, 2
    HAVING tickets_handled >= 3
    """
    return get_bq_client().query(sql).to_dataframe()


@st.cache_data(ttl=3600, show_spinner="Loading AHT...")
def load_aht_data(weeks_back: int = 8) -> pd.DataFrame:
    sql = f"""
    SELECT
      WEEK_START, ISO_WEEK, YEAR, MARKETPLACE, AGENT_GROUP,
      ROUND(AVG(TOTAL_AVG_HANDLING_TIME_MINS), 1) AS avg_aht_mins,
      SUM(TOTAL_CONTACTS_SOLVED)                   AS contacts_solved
    FROM `analysts-prod-230317.CCBM_PERFORMANCE.internal_care_perf_monitoring_tracker`
    WHERE WEEK_START >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks_back} WEEK)
      AND TICKET_TOOL          = 'INTERCOM'
      AND TOTAL_CONTACTS_RECEIVED > 0
    GROUP BY 1, 2, 3, 4, 5
    ORDER BY MARKETPLACE, YEAR DESC, ISO_WEEK DESC
    """
    return get_bq_client().query(sql).to_dataframe()


@st.cache_data(ttl=900, show_spinner="Loading TNA flags from Dust agent...")
def load_tna_flags() -> pd.DataFrame:
    """
    Flags written by the Dust Training Needs Agent every Monday 08:00 CET.
    Includes Mayday article content (fetched via MaydayKBNavigator sub-agent).
    Returns empty frame with correct schema if table not yet created.
    """
    sql = """
    SELECT *
    FROM `data-champions-prod-230414.training_needs.training_flags`
    WHERE pipeline_week
          >= FORMAT_DATE('%G-W%V', DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK))
    ORDER BY pipeline_week DESC, priority ASC, agent_name
    """
    try:
        return get_bq_client().query(sql).to_dataframe()
    except Exception:
        return pd.DataFrame(columns=[
            "pipeline_week", "agent_name", "site", "bpo", "market", "tenure_week",
            "root_cause", "weeks_repeated", "priority", "recommended_intervention",
            "explanation_text", "failing_categories", "qa_score",
            "star_actual", "lrr_actual",
            "mayday_article_title", "mayday_article_url",
            "mayday_article_steps", "mayday_article_missed_step",
        ])


# ════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════════════════

def get_benchmark(tenure_week: int, metric: str) -> float:
    return BENCHMARKS.get(min(int(tenure_week), 9), BENCHMARKS[9])[metric]

def rag_star(v, t):
    if v is None or pd.isna(v): return "grey"
    return "green" if v >= t else ("amber" if v >= t - 8 else "red")

def rag_lrr(v, t):
    if v is None or pd.isna(v): return "grey"
    return "green" if v <= t else ("amber" if v <= t + 4 else "red")

def rag_emoji(c): return {"green":"✅","amber":"🟡","red":"🔴","grey":"⚪"}.get(c,"⚪")

def color_priority(val):
    return {
        "P0": "background-color:#fdecea;font-weight:bold",
        "P1": "background-color:#fdecea;font-weight:bold",
        "P2": "background-color:#fef9e7",
        "P3": "background-color:#eafaf1",
    }.get(str(val), "")

def latest_kpi(df: pd.DataFrame, id_col: str, val_cols: list) -> pd.DataFrame:
    if df.empty: return pd.DataFrame(columns=[id_col] + val_cols)
    return (df.sort_values("week_start", ascending=False)
              .groupby(id_col).first().reset_index()[[id_col] + val_cols])


# ════════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():

    # ── Header ───────────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="background:{COLORS['purple']};padding:14px 24px;border-radius:8px;
                display:flex;justify-content:space-between;align-items:center;
                margin-bottom:16px;">
      <div>
        <span style="color:white;font-size:18px;font-weight:800;">
          🎯 BM CX — Training Needs Dashboard
        </span><br>
        <span style="color:rgba(255,255,255,.6);font-size:11px;">
          BigQuery · Mayday KB (via Dust agent) · All Markets · All Sites · 2026 Onboarding
        </span>
      </div>
      <span style="background:{COLORS['yellow']};color:{COLORS['purple']};
                   padding:4px 12px;border-radius:20px;font-size:11px;font-weight:800;">
        ⏰ Mon 08:00 CET — wak_NuzxXDd0Vfcx
      </span>
    </div>
    """, unsafe_allow_html=True)

    # ── Load data ─────────────────────────────────────────────────────────────
    with st.spinner("Connecting to BigQuery..."):
        tenure_df = load_tenure_data()
        star_df   = load_star_data()
        lrr_df    = load_lrr_data()
        frt_df    = load_frt_data()
        aht_df    = load_aht_data()
        flags_df  = load_tna_flags()

    # ── Sidebar ───────────────────────────────────────────────────────────────
    st.sidebar.title("Filters")
    st.sidebar.caption(f"{len(tenure_df)} onboarding agents · 2026")
    f_market    = st.sidebar.selectbox("Market",    ["All"] + sorted(tenure_df["market"].dropna().unique()))
    f_site      = st.sidebar.selectbox("Site",      ["All"] + sorted(tenure_df["site"].dropna().unique()))
    f_bpo       = st.sidebar.selectbox("BPO",       ["All"] + sorted(tenure_df["bpo"].dropna().unique()))
    f_seniority = st.sidebar.selectbox("Seniority", ["All","NEW_HIRE","TENURED"])
    cohort_opts = sorted(
        (tenure_df["go_live_week"] + " · " + tenure_df["site"]).dropna().unique(), reverse=True)
    f_cohort    = st.sidebar.selectbox("Cohort (go-live · site)", ["All"] + cohort_opts)
    tw_min, tw_max = int(tenure_df["tenure_week"].min()), int(tenure_df["tenure_week"].max())
    f_tenure    = st.sidebar.slider("Tenure week range", tw_min, tw_max, (tw_min, tw_max))
    st.sidebar.markdown("---")
    view_mode   = st.sidebar.radio("View", ["Individual agents","Cohort view"])

    # ── Apply filters ─────────────────────────────────────────────────────────
    mask = pd.Series(True, index=tenure_df.index)
    if f_market    != "All": mask &= tenure_df["market"]    == f_market
    if f_site      != "All": mask &= tenure_df["site"]      == f_site
    if f_bpo       != "All": mask &= tenure_df["bpo"]       == f_bpo
    if f_seniority != "All": mask &= tenure_df["seniority"] == f_seniority
    if f_cohort    != "All":
        mask &= (tenure_df["go_live_week"] + " · " + tenure_df["site"]) == f_cohort
    mask &= tenure_df["tenure_week"].between(f_tenure[0], f_tenure[1])
    filtered = tenure_df[mask].copy()

    # ── Merge KPIs ────────────────────────────────────────────────────────────
    agent_df = (filtered
        .merge(latest_kpi(star_df, "agent_id", ["star_pct","nb_surveys"]), on="agent_id", how="left")
        .merge(latest_kpi(lrr_df,  "agent_id", ["lrr_pct"]),               on="agent_id", how="left")
        .merge(latest_kpi(frt_df,  "agent_id", ["frt_median_hrs","tickets_handled"]), on="agent_id", how="left")
    )

    # Merge latest TNA flags (written by Dust agent, includes Mayday content)
    flag_cols = ["agent_name","priority","root_cause","weeks_repeated",
                 "recommended_intervention","explanation_text","failing_categories",
                 "mayday_article_title","mayday_article_url",
                 "mayday_article_steps","mayday_article_missed_step"]
    if not flags_df.empty:
        lf = (flags_df.sort_values("pipeline_week", ascending=False)
                      .groupby("agent_name").first().reset_index()
              [[c for c in flag_cols if c in flags_df.columns]])
        agent_df = agent_df.merge(lf, on="agent_name", how="left")
    else:
        for c in flag_cols[1:]:  # skip agent_name
            agent_df[c] = None

    agent_df["star_target"] = agent_df["tenure_week"].apply(lambda w: get_benchmark(w,"star"))
    agent_df["lrr_target"]  = agent_df["tenure_week"].apply(lambda w: get_benchmark(w,"lrr"))
    agent_df["star_rag"]    = agent_df.apply(lambda r: rag_star(r.get("star_pct"), r["star_target"]), axis=1)
    agent_df["lrr_rag"]     = agent_df.apply(lambda r: rag_lrr(r.get("lrr_pct"),  r["lrr_target"]),  axis=1)
    agent_df["cohort"]      = agent_df["go_live_week"] + " · " + agent_df["site"]

    # ── KPI cards ─────────────────────────────────────────────────────────────
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("Agents tracked",       len(agent_df))
    c2.metric("NH (W1–W8)",           len(agent_df[agent_df["seniority"]=="NEW_HIRE"]))
    c3.metric("🔴 STAR below target", len(agent_df[agent_df["star_rag"]=="red"]))
    c4.metric("🟡 LRR above target",  len(agent_df[agent_df["lrr_rag"].isin(["red","amber"])]))
    p1n = len(agent_df[agent_df["priority"]=="P1"]) if "priority" in agent_df.columns else "—"
    c5.metric("🔴 P1 Urgent",         p1n)
    st.markdown("---")

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4 = st.tabs([
        "📋 Agent Table", "📈 Learning Curves", "⏱ AHT", "🔁 TNA Flags"
    ])

    # ── TAB 1 — AGENT / COHORT ────────────────────────────────────────────────
    with tab1:
        if view_mode == "Individual agents":
            st.caption(f"{len(agent_df)} agents · STAR and LRR vs tenure-week benchmark")
            COLS = {
                "agent_name":"Agent","site":"Site","bpo":"BPO","market":"Market",
                "tenure_week":"W","seniority":"Type","go_live_date":"Go-live",
                "star_pct":"STAR %","star_target":"Target","lrr_pct":"LRR %",
                "lrr_target":"LRR tgt","frt_median_hrs":"FRT (h)","tickets_handled":"Tickets",
                "priority":"Priority","root_cause":"Root cause",
            }
            disp = agent_df[[c for c in COLS if c in agent_df.columns]].rename(columns=COLS)
            st.dataframe(
                disp.style
                    .applymap(color_priority, subset=["Priority"] if "Priority" in disp.columns else [])
                    .format({
                        "STAR %":  lambda x: f"{x:.1f}%" if pd.notna(x) else "—",
                        "Target":  lambda x: f"{x:.0f}%",
                        "LRR %":   lambda x: f"{x:.1f}%" if pd.notna(x) else "—",
                        "LRR tgt": lambda x: f"{x:.1f}%",
                        "FRT (h)": lambda x: f"{x:.1f}h"  if pd.notna(x) else "—",
                        "Go-live": lambda x: str(x)[:10]   if pd.notna(x) else "—",
                    }),
                use_container_width=True, height=520,
            )

            # P1 expandable detail cards — includes Mayday article when available
            if "priority" in agent_df.columns:
                p1 = agent_df[agent_df["priority"]=="P1"]
                if not p1.empty:
                    st.markdown("#### 🔴 P1 Agent Details")
                    for _, row in p1.iterrows():
                        with st.expander(
                            f"🔴 {row['agent_name']} — {row.get('root_cause','—')} "
                            f"— W{row['tenure_week']} · {row['site']}"
                        ):
                            mc1,mc2,mc3 = st.columns(3)
                            mc1.metric("STAR", f"{row.get('star_pct','—')}%",
                                       f"target {row['star_target']:.0f}%")
                            mc2.metric("LRR",  f"{row.get('lrr_pct','—')}%",
                                       f"target {row['lrr_target']:.1f}%")
                            mc3.metric("Weeks repeated", str(row.get("weeks_repeated","—")))

                            if row.get("explanation_text"):
                                st.error(f"**What went wrong:** {row['explanation_text']}")
                            if row.get("recommended_intervention"):
                                st.success(f"**Recommended action:** {row['recommended_intervention']}")

                            # Mayday article — written by Dust agent via MaydayKBNavigator
                            # Only shown for Process Compliance failures
                            title   = row.get("mayday_article_title")
                            url     = row.get("mayday_article_url")
                            steps   = row.get("mayday_article_steps")
                            missed  = row.get("mayday_article_missed_step")
                            if title and steps:
                                with st.expander(f"📖 Mayday — {title}"):
                                    if missed:
                                        st.warning(f"**Step missed by agent:** {missed}")
                                    st.code(steps, language=None)
                                    if url:
                                        st.markdown(f"[Open in Mayday ↗]({url})")
                            elif row.get("root_cause") == "Process Compliance":
                                st.caption(
                                    "Mayday article not yet fetched — "
                                    "will populate on next Monday agent run "
                                    "once MaydayKBNavigator sub-agent is connected.")

        else:  # Cohort view
            st.caption("NH onboarding cohorts · go-live week + site")
            agg = agent_df.groupby("cohort").agg(
                agents     =("agent_id","count"),
                avg_star   =("star_pct","mean"),
                avg_lrr    =("lrr_pct","mean"),
                min_tenure =("tenure_week","min"),
                max_tenure =("tenure_week","max"),
                site       =("site","first"),
                bpo        =("bpo","first"),
                market     =("market","first"),
            ).reset_index()
            agg["star_target"] = agg["min_tenure"].apply(lambda w: get_benchmark(w,"star"))
            agg["lrr_target"]  = agg["min_tenure"].apply(lambda w: get_benchmark(w,"lrr"))
            agg["STAR"] = agg.apply(lambda r: rag_emoji(rag_star(r["avg_star"],r["star_target"])),axis=1)
            agg["LRR"]  = agg.apply(lambda r: rag_emoji(rag_lrr(r["avg_lrr"], r["lrr_target"])), axis=1)
            st.dataframe(
                agg[["cohort","agents","site","bpo","market","min_tenure","max_tenure",
                     "avg_star","star_target","STAR","avg_lrr","lrr_target","LRR"]]
                   .rename(columns={"cohort":"Cohort","agents":"Agents","min_tenure":"Min W",
                                    "max_tenure":"Max W","avg_star":"STAR %","avg_lrr":"LRR %"}),
                use_container_width=True,
            )

    # ── TAB 2 — LEARNING CURVES ───────────────────────────────────────────────
    with tab2:
        st.markdown("#### NH STAR — Weekly actual vs. Fast Track benchmark")
        if not star_df.empty:
            nh_ids  = tenure_df[tenure_df["seniority"]=="NEW_HIRE"]["agent_id"]
            nh_star = (star_df[star_df["agent_id"].isin(nh_ids)]
                       .merge(tenure_df[["agent_id","market"]], on="agent_id", how="left"))
            weekly  = nh_star.groupby(["week_start","market"])["star_pct"].mean().reset_index()
            fig = px.line(weekly, x="week_start", y="star_pct", color="market",
                          color_discrete_map={"NA":COLORS["blue"],"EU":COLORS["purple"],
                                              "AP":COLORS["amber"]},
                          labels={"star_pct":"STAR %","week_start":"Week"})
            fig.add_hline(y=80, line_dash="dot", line_color=COLORS["red"],
                          annotation_text="W9+ target 80%")
            fig.update_yaxes(range=[40,105])
            fig.update_layout(height=360, margin=dict(t=30,b=20))
            st.plotly_chart(fig, use_container_width=True)
        bench_df = pd.DataFrame([
            {"Week":f"W{w}","STAR":f"{v['star']}%","LRR":f"{v['lrr']}%","AHT":f"{v['aht']} min"}
            for w,v in BENCHMARKS.items()
        ])
        st.caption("Fast Track benchmarks · W1 = go-live · W9+ = Tenured")
        st.dataframe(bench_df, use_container_width=True, hide_index=True)

    # ── TAB 3 — AHT ───────────────────────────────────────────────────────────
    with tab3:
        st.caption("Group-level · `CCBM_PERFORMANCE` · Per-agent AHT pending UNIVERS_ZENDESK access")
        if not aht_df.empty:
            fig2 = px.line(
                aht_df[aht_df["AGENT_GROUP"]=="Other Agents"].sort_values("WEEK_START"),
                x="WEEK_START", y="avg_aht_mins", color="MARKETPLACE",
                labels={"avg_aht_mins":"AHT (min)","WEEK_START":"Week"})
            fig2.add_hline(y=21, line_dash="dot", line_color=COLORS["red"],
                           annotation_text="Target 21 min")
            fig2.update_layout(height=360, margin=dict(t=30,b=20))
            st.plotly_chart(fig2, use_container_width=True)
            st.dataframe(
                aht_df[["WEEK_START","MARKETPLACE","AGENT_GROUP",
                         "avg_aht_mins","contacts_solved"]].head(40),
                use_container_width=True)

    # ── TAB 4 — TNA FLAGS ─────────────────────────────────────────────────────
    with tab4:
        st.markdown("#### Training Needs Agent — Weekly Output")
        st.caption(
            "Written by Dust agent every Monday 08:00 CET · "
            "`data-champions-prod-230414.training_needs.training_flags` · "
            "Mayday articles fetched by MaydayKBNavigator sub-agent"
        )
        if flags_df.empty:
            st.warning(
                "No flags yet. Run `training_flags_schema.sql` in BigQuery "
                "before the first Monday agent run.")
            return

        pc = flags_df["priority"].value_counts()
        fc1,fc2,fc3,fc4 = st.columns(4)
        fc1.metric("🚨 P0", pc.get("P0",0))
        fc2.metric("🔴 P1", pc.get("P1",0))
        fc3.metric("🟡 P2", pc.get("P2",0))
        fc4.metric("✅ P3", pc.get("P3",0))

        pf = st.multiselect("Show priorities", ["P0","P1","P2","P3"],
                            default=["P0","P1","P2"])
        for _, row in flags_df[flags_df["priority"].isin(pf)].iterrows():
            em = PRIORITY_EMOJI.get(str(row.get("priority")),"⚪")
            with st.expander(
                f"{em} {row['agent_name']} — {row.get('root_cause','—')} "
                f"— {row.get('site','—')} · W{row.get('tenure_week','?')} "
                f"· {row.get('pipeline_week','?')}"
            ):
                dc1,dc2,dc3,dc4 = st.columns(4)
                dc1.metric("STAR",           f"{row.get('star_actual','—')}%")
                dc2.metric("LRR",            f"{row.get('lrr_actual','—')}%")
                dc3.metric("QA Score",       str(row.get("qa_score","—")))
                dc4.metric("Weeks repeated", str(row.get("weeks_repeated",1)))

                if row.get("explanation_text"):
                    st.error(f"**What went wrong:** {row['explanation_text']}")
                if row.get("recommended_intervention"):
                    st.success(f"**Recommended action:** {row['recommended_intervention']}")

                title  = row.get("mayday_article_title")
                url    = row.get("mayday_article_url")
                steps  = row.get("mayday_article_steps")
                missed = row.get("mayday_article_missed_step")
                if title and steps:
                    with st.expander(f"📖 Mayday — {title}"):
                        if missed:
                            st.warning(f"**Step missed by agent:** {missed}")
                        st.code(steps, language=None)
                        if url:
                            st.markdown(f"[Open in Mayday ↗]({url})")


if __name__ == "__main__":
    main()

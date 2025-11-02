import os
import requests
import streamlit as st
import pandas as pd
import plotly.express as px
from dotenv import load_dotenv

# load environment variables from .env into os.env
load_dotenv()

# Robustly obtain API_BASE from environment or .env (strip surrounding quotes if present)
_api_base_raw = os.getenv("API_BASE")
if not _api_base_raw:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    if not line or line.strip().startswith("#"):
                        continue
                    if line.strip().startswith("API_BASE"):
                        _, v = line.split("=", 1)
                        _api_base_raw = v.strip()
                        break
        except Exception:
            _api_base_raw = None

# strip optional surrounding quotes and whitespace
if isinstance(_api_base_raw, str):
    API_BASE = _api_base_raw.strip()
    if (API_BASE.startswith('"') and API_BASE.endswith('"')) or (API_BASE.startswith("'") and API_BASE.endswith("'")):
        API_BASE = API_BASE[1:-1].strip()
else:
    API_BASE = "http://localhost:8000"

API_URL = API_BASE.rstrip("/") + "/mgnrega/all"
HEALTH_URL = API_BASE.rstrip("/") + "/mgnrega/health"

# Compatibility helper: safe rerun (some Streamlit versions don't expose experimental_rerun)
def _safe_rerun():
    try:
        if hasattr(st, "experimental_rerun"):
            st.experimental_rerun()
        else:
            st.warning("Please refresh the browser page to retry (automatic rerun not supported by this Streamlit version).")
            st.stop()
    except Exception:
        st.warning("Please refresh the browser page to retry.")
        st.stop()

# Quick health check to fail fast and show useful diagnostics
try:
    hresp = requests.get(HEALTH_URL, timeout=5)
    hresp.raise_for_status()
    _health_ok = True
except Exception as _e:
    _health_ok = False
    st.error(f"Backend health check failed for {HEALTH_URL}: {_e}")
    if st.button("Retry health check"):
        _safe_rerun()
    st.stop()

# NOTE: we intentionally do NOT display the backend URL in the UI for security/cleanliness

st.set_page_config(layout="wide", page_title="MGNREGA Dashboard")
st.title("MGNREGA District / State Dashboard")

# NOTE: KPI calculation location
# - Currently KPIs are calculated on the backend in the /mgnrega/all route and returned
#   under the 'kpis' key. This keeps the frontend thin and fast.
# - If you prefer frontend calculations, set `compute_kpis_in_frontend = True` and
#   implement the computations below (they will operate on the returned raw rows).
compute_kpis_in_frontend = False

# Cached fetch to avoid repeated network calls on every Streamlit interaction
@st.cache_data(ttl=1800)
def fetch_payload(api_url: str):
    """Fetch payload from backend and cache it for 30 minutes.
    Caching prevents new network requests on widget interactions (e.g. selector changes).
    """
    resp = requests.get(api_url, timeout=1000)
    resp.raise_for_status()
    return resp.json()

# UI control to force-clear the cached payload and reload
if st.sidebar.button("Force refresh data"):
    try:
        st.cache_data.clear()
    except Exception:
        pass
    _safe_rerun()

# Load data using cached fetch
with st.spinner("Loading data from backend..."):
    try:
        payload = fetch_payload(API_URL)
    except Exception as e:
        st.error(f"Failed to load data from backend at {API_URL}: {e}")
        if st.button("Force refresh / retry"):
            try:
                st.cache_data.clear()
            except Exception:
                pass
            _safe_rerun()
        st.stop()

states = payload.get("states", [])
districts = payload.get("districts", [])
mgnrega_rows = payload.get("mgnrega_data", [])
kpis = payload.get("kpis") or {}

# Convert to DataFrames for easier handling
states_df = pd.DataFrame(states) if states else pd.DataFrame(columns=["id", "state_name", "state_code"])
districts_df = pd.DataFrame(districts) if districts else pd.DataFrame(columns=["id", "district_name", "district_code", "state_id"])
m_df = pd.DataFrame(mgnrega_rows) if mgnrega_rows else pd.DataFrame()

# Sidebar selection
st.sidebar.header("Filters")
state_options = ["All"] + (states_df["state_name"].tolist() if not states_df.empty else [])
selected_state = st.sidebar.selectbox("Select state", state_options, index=0)

# Show a district selector filtered by state if selected
if selected_state != "All" and not districts_df.empty:
    sid = states_df.loc[states_df["state_name"] == selected_state, "id"].squeeze()
    filtered_districts = districts_df[districts_df["state_id"] == int(sid)] if sid is not None else pd.DataFrame()
    district_options = ["All"] + filtered_districts["district_name"].tolist()
else:
    district_options = ["All"] + (districts_df["district_name"].tolist() if not districts_df.empty else [])

selected_district = st.sidebar.selectbox("Select district", district_options, index=0)

# Enforce district-centric UX: do not render dashboard until a district is selected
if selected_district == "All":
    st.sidebar.info("This dashboard is district-centric. Please select a district to view data.")
    # stop further rendering — sidebar (selectors) remains visible
    st.stop()

# Helper to filter mgnrega dataframe
def filter_data(df, state_name, district_name):
    if df.empty:
        return df
    if district_name and district_name != "All":
        return df[df["district_name"] == district_name]
    if state_name and state_name != "All":
        return df[df["state_name"] == state_name]
    return df

view_df = filter_data(m_df, selected_state, selected_district)

# KPI source note
if compute_kpis_in_frontend:
    st.info("KPIs will be calculated in the frontend. Currently this is disabled — backend KPIs are used when available.")
else:
    pass

# ------------------
# District / State overview cards
# ------------------
st.header("Overview")
col1, col2, col3, col4 = st.columns(4)

def format_num(x):
    try:
        if pd.isna(x):
            return "—"
        if isinstance(x, float) and x.is_integer():
            x = int(x)
        return f"{x:,}"
    except Exception:
        return str(x)

# Use backend per-state aggregates if present and state is selected
backend_state_map = {s["state_name"]: s for s in (kpis.get("by_state") or [])}

if selected_state != "All" and selected_state in backend_state_map:
    state_stats = backend_state_map[selected_state]
else:
    # If a specific district is selected, show the district's own values (no aggregation)
    if not view_df.empty and selected_district != "All":
        # prefer the most recent record for the district if multiple exist
        try:
            dr = view_df.sort_values("data_fetched_on", ascending=False).iloc[0]
        except Exception:
            dr = view_df.iloc[0]
        state_stats = {
            "approved_labour_budget": int(dr.get("approved_labour_budget") or 0),
            "total_expenditure": float(dr.get("total_exp") or 0),
            "avg_wage_rate": float(dr.get("average_wage_rate_per_day_per_person") or 0),
            "avg_days_of_employment_per_household": float(dr.get("average_days_of_employment_per_household") or 0),
            "total_households_worked": int(dr.get("total_households_worked") or 0),
            "percent_utilization": None,
        }
        try:
            if state_stats["approved_labour_budget"]:
                state_stats["percent_utilization"] = (
                    float(state_stats["total_expenditure"]) / float(state_stats["approved_labour_budget"]) * 100
                )
        except Exception:
            state_stats["percent_utilization"] = None
    else:
        # fallback: compute simple aggregates from view_df (for state-level view)
        agg = {}
        agg["approved_labour_budget"] = int(view_df["approved_labour_budget"].sum()) if not view_df.empty else 0
        agg["total_expenditure"] = float(view_df["total_exp"].sum()) if not view_df.empty else 0
        agg["avg_wage_rate"] = float(view_df["average_wage_rate_per_day_per_person"].mean()) if not view_df.empty else 0
        agg["avg_days_of_employment_per_household"] = float(view_df["average_days_of_employment_per_household"].mean()) if not view_df.empty else 0
        agg["total_households_worked"] = int(view_df["total_households_worked"].sum()) if not view_df.empty else 0
        agg["percent_utilization"] = None
        if agg["approved_labour_budget"]:
            try:
                agg["percent_utilization"] = float(agg["total_expenditure"]) / float(agg["approved_labour_budget"]) * 100
            except Exception:
                agg["percent_utilization"] = None
        state_stats = agg

col1.metric("Approved Labour Budget", format_num(state_stats.get("approved_labour_budget")))
col2.metric("Total Expenditure", format_num(state_stats.get("total_expenditure")))
col3.metric("Avg Wage Rate (per day)", f"{state_stats.get('avg_wage_rate'):.2f}" if state_stats.get('avg_wage_rate') is not None else "—")
col4.metric("Avg Days of Employment / HH", f"{state_stats.get('avg_days_of_employment_per_household'):.2f}" if state_stats.get('avg_days_of_employment_per_household') is not None else "—")

# percent utilization progress bar / circular gauge
pct = state_stats.get("percent_utilization")
if pct is None:
    st.progress(0)
    st.write("% Utilization: —")
else:
    st.progress(min(max(int(pct), 0), 100))
    st.write(f"% Utilization: {pct:.2f}%")

# ------------------
# Employment composition
# ------------------
st.header("Employment composition")

# Prepare numbers
total_persondays = int(view_df["persondays_of_central_liability_so_far"].sum()) if not view_df.empty else 0
sc = int(view_df["sc_persondays"].sum()) if not view_df.empty else 0
st_ = int(view_df["st_persondays"].sum()) if not view_df.empty else 0
women = int(view_df["women_persondays"].sum()) if not view_df.empty else 0
other = max(total_persondays - sc - st_ , 0)
other_for_women = max(total_persondays - women, 0)

col1, col2, col3 = st.columns(3)
with col1:
    st.subheader("SC / ST / Other persondays")
    pc_df = pd.DataFrame({"category": ["SC", "ST", "Other"], "persondays": [sc, st_, other]})
    fig = px.pie(pc_df, names="category", values="persondays", hole=0.35)
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Women persondays vs Other")
    pc2 = pd.DataFrame({"category": ["Women", "Other"], "persondays": [women, other_for_women]})
    fig2 = px.pie(pc2, names="category", values="persondays", hole=0.35)
    st.plotly_chart(fig2, use_container_width=True)

with col3:
    st.subheader("Active workers vs Households")
    active_workers = int(view_df["total_num_of_active_workers"].sum()) if not view_df.empty else 0
    households = int(view_df["total_households_worked"].sum()) if not view_df.empty else 0
    bar_df = pd.DataFrame({"metric": ["Active workers", "Households"], "count": [active_workers, households]})
    fig3 = px.bar(bar_df, x="metric", y="count", text="count")
    st.plotly_chart(fig3, use_container_width=True)

# ------------------
# Work progress
# ------------------
st.header("Work progress / status")
col1, col2 = st.columns(2)

completed = int(view_df["number_of_completed_works"].sum()) if not view_df.empty else 0
ongoing = int(view_df["number_of_ongoing_works"].sum()) if not view_df.empty else 0
pct_cat_b = float(view_df["percent_of_category_B_works"].mean()) if not view_df.empty else 0
pct_agri = float(view_df["percentage_of_expenditure_on_agriculture_allied_works"].mean()) if not view_df.empty else 0
pct_nrm = float(view_df["percent_of_NRM_expenditure"].mean()) if not view_df.empty else 0

with col1:
    st.subheader("Counts: Completed vs Ongoing")
    cnt_df = pd.DataFrame({"status": ["Completed", "Ongoing"], "count": [completed, ongoing]})
    figc = px.pie(cnt_df, names="status", values="count", hole=0.4)
    st.plotly_chart(figc, use_container_width=True)

with col2:
    st.subheader("Category B / Agri allied / NRM (percent)")
    bc_df = pd.DataFrame({"metric": ["Category B %", "Agri allied %", "NRM %"], "value": [pct_cat_b, pct_agri, pct_nrm]})
    figb = px.bar(bc_df, x="metric", y="value", text="value")
    st.plotly_chart(figb, use_container_width=True)

# ------------------
# Financial performance
# ------------------
st.header("Financial performance")
col1, col2, col3 = st.columns(3)

wages = float(view_df["wages"].sum()) if not view_df.empty else 0
material = float(view_df["material_and_skilled_wages"].sum()) if not view_df.empty else 0
pct_payments = float(view_df["percentage_payments_generated_within_15_days"].mean()) if not view_df.empty else 0
nil_gps = int(view_df["number_of_gp_with_nil_exp"].sum()) if not view_df.empty else 0
avg_cost_per_work = None
try:
    if (completed + ongoing) > 0:
        avg_cost_per_work = float(view_df["total_exp"].sum()) / max(completed + ongoing, 1)
except Exception:
    avg_cost_per_work = None

with col1:
    st.subheader("Wage vs Material expenditure")
    fm = pd.DataFrame({"category": ["Wages", "Material"], "amount": [wages, material]})
    figf = px.pie(fm, names="category", values="amount", hole=0.4)
    st.plotly_chart(figf, use_container_width=True)

with col2:
    st.subheader("% Payments generated within 15 days")
    st.progress(min(max(int(pct_payments), 0), 100))
    st.write(f"{pct_payments:.2f}%")

with col3:
    st.subheader("NIL GPs / Avg cost per work")
    st.metric("GPs with NIL expenditure", format_num(nil_gps))
    st.metric("Avg cost per work", f"{avg_cost_per_work:.2f}" if avg_cost_per_work is not None else "—")

# ------------------
# KPIs section (improved layout)
# ------------------
st.header("Key Performance Indicators (KPIs)")

if kpis:
    overall = kpis.get("overall", {})
    # compute fallback values from data when backend doesn't provide them
    try:
        fem = overall.get("female_participation_rate")
        if fem is None and not view_df.empty:
            fem = (float(view_df["women_persondays"].sum()) / float(view_df["persondays_of_central_liability_so_far"].sum())) * 100
    except Exception:
        fem = None

    try:
        scst = overall.get("sc_st_participation_rate")
        if scst is None and not view_df.empty:
            scst = (float(view_df["sc_persondays"].sum() + view_df["st_persondays"].sum()) / float(view_df["persondays_of_central_liability_so_far"].sum())) * 100
    except Exception:
        scst = None

    tpr = overall.get("average_percentage_payments_within_15_days")
    if tpr is None and not view_df.empty:
        try:
            tpr = float(view_df["percentage_payments_generated_within_15_days"].mean())
        except Exception:
            tpr = None

    # Work completion ratio
    try:
        completed = int(view_df["number_of_completed_works"].sum()) if not view_df.empty else 0
        ongoing = int(view_df["number_of_ongoing_works"].sum()) if not view_df.empty else 0
        wcr = (completed / (completed + ongoing) * 100) if (completed + ongoing) > 0 else None
    except Exception:
        wcr = None

    # Budget utilization
    bud_pct = overall.get("percent_utilization")

    # Top row: KPIs as cards
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Budget utilization (%)", f"{bud_pct:.2f}%" if bud_pct is not None else "—")
    k2.metric("Female participation (%)", f"{fem:.2f}%" if fem is not None else "—")
    k3.metric("SC/ST participation (%)", f"{scst:.2f}%" if scst is not None else "—")
    k4.metric("Timely payment rate (%)", f"{tpr:.2f}%" if tpr is not None else "—")
    k5.metric("Work completion ratio (%)", f"{wcr:.2f}%" if wcr is not None else "—")

    # Second row: progress bars for the percentage KPIs (visual)
    p1, p2, p3, p4, p5 = st.columns(5)
    def _pct(v):
        try:
            return max(0, min(100, int(round(float(v)))))
        except Exception:
            return 0

    p1.progress(_pct(bud_pct) if bud_pct is not None else 0)
    p1.caption("Budget used")

    p2.progress(_pct(fem) if fem is not None else 0)
    p2.caption("Female participation")

    p3.progress(_pct(scst) if scst is not None else 0)
    p3.caption("SC/ST participation")

    p4.progress(_pct(tpr) if tpr is not None else 0)
    p4.caption("Timely payments within 15 days")

    p5.progress(_pct(wcr) if wcr is not None else 0)
    p5.caption("Work completion")

    # Small notes line
    st.caption("Values shown use backend-calculated KPIs when available; otherwise computed from the selected district's data.")
else:
    st.warning("No backend KPIs available; compute in frontend or run the backend KPI endpoint.")

# Footer / data preview
with st.expander("Raw data preview"):
    st.subheader("mgnrega_data (preview)")
    st.dataframe(view_df.head(200))


# End of dashboard

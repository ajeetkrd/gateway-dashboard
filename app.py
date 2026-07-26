"""
Claude Apps Gateway - Users & Spend dashboard.

Runs as a container on the gateway's Docker network and reads the gateway's
Postgres directly (host "postgres:5432", db "gateway", user/pass gw/gw).

Schema this app is built for (confirmed on the live instance):

  spend(principal text, period text, cents double precision, updated_at timestamptz)
      PK (principal, period). `cents` is money in cents. `period` encodes the
      window AND its granularity by format:
        YYYY-MM      -> monthly   (e.g. 2026-07)
        YYYY-Www     -> weekly    (e.g. 2026-W30)
        YYYY-MM-DD   -> daily     (e.g. 2026-07-22)

  principal_emails(principal text PK, email text, name text, groups jsonb, updated_at)

  spend_limits(id, scope_type, scope_id, amount bigint, period, currency, ...)
      scope_type in (user, rbac_group, organization). `amount` is a cap in cents.

All money is displayed in USD ($ = cents / 100).
"""

import os
from datetime import datetime

import pandas as pd
import psycopg2
import streamlit as st

DB_HOST = os.getenv("PGHOST", "postgres")
DB_PORT = int(os.getenv("PGPORT", "5432"))
DB_USER = os.getenv("PGUSER", "gw")
DB_PASSWORD = os.getenv("PGPASSWORD", "gw")
DB_NAME = os.getenv("PGDATABASE", "gateway")

st.set_page_config(page_title="Gateway — Users & Spend", page_icon="📊", layout="wide")


# ----------------------------------------------------------------------------
# DB access
# ----------------------------------------------------------------------------
@st.cache_resource
def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, dbname=DB_NAME
    )


def run_df(sql, params=None):
    try:
        return pd.read_sql_query(sql, get_conn(), params=params)
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        get_conn.clear()
        return pd.read_sql_query(sql, get_conn(), params=params)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def granularity(period: str) -> str:
    """Classify a period string into daily / weekly / monthly."""
    if not isinstance(period, str):
        return "unknown"
    if "-W" in period:
        return "weekly"
    parts = period.split("-")
    if len(parts) == 3:
        return "daily"
    if len(parts) == 2:
        return "monthly"
    return "unknown"


def usd(cents):
    try:
        return f"${cents / 100:,.2f}"
    except Exception:  # noqa: BLE001
        return "—"


st.title("Claude Apps Gateway — Users & Spend")
st.caption(
    f"Connected to {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME} · "
    f"loaded {datetime.now():%Y-%m-%d %H:%M:%S} · all amounts in USD"
)

# Pull the core tables once.
try:
    spend = run_df(
        "SELECT principal, period, cents, updated_at FROM spend ORDER BY cents DESC"
    )
    emails = run_df("SELECT principal, email, name, groups, updated_at FROM principal_emails")
    limits = run_df(
        "SELECT id, scope_type, scope_id, amount, period, currency, created_by, updated_at "
        "FROM spend_limits ORDER BY scope_type, scope_id"
    )
except Exception as e:  # noqa: BLE001
    st.error(f"Could not read from the database: {e}")
    st.stop()

# Enrich spend with dollars, granularity, and identity.
spend["usd"] = spend["cents"] / 100.0
spend["granularity"] = spend["period"].map(granularity)
id_map = emails.set_index("principal")[["email", "name"]] if not emails.empty else pd.DataFrame()
spend = spend.merge(
    emails[["principal", "email", "name"]], on="principal", how="left"
)
spend["display"] = spend["email"].fillna(spend["name"]).fillna(spend["principal"])

overview_tab, users_tab, spend_tab, limits_tab = st.tabs(
    ["Overview", "Users", "Spend detail", "Limits & usage"]
)

# ----- Overview -------------------------------------------------------------
with overview_tab:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Users (principals)", len(emails))
    c2.metric("Monthly spend (all)", usd(spend.loc[spend["granularity"] == "monthly", "cents"].sum()))
    c3.metric("Weekly spend (all)", usd(spend.loc[spend["granularity"] == "weekly", "cents"].sum()))
    c4.metric("Daily spend (all)", usd(spend.loc[spend["granularity"] == "daily", "cents"].sum()))

    st.caption(
        "Note: monthly/weekly/daily totals overlap — they are the same underlying "
        "usage bucketed into different windows, not additive."
    )
    st.divider()

    st.subheader("Spend by granularity")
    by_gran = (
        spend.groupby("granularity", as_index=False)["usd"]
        .sum()
        .sort_values("usd", ascending=False)
    )
    st.dataframe(
        by_gran.assign(amount=by_gran["usd"].map(lambda v: f"${v:,.2f}"))[["granularity", "amount"]],
        use_container_width=True,
        hide_index=True,
    )

# ----- Users ----------------------------------------------------------------
with users_tab:
    st.subheader("Spend per user")
    gran_choice = st.radio(
        "Period granularity", ["monthly", "weekly", "daily"], horizontal=True
    )
    view = spend[spend["granularity"] == gran_choice].copy()

    if view.empty:
        st.info(f"No {gran_choice} spend recorded yet.")
    else:
        windows = sorted(view["period"].unique(), reverse=True)
        window = st.selectbox("Window", windows)
        view = view[view["period"] == window]

        table = (
            view.groupby(["display", "principal"], as_index=False)
            .agg(spend_usd=("usd", "sum"))
            .sort_values("spend_usd", ascending=False)
        )
        table["spend"] = table["spend_usd"].map(lambda v: f"${v:,.2f}")

        st.dataframe(
            table[["display", "spend", "principal"]].rename(
                columns={"display": "user", "principal": "principal_id"}
            ),
            use_container_width=True,
            hide_index=True,
        )
        st.bar_chart(table.set_index("display")["spend_usd"])

    st.divider()
    st.subheader("All known users")
    show_emails = emails.copy()
    show_emails["groups"] = show_emails["groups"].astype(str)
    st.dataframe(show_emails, use_container_width=True, hide_index=True)

# ----- Spend detail ---------------------------------------------------------
with spend_tab:
    st.subheader("Raw spend rows")
    detail = spend[["display", "principal", "period", "granularity", "usd", "updated_at"]].copy()
    detail["amount"] = detail["usd"].map(lambda v: f"${v:,.2f}")
    st.dataframe(
        detail[["display", "principal", "period", "granularity", "amount", "updated_at"]].rename(
            columns={"display": "user"}
        ),
        use_container_width=True,
        hide_index=True,
    )

# ----- Limits & usage -------------------------------------------------------
with limits_tab:
    st.subheader("Configured spend limits vs. usage")
    if limits.empty:
        st.info("No spend limits configured.")
    else:
        lim = limits.copy()
        lim["limit_usd"] = lim["amount"] / 100.0

        rows = []
        for _, r in lim.iterrows():
            scope_type, scope_id, period = r["scope_type"], r["scope_id"], r["period"]

            # Match spend rows of the same granularity as the limit's period.
            same_gran = spend[spend["granularity"] == period]

            if scope_type == "organization":
                used = same_gran["usd"].sum()
                scope_label = "(entire organization)"
            elif scope_type == "user":
                used = same_gran.loc[same_gran["principal"] == scope_id, "usd"].sum()
                scope_label = scope_id
            elif scope_type == "rbac_group":
                # groups is jsonb array of group names on principal_emails
                def in_group(g):
                    try:
                        return scope_id in (g or [])
                    except Exception:  # noqa: BLE001
                        return False

                members = emails.loc[emails["groups"].map(in_group), "principal"]
                used = same_gran.loc[same_gran["principal"].isin(members), "usd"].sum()
                scope_label = f"group: {scope_id}"
            else:
                used = 0.0
                scope_label = scope_id

            limit_usd = r["limit_usd"]
            pct = (used / limit_usd * 100) if limit_usd else 0
            rows.append(
                {
                    "scope": f"{scope_type} {scope_label}",
                    "period": period,
                    "used": f"${used:,.2f}",
                    "limit": f"${limit_usd:,.2f}",
                    "used_pct": round(pct, 1),
                }
            )

        summary = pd.DataFrame(rows)
        st.dataframe(
            summary,
            use_container_width=True,
            hide_index=True,
            column_config={
                "used_pct": st.column_config.ProgressColumn(
                    "% of limit used", min_value=0, max_value=100, format="%.1f%%"
                )
            },
        )
        st.caption(
            "Usage is matched to each limit's granularity (daily/weekly/monthly) and, "
            "for group/org scopes, summed across the relevant principals across all "
            "windows of that granularity present in the table."
        )

    st.divider()
    st.subheader("Raw limit rows")
    raw = limits.copy()
    raw["amount_usd"] = raw["amount"].map(usd)
    st.dataframe(raw, use_container_width=True, hide_index=True)

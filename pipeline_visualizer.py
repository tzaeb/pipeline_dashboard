import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import base64
import os
import yaml


def load_config():
    try:
        with open("config.yml", "r") as file:
            return yaml.safe_load(file)
    except FileNotFoundError:
        st.error("config.yml not found. Please create it with the required fields.")
        return {}

config = load_config()
ORGANIZATION = config.get("organization")
PROJECT = config.get("project")
PAT = config.get("pat", os.environ.get("AZURE_PAT", ""))
PIPELINES = config.get("pipelines")
DEFAULT_PIPELINE = config.get("default_pipeline")
BUILD_FILTERS = config.get("build_filters", {})
MAX_BUILDS_OPTION = config.get("max_builds_option")

def get_auth_header(pat):
    token = base64.b64encode(f":{pat}".encode()).decode()
    return {"Authorization": f"Basic {token}"}

# Accepts an optional max_builds parameter to limit the number of builds returned.
@st.cache_data(ttl=3600)
def get_builds_for_pipeline(pipeline_id, max_builds=None):
    base_url = f"https://dev.azure.com/{ORGANIZATION}/{PROJECT}/_apis/build/builds?definitions={pipeline_id}"
    if max_builds is not None:
        base_url += f"&maxBuildsPerDefinition={max_builds}"
    url = base_url + "&api-version=7.1-preview.7"
    headers = get_auth_header(PAT)
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        builds = response.json().get("value", [])
        return [{
            "id": build["id"],
            "buildNumber": build.get("buildNumber", "N/A"),
            "startTime": build.get("startTime", ""),
            "description": f"#{build.get('buildNumber', 'N/A')} • {build.get('reason', 'Manual').capitalize()} ({build.get('sourceBranch', 'Unknown Branch')})",
            "link": f"https://dev.azure.com/{ORGANIZATION}/{PROJECT}/_build/results?buildId={build['id']}"
        } for build in builds]
    else:
        st.error(f"Error fetching builds for pipeline {pipeline_id}: {response.status_code} - {response.text}")
        return []

# Updated URL using "vstmr.dev.azure.com"
@st.cache_data(ttl=3600)
def get_aggregated_test_results(build_id):
    url = f"https://vstmr.dev.azure.com/{ORGANIZATION}/{PROJECT}/_apis/testresults/resultsbybuild?buildId={build_id}&api-version=7.1-preview.1"
    headers = get_auth_header(PAT)
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        results = response.json()
        if isinstance(results, dict) and "value" in results:
            results = results["value"]
        passed = sum(1 for result in results if result.get("outcome", "").lower() == "passed")
        failed = sum(1 for result in results if result.get("outcome", "").lower() == "failed")
        total = len(results)
        return {"passed": passed, "failed": failed, "total": total}
    st.warning(f"Failed to fetch aggregated test results for build {build_id}: {response.status_code}")
    return {"passed": 0, "failed": 0, "total": 0}

def process_data(builds):
    data = []
    for build in builds:
        test_results = get_aggregated_test_results(build["id"])
        total = test_results["total"]
        passed = test_results["passed"]
        failed = test_results["failed"]
        timestamp = build["startTime"]
        pass_rate = round((passed / total * 100), 2) if total > 0 else 0
        fail_rate = round((failed / total * 100), 2) if total > 0 else 0
        data.append({
            "Datetime": timestamp,
            "Build": build["buildNumber"],
            "Passed": passed,
            "Failed": failed,
            "Total": total,
            "Pass Rate (%)": pass_rate,
            "Fail Rate (%)": fail_rate,
            "Link": build["link"]
        })
    df = pd.DataFrame(data)
    if not df.empty:
        df["Datetime"] = pd.to_datetime(df["Datetime"])
    return df

st.set_page_config(layout="wide")
st.title("Azure Pipelines Dashboard")

with st.sidebar:
    st.header("Filters")
    if PIPELINES and isinstance(PIPELINES, dict):
        pipeline_options = {name: id for name, id in PIPELINES.items()}
        default_name = next((name for name, id in pipeline_options.items() if id == DEFAULT_PIPELINE),
                            list(pipeline_options.keys())[0])
        selected_pipeline_name = st.selectbox("Select Pipeline", list(pipeline_options.keys()),
                                              index=list(pipeline_options.keys()).index(default_name))
        selected_pipeline_id = pipeline_options[selected_pipeline_name]
    else:
        st.error("No pipeline configuration found in config.yml.")
        st.stop()
    
    # Optional filter by build substring.
    selected_build_filter = st.selectbox("Custom builds filter", ["None"] + list(BUILD_FILTERS.keys()))
      
    # Always show the build count selection.
    build_labels = [f"Last {cnt} builds" for cnt in MAX_BUILDS_OPTION]
    default_build_index = 0  # Adjust default as needed.
    selected_build_label = st.selectbox("Select max number of builds", options=build_labels, index=default_build_index)
    selected_build_value = MAX_BUILDS_OPTION[build_labels.index(selected_build_label)]

    # Toggle for x-axis ("Date" or "Build")
    x_axis_option = st.radio("Chart display type (x-axis)", options=["Date", "Build"], index=1)    

    if st.button("Clear Cache"):
        get_builds_for_pipeline.clear()
        get_aggregated_test_results.clear()
        st.session_state.force_refresh = True
    if st.session_state.get("force_refresh"):
        st.write("Data refreshed! Please reload the page to see the latest data.")
        st.session_state.force_refresh = False

# Always apply the build count limit when fetching builds.
builds = get_builds_for_pipeline(selected_pipeline_id, max_builds=selected_build_value)

if selected_build_filter != "None":
    filter_str = BUILD_FILTERS[selected_build_filter]
    builds = [build for build in builds if filter_str in build["buildNumber"]]

if builds:
    # Process the builds into a DataFrame.
    df = process_data(builds)
    
    # For the chart: if x-axis is "Build", sort chronologically (oldest to newest)
    if x_axis_option == "Build":
        df_chart = df.sort_values("Datetime", ascending=True)
    else:
        df_chart = df.copy()
    
    # For the table, show the newest builds at the top.
    df_table = df.sort_values("Datetime", ascending=False)
    
    st.subheader("Builds")
    st.dataframe(
        df_table,
        height=200,
        use_container_width=True,
        column_config={
            "Link": st.column_config.LinkColumn("Link", width="small", display_text="View")
        },
        hide_index=True
    )
    
    # Set up the x-axis for the chart.
    if x_axis_option == "Date":
        x_data = "Datetime"
    else:
        x_data = "Build"
        df_chart["Build"] = df_chart["Build"].astype(str)
    
    category_orders = {}
    if x_axis_option == "Build":
        category_orders = {"Build": df_chart[x_data].tolist()}
    
    st.subheader("Trends")
    fig = px.area(
        df_chart,
        x=x_data,
        y=["Pass Rate (%)", "Fail Rate (%)"],
        title=f"Pipeline: {selected_pipeline_name} (x-axis: {x_axis_option})",
        labels={"value": "%", "variable": "Rate", x_data: x_axis_option},
        range_y=[0, 100],
        color_discrete_map={"Pass Rate (%)": "#00CC96", "Fail Rate (%)": "#EF553B"},
        category_orders=category_orders
    )
    fig.update_traces(mode="lines+markers")
    
    if x_axis_option == "Date":
        fig.update_xaxes(tickformat="%Y-%m-%d")
    else:
        fig.update_xaxes(type="category")
    
    fig.update_layout(
        yaxis_title="Percentage (%)",
        legend_title="Rate",
        hovermode="x unified",
        height=400,
        margin=dict(l=20, r=20, t=40, b=20)
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.write(f"No build data available for pipeline {selected_pipeline_name} (ID: {selected_pipeline_id}).")

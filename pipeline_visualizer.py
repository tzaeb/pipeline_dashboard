import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import base64
import os
import yaml

# Load configuration from YAML file
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
MAX_BUILDS_PER_DEFINITION = config.get("maxBuildsPerDefinition")
PIPELINES = config.get("pipelines")
DEFAULT_PIPELINE = config.get("default_pipeline")
BUILD_FILTERS = config.get("build_filters", {})

# Encode the PAT for authentication
def get_auth_header(pat):
    token = base64.b64encode(f":{pat}".encode()).decode()
    return {"Authorization": f"Basic {token}"}

# Fetch builds for a specific pipeline (max builds per definition)
def get_builds_for_pipeline(pipeline_id):
    url = f"https://dev.azure.com/{ORGANIZATION}/{PROJECT}/_apis/build/builds?definitions={pipeline_id}&maxBuildsPerDefinition={MAX_BUILDS_PER_DEFINITION}&api-version=7.1-preview.7"
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

# Fetch aggregated test results for a specific build using the aggregated API endpoint.
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

# Process the build and aggregated test result data into a DataFrame
def process_data(builds):
    data = []
    for build in builds:
        test_results = get_aggregated_test_results(build["id"])
        total = test_results["total"]
        passed = test_results["passed"]
        failed = test_results["failed"]
        date = build["startTime"]
        pass_rate = round((passed / total * 100), 2) if total > 0 else 0
        fail_rate = round((failed / total * 100), 2) if total > 0 else 0
        data.append({
            "Date": date,
            "Build": build["buildNumber"],
            "Passed": passed,
            "Failed": failed,
            "Total": total,
            "Pass Rate (%)": pass_rate,
            "Fail Rate (%)": fail_rate,
            "Release": f"v{build['buildNumber'].split('.')[0]}.0",
            "Description": build["description"],
            "Link": build["link"]
        })
    df = pd.DataFrame(data)
    if not df.empty:
        df["Date"] = pd.to_datetime(df["Date"]).dt.date
    return df

# Streamlit App Configuration
st.set_page_config(layout="wide")
st.title("Azure Pipelines Dashboard")

# Sidebar: Pipeline selection and build filter
with st.sidebar:
    st.header("Filters")
    if PIPELINES and isinstance(PIPELINES, dict):
        pipeline_options = {name: id for name, id in PIPELINES.items()}
        default_name = next((name for name, id in pipeline_options.items() if id == DEFAULT_PIPELINE), list(pipeline_options.keys())[0])
        selected_pipeline_name = st.selectbox("Select Pipeline", list(pipeline_options.keys()), index=list(pipeline_options.keys()).index(default_name))
        selected_pipeline_id = pipeline_options[selected_pipeline_name]
    else:
        st.error("No pipeline configuration found in config.yml.")
        st.stop()

    # Create a dropdown with an initial "None" option to not exclude any builds.
    selected_build_filter = st.selectbox("Filter builds", ["None"] + list(BUILD_FILTERS.keys()))

# Main content: Fetch builds and aggregated test results
builds = get_builds_for_pipeline(selected_pipeline_id)

# Apply build name filter if one is selected
if selected_build_filter != "None":
    filter_str = BUILD_FILTERS[selected_build_filter]
    builds = [build for build in builds if filter_str in build["buildNumber"]]

if builds:
    df = process_data(builds)
    
    # Display raw test data in a table
    st.subheader("Builds")
    st.dataframe(
        df,
        height=200,
        use_container_width=True,
        column_config={
            "Link": st.column_config.LinkColumn("Link", width="small", display_text="View")
        },
        hide_index=True
    )
    
    # Visualize Pass/Fail trends with updated colors and compact layout
    st.subheader("Trends")
    fig = px.area(
        df,
        x="Date",
        y=["Pass Rate (%)", "Fail Rate (%)"],
        title=f"Pipeline: {selected_pipeline_name}",
        labels={"value": "%", "variable": "Rate"},
        range_y=[0, 100],
        color_discrete_map={"Pass Rate (%)": "#00CC96", "Fail Rate (%)": "#EF553B"}
    )
    fig.update_traces(mode="lines+markers")
    fig.update_layout(
        yaxis_title="Percentage (%)",
        legend_title="Rate",
        hovermode="x unified",
        height=350,
        margin=dict(l=20, r=20, t=40, b=20)
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.write(f"No build data available for pipeline {selected_pipeline_name} (ID: {selected_pipeline_id}).")

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
PAT = config.get("pat", os.environ.get("AZURE_PAT", ""))  # Fallback to env if not in YAML
Pipeline_id = config.get("pipelines")  # Default if not in YAML
DEFAULT_PIPELINE_ID = config.get("default_pipeline_id")

# Encode the PAT for authentication
def get_auth_header(pat):
    token = base64.b64encode(f":{pat}".encode()).decode()
    return {"Authorization": f"Basic {token}"}

# Fetch builds for a specific pipeline (max 30 results)
def get_builds_for_pipeline(pipeline_id):
    url = f"https://dev.azure.com/{ORGANIZATION}/{PROJECT}/_apis/build/builds?definitions={pipeline_id}&maxBuilds=30&api-version=7.1-preview.7"
    headers = get_auth_header(PAT)
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        builds = response.json().get("value", [])
        return [{
            "id": build["id"],
            "buildNumber": build["buildNumber"],
            "startTime": build.get("startTime", ""),
            "description": f"#{build['buildNumber']} • {build.get('reason', 'Manual').capitalize()} ({build.get('sourceBranch', 'Unknown Branch')})",
            "link": f"https://dev.azure.com/{ORGANIZATION}/{PROJECT}/_build/results?buildId={build['id']}"
        } for build in builds]
    else:
        st.error(f"Error fetching builds for pipeline {pipeline_id}: {response.status_code} - {response.text}")
        return []

# Fetch test results for a specific build
def get_test_results_for_build(build_id):
    url = f"https://dev.azure.com/{ORGANIZATION}/{PROJECT}/_apis/test/runs?buildId={build_id}&api-version=6.0"
    headers = get_auth_header(PAT)
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        test_runs = response.json().get("value", [])
        if test_runs:
            total_passed = sum(run.get("passedTests", 0) for run in test_runs)
            total_failed = sum(run.get("failedTests", 0) for run in test_runs)
            total_tests = sum(run.get("totalTests", 0) for run in test_runs)
            start_date = min((run.get("startedDate", "") for run in test_runs if run.get("startedDate")), default="")
            return {
                "passed": total_passed,
                "failed": total_failed,
                "total": total_tests,
                "date": start_date
            }
    st.warning(f"No test results found for build {build_id}")
    return {"passed": 0, "failed": 0, "total": 0, "date": ""}

# Process data into a DataFrame
def process_data(builds):
    data = []
    for build in builds:
        test_results = get_test_results_for_build(build["id"])
        total = test_results["total"]
        data.append({
            "Date": test_results["date"] or build["startTime"],
            "Build": build["buildNumber"],
            "Passed": test_results["passed"],
            "Failed": test_results["failed"],
            "Total": total,
            "Pass_Rate": (test_results["passed"] / total * 100) if total > 0 else 0,
            "Fail_Rate": (test_results["failed"] / total * 100) if total > 0 else 0,
            "Release": f"v{build['buildNumber'].split('.')[0]}.0",
            "Description": build["description"],
            "Link": build["link"]
        })
    df = pd.DataFrame(data)
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    return df

# Streamlit app
st.set_page_config(layout="wide")  # Use wide layout for compactness
st.title("Azure Pipelines Dashboard")

# Sidebar for pipeline selection (dropdown)
with st.sidebar:
    st.header("Filters")
    pipeline_options = {name: id for id, name in Pipeline_id.items()}
    selected_pipeline_name = st.selectbox(
        "Select Pipeline",
        list(pipeline_options.keys()),
        index=list(pipeline_options.keys()).index(Pipeline_id[DEFAULT_PIPELINE_ID]) if DEFAULT_PIPELINE_ID in Pipeline_id else 0
    )
    selected_pipeline_id = pipeline_options[selected_pipeline_name]
    
    st.markdown("""
    ### How to Use
    1. Create a `config.yml` file with your Azure DevOps details.
    2. Add it to `.gitignore`.
    3. Run with `streamlit run app.py`.
    """)

# Main content: 2x1 layout (table above chart)
# Fetch and process data for the selected pipeline
builds = get_builds_for_pipeline(selected_pipeline_id)
if builds:
    df = process_data(builds)

    # Row 1: Raw Test Data
    st.subheader("Raw Test Data")
    st.dataframe(
        df,
        height=200,  # ~5 rows visible, scroll for more
        use_container_width=True,
        column_config={
            "Link": st.column_config.LinkColumn(
                "Link",
                width="small",
                display_text="View"
            )
        },
        hide_index=True
    )

    # Row 2: Pass/Fail Trends
    st.subheader("Pass/Fail Trends")
    fig = px.area(
        df,
        x="Date",
        y=["Pass_Rate", "Fail_Rate"],
        title=f"Pipeline: {selected_pipeline_name}",
        labels={"value": "%", "variable": "Rate"},
        range_y=[0, 100],
        color_discrete_map={"Pass_Rate": "#00CC96", "Fail_Rate": "#EF553B"}
    )
    fig.update_traces(mode="lines+markers")
    fig.update_layout(
        yaxis_title="Percentage (%)",
        legend_title="Rate",
        hovermode="x unified",
        height=400,  # Adjusted height for single chart
        margin=dict(l=20, r=20, t=40, b=20)
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.write(f"No build data available for pipeline {selected_pipeline_name} (ID: {selected_pipeline_id}).")

import streamlit as st
import plotly.express as px
import os
import yaml
from utils.azure_api import AzureAPI
from streamlit_autorefresh import st_autorefresh


def load_config():
    try:
        with open("config.yml", "r") as file:
            return yaml.safe_load(file)
    except FileNotFoundError:
        st.error("config.yml not found. Please create it with the required fields.")
        return {}

# Function to check for new pipeline runs
def check_new_pipeline_runs():
    if project_pipelines and isinstance(project_pipelines, dict):
        for pipeline_name, pipeline_id in project_pipelines.items():
            latest_build_ids = azure_api_instance.get_latest_build_no_cache(
                ORGANIZATION, current_project, pipeline_id, max_builds=1
            )
            if latest_build_ids:
                latest_build_id = latest_build_ids[0]
                # Store the latest build ID from the non-cached call
                st.session_state[f"latest_non_cached_{pipeline_name}"] = latest_build_id

# Load configuration values
config = load_config()
ORGANIZATION = config.get("organization")
PAT = config.get("pat", os.environ.get("AZURE_PAT", ""))
BUILD_FILTERS = config.get("build_filters", {})
MAX_BUILDS_OPTION = config.get("max_builds_option")
AUTO_REFRESH_INTERVAL = config.get("auto_refresh_interval", None)

st.set_page_config(layout="wide")
st.title("Azure Pipelines Dashboard")

# Sidebar: Select Azure Project and common filters
with st.sidebar:
    st.header("Azure Projects")
    if config.get("projects") and isinstance(config["projects"], dict):
        project_options = {name: details for name, details in config["projects"].items()}
        selected_project_name = st.selectbox("Select Azure Project", list(project_options.keys()))
        project_details = project_options[selected_project_name]
        current_project = project_details.get("project")
        project_pipelines = project_details.get("pipelines")
        default_pipeline = project_details.get("default_pipeline", list(project_pipelines.keys())[0] if project_pipelines else None)
    else:
        st.error("No Azure projects defined in config.yml.")
        st.stop()
    
    st.header("Filters")
    selected_build_filter = st.selectbox("Custom builds filter", ["None"] + list(BUILD_FILTERS.keys()))
    
    build_labels = [f"Last {cnt} builds" for cnt in MAX_BUILDS_OPTION]
    default_build_index = 0
    selected_build_label = st.selectbox("Select max number of builds", options=build_labels, index=default_build_index)
    selected_build_value = MAX_BUILDS_OPTION[build_labels.index(selected_build_label)]
    
    x_axis_option = st.radio("Chart display type (x-axis)", options=["Date", "Build"], index=1)
    
    if st.button("Clear Cache"):
        AzureAPI.get_builds_for_pipeline.clear()
        AzureAPI.get_aggregated_test_results.clear()
        st.rerun()

# Initialize the AzureAPI class with only the PAT
azure_api_instance = AzureAPI(PAT)

# Auto-refresh to check for new runs
if AUTO_REFRESH_INTERVAL:
    st_autorefresh(interval=AUTO_REFRESH_INTERVAL, key="pipeline_checker")
    check_new_pipeline_runs()

# Display pipelines as tabs for the selected project
if project_pipelines and isinstance(project_pipelines, dict):
    pipeline_options = {name: id for name, id in project_pipelines.items()}
    tabs = st.tabs(list(pipeline_options.keys()))
    
    for pipeline_name, pipeline_id, tab in zip(pipeline_options.keys(), pipeline_options.values(), tabs):
        with tab:
            # Fetch builds (cached data)
            builds = azure_api_instance.get_builds_for_pipeline(
                ORGANIZATION, current_project, pipeline_id, max_builds=selected_build_value
            )
            
            # Check if there's a new run by comparing non-cached latest build with cached builds
            if f"latest_non_cached_{pipeline_name}" in st.session_state and builds:
                cached_latest_build_id = builds[0]["id"]  # Latest build from cached data
                non_cached_latest_build_id = st.session_state[f"latest_non_cached_{pipeline_name}"]
                if cached_latest_build_id != non_cached_latest_build_id:
                    st.warning(
                        f"New pipeline run available for {pipeline_name}! "
                        "The data below is outdated. Clear cache and refresh to see updates."
                    )
            
            if selected_build_filter != "None":
                filter_str = BUILD_FILTERS[selected_build_filter]
                builds = [build for build in builds if filter_str in build["buildNumber"]]
            
            if builds:
                # Process builds into a DataFrame
                df = azure_api_instance.process_data(ORGANIZATION, current_project, builds)
                
                # Prepare data for charting
                df_chart = df.sort_values("Datetime", ascending=True) if x_axis_option == "Build" else df.copy()
                df_table = df.sort_values("Datetime", ascending=False)
                
                st.dataframe(
                    df_table,
                    height=200,
                    use_container_width=True,
                    column_config={
                        "Link": st.column_config.LinkColumn("Link", width="small", display_text="View")
                    },
                    hide_index=True
                )
                
                if x_axis_option == "Date":
                    x_data = "Datetime"
                else:
                    x_data = "Build"
                    df_chart["Build"] = df_chart["Build"].astype(str)
                
                category_orders = {"Build": df_chart[x_data].tolist()} if x_axis_option == "Build" else {}
                
                fig = px.area(
                    df_chart,
                    x=x_data,
                    y=["Pass Rate (%)", "Fail Rate (%)"],
                    labels={"value": "%", "variable": "Rate", x_data: x_axis_option},
                    range_y=[0, 100],
                    color_discrete_map={"Pass Rate (%)": "#00CC96", "Fail Rate (%)": "#EF553B"},
                    category_orders=category_orders
                )
                fig.update_traces(mode="lines+markers")
                
                if x_axis_option == "Date":
                    fig.update_xaxes(tickformat="%Y-%m-%d")
                else:
                    fig.update_xaxes(type="category", tickangle=45, automargin=True)
                
                fig.update_layout(
                    yaxis_title="Percentage (%)",
                    legend_title="Rate",
                    hovermode="x unified",
                    height=400,
                    margin=dict(l=20, r=20, t=40, b=20)
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.write(f"No build data available for pipeline {pipeline_name} (ID: {pipeline_id}).")
else:
    st.error("No pipeline configuration found for the selected project.")

import streamlit as st
import requests
import base64
import pandas as pd

class AzureAPI:
    def __init__(self, pat):
        self.pat = pat
        self.auth_header = self._get_auth_header()
        
    def _get_auth_header(self):
        token = base64.b64encode(f":{self.pat}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def get_latest_build_no_cache(self, organization, project, pipeline_id, max_builds=None):
        url = f"https://dev.azure.com/{organization}/{project}/_apis/build/builds?definitions={pipeline_id}"
        if max_builds is not None:
            url += f"&maxBuildsPerDefinition={max_builds}"
        url += "&api-version=7.1-preview.7"
        response = requests.get(url, headers=self.auth_header)
        if response.status_code == 200:
            builds = response.json().get("value", [])
            return [build["id"] for build in builds] if builds else []
        return []

    @st.cache_data(ttl=3600)
    def get_builds_for_pipeline(_self, organization, project, pipeline_id, max_builds=None):
        base_url = f"https://dev.azure.com/{organization}/{project}/_apis/build/builds?definitions={pipeline_id}"
        if max_builds is not None:
            base_url += f"&maxBuildsPerDefinition={max_builds}"
        url = base_url + "&api-version=7.1-preview.7"
        response = requests.get(url, headers=_self.auth_header)
        if response.status_code == 200:
            builds = response.json().get("value", [])
            return [{
                "id": build["id"],
                "buildNumber": build.get("buildNumber", "N/A"),
                "startTime": build.get("startTime", ""),
                "description": f"#{build.get('buildNumber', 'N/A')} • {build.get('reason', 'Manual').capitalize()} ({build.get('sourceBranch', 'Unknown Branch')})",
                "link": f"https://dev.azure.com/{organization}/{project}/_build/results?buildId={build['id']}"
            } for build in builds]
        else:
            st.error(f"Error fetching builds for pipeline {pipeline_id}: {response.status_code} - {response.text}")
            return []

    @st.cache_data(ttl=3600)
    def get_aggregated_test_results(_self, organization, project, build_id):
        url = f"https://vstmr.dev.azure.com/{organization}/{project}/_apis/testresults/resultsbybuild?buildId={build_id}&api-version=7.1-preview.1"
        response = requests.get(url, headers=_self.auth_header)
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

    def process_data(self, organization, project, builds):
        data = []
        for build in builds:
            test_results = self.get_aggregated_test_results(organization, project, build["id"])
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

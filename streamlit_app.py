import streamlit as st
import requests
import time
import uuid

st.set_page_config(page_title="Support AI Agent UI", page_icon="🤖", layout="centered")

# --- Configuration Sidebar ---
with st.sidebar:
    st.header("⚙️ Configuration")
    api_host = st.text_input("API Host", value="localhost")
    api_port = st.text_input("API Port", value="8000")
    
    API_BASE_URL = f"http://{api_host}:{api_port}/api/v1"
    
    st.markdown("---")
    st.subheader("👥 Tenant Selection")
    
    # Fetch tenants dynamically
    CUSTOMER_ID = str()
    try:
        resp = requests.get(f"{API_BASE_URL}/tenants", timeout=2)
        if resp.status_code == 200:
            tenants = resp.json()
            if tenants:
                tenant_options = {f"{t['name']} ({t['id']})": t['id'] for t in tenants}
                selected_label = st.selectbox("Select Client", options=list(tenant_options.keys()))
                CUSTOMER_ID = tenant_options[selected_label]
            else:
                st.warning("No tenants found in Database.")
        else:
            st.error(f"Failed to load tenants (HTTP {resp.status_code}).")
    except requests.exceptions.RequestException:
        st.error("Cannot connect to API to fetch tenants.")
    
    st.markdown("---")
    st.caption(f"**Endpoint Configured:**\n `{API_BASE_URL}`")

# --- Main App ---
st.title("🤖 Support AI Agent Tester")
st.markdown("Submit a technical support request to trigger the full LangGraph investigation lifecycle asynchronously.")

# Initialize session state variables
if "job_id" not in st.session_state:
    st.session_state.job_id = None
if "ticket_id" not in st.session_state:
    st.session_state.ticket_id = None
if "status" not in st.session_state:
    st.session_state.status = None
if "report" not in st.session_state:
    st.session_state.report = None

# Input Form
with st.form("ticket_form"):
    ticket_text = st.text_area(
        "Describe the IT issue:", 
        placeholder="User reporting they cannot reach 172.27.0.0/24 from the branch office...",
        height=150
    )
    
    submitted = st.form_submit_button("Submit Webhook")
    
    if submitted:
        if not ticket_text.strip():
            st.error("Please enter a ticket description.")
        else:
            # 1. Reset state
            st.session_state.job_id = None
            st.session_state.ticket_id = None
            st.session_state.status = "pending"
            st.session_state.report = None
            
            payload = {
                "id": f"UI-{uuid.uuid4().hex[:6]}",
                "mode": "incident",
                "severity": "medium",
                "text": ticket_text,
                "source": "streamlit"
            }
            
            headers = {"X-Customer-ID": CUSTOMER_ID}
            
            try:
                response = requests.post(
                    f"{API_BASE_URL}/webhook/streamlit", 
                    json=payload, 
                    headers=headers
                )
                
                if response.status_code == 202:
                    data = response.json()
                    st.session_state.job_id = data.get("job_id")
                    st.session_state.ticket_id = data.get("ticket_id")
                    st.session_state.status = "running"
                    st.success(f"✅ Ticket ingested! Tracking Job ID: `{st.session_state.job_id}`")
                else:
                    st.error(f"Failed to ingest ticket. HTTP {response.status_code}: {response.text}")
                    st.session_state.status = "failed"
            except requests.exceptions.RequestException as e:
                 st.error(f"API Connection Error: Make sure FastAPI is running on port 8000. \n{e}")
                 st.session_state.status = "failed"

# Polling Logic
if st.session_state.job_id and st.session_state.status == "running":
    status_placeholder = st.empty()
    progress_bar = st.progress(0)
    
    polling_count = 0
    
    while st.session_state.status == "running":
        try:
            resp = requests.get(f"{API_BASE_URL}/jobs/{st.session_state.job_id}")
            if resp.status_code == 200:
                job_data = resp.json()
                current_status = job_data.get("status")
                
                if current_status == "completed":
                    st.session_state.status = "completed"
                    progress_bar.progress(100)
                    status_placeholder.success("🎉 Investigation Completed!")
                    break
                elif current_status == "failed":
                    st.session_state.status = "failed"
                    progress_bar.empty()
                    status_placeholder.error("❌ Agent execution failed.")
                    break
                else:
                    # Still running
                    progress_bar.progress((polling_count % 10) * 10) # Simple visual animation
                    msg = f"⏳ Agents are working... (Elapsed: {polling_count * 5}s)"
                    if polling_count >= 180: # 15 minutes
                        msg += "\n\n⚠️ **Note:** The investigation has been running for over 15 minutes. It may be handling a very complex ticket containing multiple components. You can let it continue, or safely abort the UI polling by clicking 'Stop' in the top right corner."
                    status_placeholder.info(msg)
            else:
                progress_bar.empty()
                status_placeholder.warning(f"Polling failed (HTTP {resp.status_code}). Retrying...")
        except requests.exceptions.RequestException:
             progress_bar.empty()
             status_placeholder.warning("Connection lost. Retrying...")
             
        time.sleep(5)
        polling_count += 1

# Display Report
if st.session_state.status == "completed":
    if not st.session_state.report:
        with st.spinner("Fetching final report..."):
            try:
                report_resp = requests.get(f"{API_BASE_URL}/tickets/{st.session_state.ticket_id}/report")
                if report_resp.status_code == 200:
                    st.session_state.report = report_resp.json().get("report", "No report content found.")
                else:
                    st.error(f"Failed to fetch report HTTP {report_resp.status_code}")
            except requests.exceptions.RequestException as e:
                st.error(f"Error fetching report: {e}")

    if st.session_state.report:
        st.markdown("---")
        st.subheader("Final Engineering Report")
        st.markdown(st.session_state.report)

# --- Job History Section ---
st.markdown("---")
with st.expander("📚 Past Job History & Reports"):
    if CUSTOMER_ID:
        if st.button("Refresh History"):
            with st.spinner("Fetching past jobs..."):
                try:
                    jobs_resp = requests.get(f"{API_BASE_URL}/tenants/{CUSTOMER_ID}/jobs?limit=10")
                    if jobs_resp.status_code == 200:
                        st.session_state.past_jobs = jobs_resp.json()
                    else:
                        st.error(f"Failed to fetch jobs (HTTP {jobs_resp.status_code})")
                except requests.exceptions.RequestException as e:
                    st.error(f"Error fetching jobs: {e}")

        if "past_jobs" in st.session_state and st.session_state.past_jobs:
            # Format the options cleanly
            job_options = {}
            for j in st.session_state.past_jobs:
                start_time = j.get('started_at', 'Unknown Time')[:16].replace('T', ' ') if j.get('started_at') else 'Unknown Time'
                label = f"{start_time} | Ticket: {j['ticket_id']} [{j['status'].upper()}]"
                job_options[label] = j['ticket_id']
                
            selected_job_label = st.selectbox("Select a past job:", options=list(job_options.keys()))
            
            if st.button("View Report"):
                selected_ticket_id = job_options[selected_job_label]
                with st.spinner("Loading..."):
                    try:
                        rep_resp = requests.get(f"{API_BASE_URL}/tickets/{selected_ticket_id}/report")
                        if rep_resp.status_code == 200:
                            st.session_state.past_report = rep_resp.json().get("report", "No report content found.")
                        else:
                            st.error(f"Failed to fetch report (HTTP {rep_resp.status_code}) - the job might not have finished.")
                            st.session_state.past_report = None
                    except Exception as e:
                        st.error(f"Error: {e}")
                        
        if "past_report" in st.session_state and st.session_state.past_report:
            st.markdown("### Historical Report")
            st.markdown(st.session_state.past_report)
    else:
        st.info("Select a tenant from the sidebar first.")

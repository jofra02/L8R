import streamlit as st
import requests
import time
import uuid

API_BASE_URL = "http://localhost:8000/api/v1"
CUSTOMER_ID = "fake_client"

st.set_page_config(page_title="Support AI Agent UI", page_icon="🤖", layout="centered")

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
    
    max_retries = 120 # 10 minutes max polling assuming 5s intervals
    polling_count = 0
    
    while st.session_state.status == "running" and polling_count < max_retries:
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
                    status_placeholder.info(f"⏳ Agents are working... (Polling {polling_count * 5}s)")
            else:
                progress_bar.empty()
                status_placeholder.warning(f"Polling failed (HTTP {resp.status_code}). Retrying...")
        except requests.exceptions.RequestException:
             progress_bar.empty()
             status_placeholder.warning("Connection lost. Retrying...")
             
        time.sleep(5)
        polling_count += 1
        
    if polling_count >= max_retries:
         st.session_state.status = "timeout"
         st.error("Polling timeout reached (10 minutes).")

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

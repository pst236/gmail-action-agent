import os
import datetime
import base64

import asyncio

try:
    asyncio.get_event_loop()
except RuntimeError:
    # Safely creates and sets a loop if Python 3.14 didn't auto-create one
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

# Your existing code starts here
import streamlit as st
# ... remainder of your code

import streamlit as st
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.genai import Client

# Gmail API Scopes
# Minimal scopes for reading and modifying (archive/mark) emails
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]



def authenticate_gmail():
    """Authenticates the user and returns a Gmail API service instance."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                st.error("Missing 'credentials.json' file. Please upload it to the directory.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

def fetch_recent_emails(service):
    """Fetches text content of emails received in the last 24 hours."""
    # Calculate time 24 hours ago
    time_24h_ago = datetime.datetime.now() - datetime.timedelta(days=1)
    epoch_24h_ago = int(time_24h_ago.timestamp())
    
    # Query string for emails received after the epoch timestamp
    query = f"after:{epoch_24h_ago}"
    
    try:
        results = service.users().messages().list(userId='me', q=query).execute()
        messages = results.get('messages', [])
        
        email_data = []
        for msg in messages[:20]: # Limit to top 20 emails to avoid rate limits
            msg_details = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
            payload = msg_details.get('payload', {})
            headers = payload.get('headers', [])
            
            # Extract Subject and Sender
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown Sender')
            
            # Extract Body Text
            body = ""
            if 'parts' in payload:
                for part in payload['parts']:
                    if part['mimeType'] == 'text/plain' and 'data' in part['body']:
                        body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                        break
            elif 'data' in payload.get('body', {}):
                body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
                
            if body:
                email_data.append({"sender": sender, "subject": subject, "body": body[:1500]}) # Truncate body
        return email_data
    except Exception as e:
        st.error(f"Error fetching emails: {e}")
        return []

def extract_action_items(emails, api_key):
    """Uses Gemini API to synthesize and extract clear action items from emails."""
    if not emails:
        return "No emails found in the last 24 hours."
        
    client = Client(api_key=api_key)
    
    # Prepare text payload for LLM analysis
    email_text_dump = ""
    for idx, email in enumerate(emails, 1):
        email_text_dump += f"\n--- Email #{idx} ---\nFrom: {email['sender']}\nSubject: {email['subject']}\nContent: {email['body']}\n"

    prompt = f"""
    You are an executive assistant. Review the following emails from the past 24 hours and extract all explicit action items, tasks, requests, or deadlines.
    Group them clearly by sender/subject. If an email contains no action items, skip it.
    
    Emails:
    {email_text_dump}
    
    Format your response in clean Markdown with checkboxes (- [ ]) for each individual action item. Include deadlines if mentioned.
    """
    
    # Configure model name here. Replace with a model available to your account if needed.
    MODEL_NAME = 'models/gemini-3-flash-preview'

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )
        return response.text
    except Exception as e:
        err = str(e)
        if 'no longer available' in err or 'NOT_FOUND' in err or '404' in err:
            st.error(
                f"Model {MODEL_NAME} is not available to your account: {e}.\n"
                "Open Google Cloud Console → Generative AI → Models and pick a model you have access to, then set `MODEL_NAME` accordingly."
            )
        else:
            st.error(f"Error connecting to Gemini API: {e}")
        return f"Error connecting to Gemini API: {e}"

# Streamlit UI Construction
st.set_page_config(page_title="Gmail Action Items Agent", layout="wide")
st.title("📬 Gmail Action Items Extractor")
st.subheader("Extract actionable tasks from your last 24 hours of emails.")

# Sidebar for API Configuration
with st.sidebar:
    st.header("Configuration")
    gemini_key = st.text_input("Gemini API Key", type="password")
    st.info("Ensure your 'credentials.json' file is uploaded to the root directory of your workspace.")

# Main Application Logic
if st.button("Fetch and Analyze Emails", type="primary"):
    if not gemini_key:
        st.warning("Please provide your Gemini API key in the sidebar.")
    else:
        with st.spinner("Connecting to Gmail..."):
            gmail_service = authenticate_gmail()
            
        if gmail_service:
            with st.spinner("Fetching emails from the past 24 hours..."):
                emails = fetch_recent_emails(gmail_service)
                st.success(f"Successfully downloaded {len(emails)} recent emails.")
                
            with st.spinner("Extracting action items with AI..."):
                summary = extract_action_items(emails, gemini_key)
                
            st.markdown("### 📋 Extracted Action Items")
            st.markdown(summary)

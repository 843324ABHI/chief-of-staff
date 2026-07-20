import os.path
import base64
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
# pyrefly: ignore [missing-import]
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# If modifying these scopes, delete the file token.json.
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar'
]
def get_service():
    """
    Shows basic usage of the Gmail API.
    Lists the user's Gmail labels.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                raise FileNotFoundError(
                    "credentials.json not found! "
                    "Please download your OAuth client ID JSON from the Google Cloud Console "
                    "and save it as 'credentials.json' in the root directory."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    # Build and return the Gmail API service
    return build('gmail', 'v1', credentials=creds)

def fetch_threads(max_results=10):
    """
    Fetches the most recent threads from the user's inbox.
    Returns a list of dictionaries with thread details formatted for app.py.
    """
    service = get_service()
    
    # Query for threads in the inbox
    results = service.users().threads().list(userId='me', maxResults=max_results, q="in:inbox").execute()
    threads = results.get('threads', [])
    
    formatted_threads = []
    
    for t in threads:
        t_id = t['id']
        # Fetch the full thread details to get headers and snippet
        t_details = service.users().threads().get(userId='me', id=t_id).execute()
        
        messages = t_details.get('messages', [])
        if not messages:
            continue
            
        # We usually want the headers from the most recent message in the thread
        latest_message = messages[-1]
        payload = latest_message.get('payload', {})
        headers = payload.get('headers', [])
        
        subject = "No Subject"
        sender = "Unknown Sender"
        date = "Unknown Date"
        message_id = ""
        
        for header in headers:
            name = header.get('name', '').lower()
            if name == 'subject':
                subject = header.get('value')
            elif name == 'from':
                sender = header.get('value')
            elif name == 'date':
                date = header.get('value')
            elif name == 'message-id':
                message_id = header.get('value')
                
        # The snippet represents the general preview text for the thread
        snippet = t_details.get('snippet', '')
        
        formatted_threads.append({
            "thread_id": t_id,
            "sender": sender,
            "subject": subject,
            "snippet": snippet,
            "date": date,
            "message_id": message_id
        })
        
    return formatted_threads

def send_reply(thread_id, to_address, subject, body_text, message_id=None):
    """
    Sends an email reply to a specific thread.
    """
    service = get_service()
    
    message = EmailMessage()
    message.set_content(body_text)
    message['To'] = to_address
    message['Subject'] = subject
    if message_id:
        message['In-Reply-To'] = message_id
        message['References'] = message_id

    # Create the raw base64 string expected by the Gmail API
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

    create_message = {
        'raw': encoded_message,
        'threadId': thread_id
    }

    send_message = service.users().messages().send(userId="me", body=create_message).execute()
    return send_message

if __name__ == '__main__':
    # Test execution when run directly
    print("Authenticating and fetching threads...")
    try:
        recent_threads = fetch_threads(max_results=3)
        print(f"\nSuccessfully fetched {len(recent_threads)} threads:\n" + "="*40)
        for t in recent_threads:
            print(f"Subject: {t['subject']}")
            print(f"From:    {t['sender']}")
            print(f"Date:    {t['date']}")
            print(f"Preview: {t['snippet']}\n")
    except Exception as e:
        print(f"\nError: {e}")

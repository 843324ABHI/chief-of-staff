import os
import os.path
import json
import datetime
import socket
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
# pyrefly: ignore [missing-import]
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from groq import Groq

# IPv4 monkey-patch
old_getaddrinfo = socket.getaddrinfo
def new_getaddrinfo(*args, **kwargs):
    responses = old_getaddrinfo(*args, **kwargs)
    return [response for response in responses if response[0] == socket.AF_INET]
socket.getaddrinfo = new_getaddrinfo

# If modifying these scopes, delete the file token.json.
# Using the exact scopes from engine.py as requested.
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar'
]

def _build_calendar_service():
    """
    Builds the Calendar API service using the shared token.json.
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

    # Build and return the Calendar API service
    return build('calendar', 'v3', credentials=creds)

def parse_meeting_request(thread):
    """
    Parses a meeting request from an email thread using Groq.
    """
    try:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            return {"parsing_error": "GROQ_API_KEY not found in environment."}
            
        messages_text = ""
        if isinstance(thread, dict):
            if "messages" in thread:
                for msg in thread["messages"]:
                    sender = msg.get("from", msg.get("sender", "Unknown"))
                    date = msg.get("date", "")
                    body = msg.get("body", msg.get("snippet", ""))
                    messages_text += f"From: {sender}\nDate: {date}\nBody: {body}\n\n"
            else:
                sender = thread.get("sender", "Unknown")
                date = thread.get("date", "")
                body = thread.get("snippet", "")
                messages_text = f"From: {sender}\nDate: {date}\nBody: {body}\n"
        else:
            messages_text = str(thread)

        today_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        prompt = f'''System Instruction:
You are a helpful assistant that extracts meeting details from an email thread.
Today's date is: {today_str}. Use this to resolve relative dates (e.g. "tomorrow", "next Tuesday").
Extract the following information and return ONLY valid JSON:
- proposed_times: list of ISO-8601 datetime strings
- attendees: list of email addresses or names
- topic: one-line summary of the meeting
- duration_minutes: integer (default to 30 if not specified)

Do not include any explanation or markdown formatting outside the JSON object.

Email Thread:
{messages_text}'''

        client = Groq(api_key=api_key)
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            model="llama-3.1-8b-instant",
        )
        
        response_text = chat_completion.choices[0].message.content.strip()
        
        # Strip markdown code fences if present
        if response_text.startswith("```"):
            lines = response_text.split('\n')
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            response_text = '\n'.join(lines).strip()
            
        data = json.loads(response_text)
        
        if "duration_minutes" not in data:
            data["duration_minutes"] = 30
            
        return data

    except Exception as e:
        return {"parsing_error": str(e)}

def check_availability(time_min, time_max):
    """
    Calls the FreeBusy API on the user's primary calendar.
    Returns True if free, False if busy.
    Appends 'Z' to times that lack timezone info.
    Catches exceptions and returns False as safe default.
    """
    try:
        # Simple heuristic for missing timezone: no 'Z' and no '+' or '-' after the time part.
        if not time_min.endswith('Z') and '+' not in time_min and '-' not in time_min[10:]:
            time_min += 'Z'
        if not time_max.endswith('Z') and '+' not in time_max and '-' not in time_max[10:]:
            time_max += 'Z'
            
        service = _build_calendar_service()
        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": "primary"}]
        }
        
        eventsResult = service.freebusy().query(body=body).execute()
        calendars = eventsResult.get('calendars', {})
        primary = calendars.get('primary', {})
        busy = primary.get('busy', [])
        
        # If there are any busy intervals, return False
        if busy:
            return False
        return True
    except Exception:
        return False

def find_free_slot(proposed_times, duration_minutes):
    """
    Loops through proposed times, calculates end time using duration, calls check_availability
    for each, and returns the first free slot or None. Skips malformed time strings gracefully.
    """
    if not proposed_times:
        return None
        
    for pt in proposed_times:
        try:
            pt_clean = pt.replace('Z', '+00:00')
            start_dt = datetime.datetime.fromisoformat(pt_clean)
            end_dt = start_dt + datetime.timedelta(minutes=duration_minutes)
            
            time_min = pt
            time_max = end_dt.isoformat()
            
            if check_availability(time_min, time_max):
                return pt
        except Exception:
            continue
            
    return None

def create_event(summary, start_time, duration_minutes, attendees, description=""):
    """
    Creates a Google Calendar event on the user's primary calendar.
    Calculates end_time from start + duration.
    Only includes attendees if they contain valid emails (have "@").
    """
    service = _build_calendar_service()
    
    # Calculate end time
    start_time_clean = start_time.replace('Z', '+00:00')
    start_dt = datetime.datetime.fromisoformat(start_time_clean)
    end_dt = start_dt + datetime.timedelta(minutes=duration_minutes)
    
    # Format times properly for the API, ensuring a 'Z' or offset exists
    start_str = start_time
    if not start_str.endswith('Z') and '+' not in start_str and '-' not in start_str[10:]:
        start_str += 'Z'
        
    end_str = end_dt.isoformat()
    if not end_str.endswith('Z') and '+' not in end_str and '-' not in end_str[10:]:
        end_str += 'Z'
        
    # Filter attendees
    valid_attendees = [{"email": a} for a in attendees if "@" in a]
    
    event_body = {
        "summary": summary,
        "description": description,
        "start": {
            "dateTime": start_str,
            "timeZone": "UTC"
        },
        "end": {
            "dateTime": end_str,
            "timeZone": "UTC"
        }
    }
    
    if valid_attendees:
        event_body["attendees"] = valid_attendees
        
    created_event = service.events().insert(
        calendarId="primary",
        sendUpdates="all",
        body=event_body
    ).execute()
    
    return created_event

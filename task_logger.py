import json
import os
import datetime

LOG_FILE = "action_log.json"

def log_action(action_type, thread_subject, detail, action_id):
    """
    Appends a record to action_log.json
    """
    record = {
        "timestamp": datetime.datetime.now().isoformat(),
        "action_type": action_type,
        "thread_subject": thread_subject,
        "detail": detail,
        "id": action_id
    }
    
    logs = get_action_log()
    logs.append(record)
    
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=4)

def get_action_log():
    """
    Reads action_log.json and returns the full list.
    Returns [] if the file does not exist or is empty.
    """
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r") as f:
            content = f.read().strip()
            if not content:
                return []
            return json.loads(content)
    except Exception:
        return []

def clear_log():
    """
    Writes an empty list to action_log.json
    """
    with open(LOG_FILE, "w") as f:
        json.dump([], f, indent=4)

import json
import os

def load_tone_profile(path="tone_profile.json"):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_past_replies(path="past_replies.json"):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def format_thread_history(thread):
    formatted_parts = []
    subject = thread.get("subject", "")
    if subject:
        formatted_parts.append(f"Subject: {subject}\n")
    
    messages = thread.get("messages", [])
    for msg in messages:
        sender = msg.get("from", "Unknown")
        date = msg.get("date", "Unknown date")
        body = msg.get("body", "")
        formatted_parts.append(f"From: {sender}\nDate: {date}\n\n{body}\n\n----------------------------------------")
        
    return "\n\n".join(formatted_parts).strip()

def build_system_prompt(tone_profile, past_replies):
    name = tone_profile.get("name", "the user")
    role = tone_profile.get("role", "a professional")
    tone = tone_profile.get("tone", "professional")
    formality = tone_profile.get("formality", "neutral")
    quirks = tone_profile.get("quirks", [])
    
    prompt = f"You are an AI assistant acting as {name}, {role}.\n"
    prompt += f"Your goal is to draft email replies in their exact voice.\n\n"
    prompt += f"Tone: {tone}\n"
    prompt += f"Formality: {formality}\n\n"
    
    if quirks:
        prompt += "Writing Rules & Quirks:\n"
        for quirk in quirks:
            prompt += f"- {quirk}\n"
        prompt += "\n"
        
    if past_replies:
        prompt += f"Here's how {name} writes:\n\n"
        for i, reply in enumerate(past_replies[:3]):
            prompt += f"--- Example {i+1} ---\n"
            if "subject" in reply:
                prompt += f"Subject: {reply['subject']}\n"
            prompt += f"{reply.get('body', '')}\n\n"
            
    return prompt.strip()

def build_user_prompt(thread_formatted):
    prompt = "Please draft a reply to the following email thread based on my persona.\n\n"
    prompt += "Email Thread:\n"
    prompt += "========================================\n"
    prompt += f"{thread_formatted}\n"
    prompt += "========================================"
    return prompt

def assemble_context(thread, tone_path="tone_profile.json", replies_path="past_replies.json"):
    tone_profile = load_tone_profile(tone_path)
    past_replies = load_past_replies(replies_path)
    
    thread_formatted = format_thread_history(thread)
    
    system_prompt = build_system_prompt(tone_profile, past_replies)
    user_prompt = build_user_prompt(thread_formatted)
    
    return {
        "system": system_prompt,
        "user": user_prompt
    }

if __name__ == "__main__":
    # Test thread
    sample_thread = {
        "subject": "Need feedback on the new landing page design",
        "messages": [
            {
                "from": "Elena (Design Team)",
                "date": "2023-10-25 10:00 AM",
                "body": "Hi Rahul,\n\nWe've finished the first draft of the new landing page. Could you take a look when you have a moment? I'm mainly concerned about whether the main call-to-action is clear enough.\n\nThanks,\nElena"
            },
            {
                "from": "Rahul",
                "date": "2023-10-25 10:15 AM",
                "body": "Hey Elena,\n\nWill check it out this afternoon. Send over the Figma link.\n\nBest, Rahul"
            },
            {
                "from": "Elena (Design Team)",
                "date": "2023-10-25 10:20 AM",
                "body": "Here is the link: figma.com/example\nLet me know your thoughts!"
            }
        ]
    }

    try:
        context = assemble_context(
            sample_thread, 
            tone_path="tone_profile.json", 
            replies_path="past_replies.json"
        )
        print("=== SYSTEM PROMPT ===\n")
        print(context["system"])
        print("\n=== USER PROMPT ===\n")
        print(context["user"])
    except Exception as e:
        print(f"Error: {e}")

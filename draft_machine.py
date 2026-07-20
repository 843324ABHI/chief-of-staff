import os
from dotenv import load_dotenv
from context_builder import assemble_context

load_dotenv()

SAMPLE_THREADS = [
    {
        "subject": "Q3 Budget Review",
        "messages": [
            {
                "from": "Sarah (Finance)",
                "date": "2023-10-25 10:00 AM",
                "body": "Hi Rahul,\n\nWe need to review the Q3 budget by tomorrow. Are you available for a quick call at 2 PM?\n\nThanks,\nSarah"
            }
        ]
    },
    {
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
    },
    {
        "subject": "Client meeting follow-up",
        "messages": [
            {
                "from": "Michael (Sales)",
                "date": "2023-10-26 09:00 AM",
                "body": "Hi Rahul,\n\nThe meeting with Acme Corp went well. They are interested in our enterprise tier but want a discount on the onboarding fee. Should we approve a 20% discount to close the deal?\n\nThanks,\nMichael"
            }
        ]
    }
]

def draft_reply(thread, provider="Gemini"):
    """
    Drafts an email reply using the provided thread and persona context.
    """
    context = assemble_context(thread)
    
    system_prompt = context["system"]
    user_prompt = context["user"]
    
    drafting_rules = """
Drafting Rules:
a. ONE-ASK RULE: every email has exactly ONE clear question or ONE clear response
b. LENGTH CONTROL: match thread energy, max 5 sentences, use numbered points if needed
c. NO AI FILLER: never say "I hope this finds you well", "Thank you for reaching out", etc.
d. STRUCTURE: acknowledge briefly -> give response -> ONE clear next step

Output ONLY the draft text. Do not include a subject line or any explanations.
"""
    
    combined_prompt = f"{system_prompt}\n\n{drafting_rules}\n\n{user_prompt}"
    
    if provider == "Groq":
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": combined_prompt,
                }
            ],
            model="llama-3.1-8b-instant",
        )
        return chat_completion.choices[0].message.content.strip()
    else:
        from google import genai
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=combined_prompt,
        )
        
        return response.text.strip()

def draft_reply_with_metadata(thread):
    """
    Drafts an email reply and returns it along with relevant metadata.
    """
    draft_text = draft_reply(thread)
    
    subject = thread.get("subject", "")
    
    messages = thread.get("messages", [])
    reply_to = messages[-1].get("from", "Unknown") if messages else "Unknown"
    
    return {
        "draft": draft_text,
        "model": "gemini-2.5-flash",
        "subject": subject,
        "reply_to": reply_to
    }

if __name__ == "__main__":
    if not os.getenv("GEMINI_API_KEY"):
        print("Error: GEMINI_API_KEY environment variable is missing. Please set it in your .env file.")
        exit(1)
        
    sample_thread = {
        "subject": "Q3 Budget Review",
        "messages": [
            {
                "from": "Sarah (Finance)",
                "date": "2023-10-25 10:00 AM",
                "body": "Hi Rahul,\n\nWe need to review the Q3 budget by tomorrow. Are you available for a quick call at 2 PM?\n\nThanks,\nSarah"
            }
        ]
    }
    
    print("Generating draft...")
    try:
        result = draft_reply_with_metadata(sample_thread)
        print("\n=== METADATA ===")
        print(f"Model: {result['model']}")
        print(f"Subject: {result['subject']}")
        print(f"Replying to: {result['reply_to']}")
        print("\n=== DRAFT ===")
        print(result['draft'])
    except Exception as e:
        print(f"Error generating draft: {e}")

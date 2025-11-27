import os
import json
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from twilio.twiml.voice_response import VoiceResponse, Gather
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY not set")

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI()

# Conversation memory storage per call
conversation_state = {}

# System prompt for the AI
SYSTEM_PROMPT = """
You are a friendly and professional restaurant reservation assistant.
Your job is to collect:
- Customer name
- Reservation date
- Reservation time
- Number of guests
- Any special requests

Ask ONE question at a time.

When all details are collected, reply ONLY with JSON in this exact format:

{
  "status": "complete",
  "name": "John Smith",
  "date": "2025-11-20",
  "time": "7:00 PM",
  "party_size": "4",
  "notes": "Window seat please"
}

If details are still missing, continue asking normal questions.
DO NOT return JSON until everything is collected.
"""


@app.get("/")
def home():
    return {"status": "ok", "message": "AI reservation system running"}


@app.post("/incoming-call", response_class=PlainTextResponse)
async def incoming_call():
    """First webhook when call arrives."""
    twiml = VoiceResponse()

    gather = Gather(
        input="speech",
        action="/process-speech",
        speech_timeout="auto"
    )
    gather.say("Hello! I can help you make a reservation. How may I assist you today?")
    twiml.append(gather)

    # Fallback if no speech detected
    twiml.say("Sorry, I didn't hear anything. Goodbye.")
    twiml.hangup()

    return str(twiml)


@app.post("/process-speech", response_class=PlainTextResponse)
async def process_speech(request: Request):
    """Handles each piece of speech from the caller."""
    form = await request.form()

    speech_text = form.get("SpeechResult", "").strip()
    call_sid = form.get("CallSid", "unknown")

    print(f"\nCALL {call_sid} - USER SAID: {speech_text}")

    # Create memory for this call if needed
    if call_sid not in conversation_state:
        conversation_state[call_sid] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    # Handle

import os
import json
from fastapi import FastAPI, Request, Form
from fastapi.responses import PlainTextResponse
from twilio.twiml.voice_response import VoiceResponse, Gather
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY not set in environment variables")

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI()

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


def ask_openai(user_text: str) -> str:
    """Send user speech to OpenAI and return the assistant reply."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # cheap & good
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("OpenAI error:", e)
        return "Sorry, I had an issue. Could you repeat that?"


@app.get("/")
def home():
    return {"status": "ok", "message": "AI reservation system running"}


@app.post("/incoming-call", response_class=PlainTextResponse)
async def incoming_call():
    """First Twilio webhook: greet the caller and start listening."""
    twiml = VoiceResponse()

    gather = Gather(
        input="speech",
        action="/process-speech",
        speech_timeout="auto"
    )
    gather.say("Hello! I can help you make a reservation. How may I assist you today?")
    twiml.append(gather)

    twiml.say("Sorry, I didn't catch anything. Goodbye.")
    twiml.hangup()
    return str(twiml)


@app.post("/process-speech", response_class=PlainTextResponse)
async def process_speech(request: Request):
    """Twilio sends caller speech here. We respond with AI output."""
    form = await request.form()
    speech_text = form.get("SpeechResult", "").strip()

    print("\nCALLER SAID:", speech_text)

    if not speech_text:
        twiml = VoiceResponse()
        gather = Gather(input="speech", action="/process-speech")
        gather.say("Sorry, I didn't hear that. Could you repeat?")
        twiml.append(gather)
        return str(twiml)

    ai_reply = ask_openai(speech_text)
    print("AI REPLY:", ai_reply)

    # Check if AI returned JSON (reservation complete)
    if ai_reply.startswith("{"):
        try:
            data = json.loads(ai_reply)

            if data.get("status") == "complete":
                print("\nFINAL RESERVATION DATA:", data)

                twiml = VoiceResponse()
                twiml.say(
                    f"Thank you {data['name']}. "
                    f"Your reservation for {data['party_size']} people "
                    f"on {data['date']} at {data['time']} "
                    "has been recorded. We look forward to seeing you!"
                )
                twiml.hangup()
                return str(twiml)

        except Exception as e:
            print("JSON parsing error:", e)

    # Otherwise continue the conversation
    twiml = VoiceResponse()
    gather = Gather(
        input="speech",
        action="/process-speech",
        speech_timeout="auto"
    )
    gather.say(ai_reply[:400])  # keep reply short
    twiml.append(gather)

    return str(twiml)

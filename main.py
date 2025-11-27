import os
import json
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Gather
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY not set")

client = OpenAI(api_key=OPENAI_API_KEY)
app = FastAPI()

BASE_URL = "https://ai-call-reservations.onrender.com"

# Track per-call reservation data (active calls)
reservation_state = {}
# Store confirmed reservations (for UI)
confirmed_reservations = []

SYSTEM_PROMPT = """
You are an extraction-only assistant for a voice reservation system.

You NEVER ask questions and you NEVER chat.

Your ONLY job is:
Given a SINGLE user message, extract these fields IF they are present:

{
  "name": "",
  "date": "",
  "time": "",
  "party_size": "",
  "notes": ""
}

Rules:
- Always respond with EXACTLY one JSON object.
- No markdown, no ``` fences, no text before or after JSON.
- If a field is not clearly mentioned, leave it as an empty string "".
- Do NOT infer or guess missing fields.
- Do NOT ask questions.
- Do NOT explain anything.
- Output ONLY valid JSON.
"""
    

def next_question(data):
    """Return the next missing field as a friendly question."""
    if not data.get("name"):
        return "Sure! Please say your full name now, for example: John Smith."
    if not data.get("date"):
        return "Great! What date would you like the reservation for?"
    if not data.get("time"):
        return "Perfect. And what time works best for you?"
    if not data.get("party_size"):
        return "Got it. How many guests will be joining?"
    if not data.get("notes"):
        return "Excellent. Any special requests? For example seating or dietary needs?"
    return None


@app.get("/")
def home():
    return {"status": "ok"}


@app.get("/reservations")
def list_reservations():
    """
    Return all confirmed reservations.
    This is what your Lovable UI will call.
    """
    return {"reservations": confirmed_reservations}


@app.post("/incoming-call", response_class=Response)
async def incoming_call():
    """Initial greeting."""
    twiml = VoiceResponse()

    gather = Gather(
        input="speech",
        action=f"{BASE_URL}/process-speech",
        speech_timeout="auto",
        language="en-GB"
    )
    gather.say(
        "Hello! I can help you make a reservation. How may I assist you today?",
        voice="Polly.Amy"
    )
    twiml.append(gather)

    return Response(str(twiml), media_type="application/xml")


@app.post("/process-speech", response_class=Response)
async def process_speech(request: Request):
    """Handle speech from the caller."""
    form = await request.form()

    speech = form.get("SpeechResult", "").strip()
    call_sid = form.get("CallSid", "unknown")

    print(f"\nCALL {call_sid} - USER SAID: {speech}")

    # Create reservation state if new caller
    if call_sid not in reservation_state:
        reservation_state[call_sid] = {
            "name": None,
            "date": None,
            "time": None,
            "party_size": None,
            "notes": None,
        }

    # If silence or noise
    if not speech:
        twiml = VoiceResponse()
        gather = Gather(
            input="speech",
            action=f"{BASE_URL}/process-speech",
            language="en-GB"
        )
        gather.say(
            "Sorry, I didn't quite catch that. Could you say that again?",
            voice="Polly.Amy"
        )
        twiml.append(gather)
        return Response(str(twiml), media_type="application/xml")

    # ---- STRICT AI EXTRACTION (stateless) ----
    extracted = {}
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": speech},
            ],
        )
        raw = completion.choices[0].message.content.strip()
        print("RAW EXTRACTION:", raw)

        # Strip markdown fences if model adds them
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()

        extracted = json.loads(raw)

    except Exception as e:
        print("Extraction error:", e)
        extracted = {}

    # Update reservation state with extracted fields
    current = reservation_state[call_sid]

    for field in ["name", "date", "time", "party_size", "notes"]:
        value = extracted.get(field)
        if isinstance(value, str) and value.strip():
            current[field] = value.strip()

    print("Current Reservation:", current)

    # Decide what to ask next
    question = next_question(current)

    twiml = VoiceResponse()

    # If all fields collected → confirm, store, and end
    if not question:
        final = current.copy()
        final["call_sid"] = call_sid
        final["created_at"] = datetime.utcnow().isoformat() + "Z"

        confirmed_reservations.append(final)
        print("CONFIRMED RESERVATIONS:", confirmed_reservations)

        twiml.say(
            f"Thanks {final['name']}! Your reservation for {final['party_size']} guests "
            f"on {final['date']} at {final['time']} has been recorded. "
            "We look forward to seeing you!",
            voice="Polly.Amy"
        )
        twiml.hangup()

        # Cleanup active state
        reservation_state.pop(call_sid, None)
        return Response(str(twiml), media_type="application/xml")

    # Ask the next friendly question
    gather = Gather(
        input="speech",
        action=f"{BASE_URL}/process-speech",
        speech_timeout="auto",
        language="en-GB"
    )
    gather.say(question, voice="Polly.Amy")
    twiml.append(gather)

    return Response(str(twiml), media_type="application/xml")

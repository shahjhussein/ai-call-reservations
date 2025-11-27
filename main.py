import os
import json
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

# Track per-call reservation data
reservation_state = {}
conversation_state = {}  # memory for extraction


SYSTEM_PROMPT = """
You are an extraction-only assistant. 
You NEVER ask questions. You NEVER give instructions.
You ONLY extract information from what the user says.

Given any user message, extract ONLY these fields if present:

{
  "name": "",
  "date": "",
  "time": "",
  "party_size": "",
  "notes": ""
}

Rules:
- If a field is not mentioned, leave it as an empty string.
- DO NOT ask questions.
- DO NOT add explanations.
- DO NOT format anything except the JSON.
- Output ONLY valid JSON.
"""


@app.get("/")
def home():
    return {"status": "ok"}


@app.post("/incoming-call", response_class=Response)
async def incoming_call():
    twiml = VoiceResponse()

    gather = Gather(
        input="speech",
        action=f"{BASE_URL}/process-speech",
        speech_timeout="auto"
    )
    gather.say("Hello! I can help you make a reservation. How may I assist you today?")
    twiml.append(gather)

    return Response(str(twiml), media_type="application/xml")


def next_question(data):
    if not data.get("name"):
        return "Sure! What name should I put down for the reservation?"
    if not data.get("date"):
        return "Great! What date would you like the reservation for?"
    if not data.get("time"):
        return "Perfect. And what time works best for you?"
    if not data.get("party_size"):
        return "Got it. How many guests will be joining?"
    if not data.get("notes"):
        return "Excellent. Any special requests? For example seating or dietary needs?"
    return None


@app.post("/process-speech", response_class=Response)
async def process_speech(request: Request):
    form = await request.form()

    speech = form.get("SpeechResult", "").strip()
    call_sid = form.get("CallSid", "unknown")

    print(f"\nCALL {call_sid} - USER SAID: {speech}")

    # Create State If Not Exists
    if call_sid not in reservation_state:
        reservation_state[call_sid] = {
            "name": None,
            "date": None,
            "time": None,
            "party_size": None,
            "notes": None
        }

    if call_sid not in conversation_state:
        conversation_state[call_sid] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    # If no speech
    if not speech:
        twiml = VoiceResponse()
        gather = Gather(
            input="speech",
            action=f"{BASE_URL}/process-speech"
        )
        gather.say("Sorry, could you repeat that?")
        twiml.append(gather)
        return Response(str(twiml), media_type="application/xml")

    # Run extraction AI
    conversation_state[call_sid].append({"role": "user", "content": speech})

    try:
        result = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=conversation_state[call_sid],
            temperature=0.0
        )
        extracted_json = result.choices[0].message.content.strip()
        extracted = json.loads(extracted_json)
    except Exception as e:
        print("Extraction error:", e)
        extracted = {}

    # Update reservation fields if extracted
    for field in ["name", "date", "time", "party_size", "notes"]:
        if extracted.get(field):
            reservation_state[call_sid][field] = extracted[field]

    print("Current Reservation:", reservation_state[call_sid])

    # Determine next question
    question = next_question(reservation_state[call_sid])

    twiml = VoiceResponse()

    if not question:
        final = reservation_state[call_sid]
        twiml.say(
            f"Thanks {final['name']}! Your reservation for {final['party_size']} guests "
            f"on {final['date']} at {final['time']} has been recorded. "
            "We look forward to seeing you!"
        )
        twiml.hangup()
        reservation_state.pop(call_sid, None)
        conversation_state.pop(call_sid, None)
        return Response(str(twiml), media_type="application/xml")

    # Ask the NEXT question only
    gather = Gather(
        input="speech",
        action=f"{BASE_URL}/process-speech",
        speech_timeout="auto"
    )
    gather.say(question)
    twiml.append(gather)

    return Response(str(twiml), media_type="application/xml")

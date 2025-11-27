import os
import json
from fastapi import FastAPI, Request
from fastapi.responses import Response
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

# Memory store per call
conversation_state = {}

# AI system instructions
SYSTEM_PROMPT = """
You are a friendly and professional restaurant reservation assistant.
Your job is to collect the customer's:
- Full name
- Reservation date
- Reservation time
- Number of guests
- Any special notes

Ask ONE question at a time.
Never ask for multiple details in one question.

When ALL details are collected, reply ONLY in JSON exactly like this:

{
  "status": "complete",
  "name": "John Smith",
  "date": "2025-11-20",
  "time": "7:00 PM",
  "party_size": "4",
  "notes": "Window seat please"
}

Before JSON output, continue the conversation normally.
Do NOT output JSON until booking is complete.
"""


@app.get("/")
def home():
    return {"status": "ok", "message": "AI reservation system running"}


@app.post("/incoming-call", response_class=Response)
async def incoming_call():
    """Initial greeting when call comes in."""
    twiml = VoiceResponse()

    gather = Gather(
        input="speech",
        action="/process-speech",
        speech_timeout="auto"
    )
    gather.say("Hello! I can help you make a reservation. How may I assist you today?")
    twiml.append(gather)

    twiml.say("Sorry, I didn't catch that. Goodbye.")
    twiml.hangup()

    return Response(content=str(twiml), media_type="application/xml")


@app.post("/process-speech", response_class=Response)
async def process_speech(request: Request):
    """Handles each user message."""
    form = await request.form()

    speech_text = form.get("SpeechResult", "").strip()
    call_sid = form.get("CallSid", "unknown")

    print(f"\nCALL {call_sid} - USER SAID: {speech_text}")

    # Ensure memory exists
    if call_sid not in conversation_state:
        conversation_state[call_sid] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    # Handle empty speech
    if not speech_text:
        twiml = VoiceResponse()
        gather = Gather(input="speech", action="/process-speech")
        gather.say("Sorry, I didn't hear that. Could you repeat?")
        twiml.append(gather)
        return Response(content=str(twiml), media_type="application/xml")

    # Store user message
    conversation_state[call_sid].append(
        {"role": "user", "content": speech_text}
    )

    # Call OpenAI
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=conversation_state[call_sid],
            temperature=0.3
        )
        ai_reply = response.choices[0].message.content.strip()
    except Exception as e:
        print("OpenAI error:", e)
        ai_reply = "Sorry, I had a problem. Could you repeat that?"

    print("AI REPLY:", ai_reply)

    # Store assistant message
    conversation_state[call_sid].append(
        {"role": "assistant", "content": ai_reply}
    )

    # Check if AI returned JSON completion
    if ai_reply.startswith("{"):
        try:
            data = json.loads(ai_reply)

            if data.get("status") == "complete":
                print("\nFINAL RESERVATION DATA:", data)

                # Clear memory
                conversation_state.pop(call_sid, None)

                twiml = VoiceResponse()
                twiml.say(
                    f"Thank you {data['name']}. "
                    f"Your reservation for {data['party_size']} guests "
                    f"on {data['date']} at {data['time']} is confirmed. "
                    "We look forward to seeing you!"
                )
                twiml.hangup()
                return Response(content=str(twiml), media_type="application/xml")

        except Exception as e:
            print("JSON parse error:", e)

    # Otherwise continue the conversation
    twiml = VoiceResponse()
    gather = Gather(
        input="speech",
        action="/process-speech",
        speech_timeout="auto"
    )
    gather.say(ai_reply[:400])
    twiml

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

conversation_state = {}

SYSTEM_PROMPT = """
You are a friendly restaurant reservation assistant...
(unchanged - keep your full prompt here)
"""


@app.get("/")
def home():
    return {"status": "ok", "message": "AI reservation system running"}


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

    twiml.say("Sorry, I didn't hear that. Goodbye.")
    twiml.hangup()

    return Response(content=str(twiml), media_type="application/xml")


@app.post("/process-speech", response_class=Response)
async def process_speech(request: Request):
    form = await request.form()

    speech_text = form.get("SpeechResult", "").strip()
    call_sid = form.get("CallSid", "unknown")

    print(f"\nCALL {call_sid} - USER SAID: {speech_text}")

    if call_sid not in conversation_state:
        conversation_state[call_sid] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    if not speech_text:
        twiml = VoiceResponse()
        gather = Gather(
            input="speech",
            action=f"{BASE_URL}/process-speech"
        )
        gather.say("Sorry, I didn't hear that. Could you repeat?")
        twiml.append(gather)
        return Response(content=str(twiml), media_type="application/xml")

    conversation_state[call_sid].append(
        {"role": "user", "content": speech_text}
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=conversation_state[call_sid],
            temperature=0.3
        )
        ai_reply = response.choices[0].message.content.strip()
    except Exception as e:
        ai_reply = "Sorry, I had a problem. Could you repeat that?"

    print("AI REPLY:", ai_reply)

    conversation_state[call_sid].append(
        {"role": "assistant", "content": ai_reply}
    )

    if ai_reply.startswith("{"):
        try:
            data = json.loads(ai_reply)

            if data.get("status") == "complete":
                conversation_state.pop(call_sid, None)

                twiml = VoiceResponse()
                twiml.say(
                    f"Thank you {data['name']}. Your reservation for "
                    f"{data['party_size']} guests on {data['date']} at "
                    f"{data['time']} is confirmed."
                )
                twiml.hangup()
                return Response(content=str(twiml), media_type="application/xml")
        except:
            pass

    twiml = VoiceResponse()
    gather = Gather(
        input="speech",
        action=f"{BASE_URL}/process-speech",
        speech_timeout="auto"
    )
    gather.say(ai_reply[:400])
    twiml.append(gather)

    return Response(content=str(twiml), media_type="application/xml")

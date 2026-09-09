import io
from urllib import response
import wave
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from google.genai import types
response

#ติดตั้ง FastAPI 
app = FastAPI()

#ปลดล้อก cors ให้หน้าเว็บ ส่งข้อมูลมาหา pythonได้
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = "API_KEY_HERE"
client = genai.Client(api_key=GEMINI_API_KEY)

#คำสั่งเอไอ
SYSTEM_PROMPT = """
I assign you the role of a young American guy who likes to chat and joke around, using everyday slang and a bit of Thai. You're friendly and caring but don't always have to be polite. Sometimes you can tease like best buddies do (keep it brief: 2-3 sentences, some profanity is okay). Adapt to the other person and act like a foreign friend who helps out when they accidentally speak Thai or can't find the right words in English, kind of like a friend teaching a friend. You can also sneak in grammar tips if they say something that sounds super unnatural (like if a native speaker heard it, they wouldn't understand). Don't forget to be a caring friend if the user shares their plans with you; this info will be in the "task_name" section, and try to respond in English.

Analyze the user's input simultaneously and ALWAYS respond in valid JSON format using the exact structure below:

{
  "reply": "Your normal conversational response to the user",
  "vocabularies": [{"word": "New/Interesting word", "meaning": "Thai translation"}],
  "errors": [{"user_said": "Incorrect phrase", "correct": "Corrected phrase", "explanation": "Brief explanation in Thai"}],
  "tasks": [{"task_name": "User's plan OR suggested practice task"}]
}

Very important: If there are no new vocabularies, errors, or tasks, return empty arrays `[]` for those fields. Do NOT include any introductory or concluding text outside the JSON object.
"""

# ==========================================
# 1. ส่วน LLM (คุยโต้ตอบ)
# ==========================================
class ChatRequest(BaseModel):
    user_message: str

import json
import re
import sqlite3

# เชื่อมต่อกับSQlite3
def save_analysis_to_db(data):
    conn = sqlite3.connect('User_data.db')
    cursor = conn.cursor()

    #insert ข้อมูลจากเว็บลงในตาราง
    try:
        #บันทึกข้อมูลลงในตาราง Vocabularies
        for item in data.get("vocabularies", []):
            cursor.execute(
                "INSERT INTO Vocabularies (word, meaning) VALUES (?, ?)",
                (item.get("word"), item.get("meaning"))
            )

        #บันทึกข้อมูลจุดที่ผิดแกรมม่า (common_errors)
        for item in data.get("errors",[]):
            cursor.execute(
                "INSERT INTO common_errors (user_said, correct_version, explanation) VALUES (?, ?, ?)",
                (item.get("user_said"), item.get("correct_version"), item.get("explanation"))
            )

        #บันทึกข้อมูล task
        for item in data.get("tasks", []):
            cursor.execute(
                "INSERT INTO tasks (task_name, is_completed) VALUES (?, ?)",
                (item.get("task_name"), 0)   
            )

        #ยืนยันการบันทึกข้อมูล
        conn.commit()
        print("💾บันทึกข้อมูลลง SQLite เรียบร้อยแล้ว")

    except Exception as e:
        print("❌ เกิดข้อผิดพลาดในการบันทึกข้อมูลลง SQLite:", str(e))
        conn.rollback() #ยกเลิกการเปลี่ยนแปลงหากเกิดข้อผิดพลาด
    finally:
        conn.close() #ปิดการเชื่อมฐานข้อมูล  

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    print("📥 [RECEIVED] ได้รับข้อความจากหน้าเว็บแล้ว:", request.user_message)
    try:
        # บังคับให้ Gemini คืนค่าเป็น JSON ผ่าน response_mime_type
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=request.user_message,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json"  # ✨ ล็อคให้ Gemini คืนค่าเป็น JSON เท่านั้น
            )
        )

        raw_response = response.text.strip()

        try:
            # 1. ลองแปลง JSON ปกติ
            data = json.loads(raw_response)
            user_reply = data.get("reply", "")
            print("คัดแยก JSON สำเร็จ! เตรียมบันทึกลง DB...")
        except json.JSONDecodeError:
            # 2. กรณี JSON โดนตัดตอน ให้ใช้ Regex แกะเฉพาะข้อความใน "reply" ออกมา
            match = re.search(r'"reply"\s*:\s*"(.*?)"(?=,\s*"|\s*}|$)', raw_response, re.DOTALL)
            if match:
                user_reply = match.group(1).replace('\\"', '"')
            else:
                user_reply = raw_response  # กันพลาดกรณีแกะไม่ได้จริงๆ

            data = {
                "reply": user_reply,
                "vocabularies": [],
                "errors": [],
                "tasks": []
            }
        #บันทึกข้อมูลลง SQLite
        save_analysis_to_db(data)
            
        
        print("📤 [SENT] ตอบกลับข้อความไปยังหน้าเว็บ:", user_reply)

        #ส่งข้อมูลกลับไปยังหน้าเว็บ
        return JSONResponse(content=data)

    except Exception as e:
        print("❌ ERROR เกิดขึ้นตรงนี้:", str(e))
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)



# ==========================================   
# 2. ส่วน TTS (แปลงข้อความ AI เป็นเสียงพูด)
# ==========================================
def _call_gemini_tts(text: str) -> bytes:
    response = client.models.generate_content(
        model="gemini-3.1-flash-tts-preview", # หรือโมเดลที่รองรับ Audio output
        contents=f"Please read this text aloud naturally: {text}",
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Puck", # 🎙️ สามารถเปลี่ยนชื่อเสียงตรงนี้ได้!
                    )
                )
            ),
        ),
    )
    return response.candidates[0].content.parts[0].inline_data.data

@app.post("/api/tts")
async def tts_endpoint(request: Request):
    body = await request.json()
    text = body.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "No text provided."}, status_code=400)

    try:
        # แปลงเสียงใน Background Thread เพื่อไม่ให้เซิร์ฟเวอร์ค้าง
        pcm_data = await asyncio.to_thread(_call_gemini_tts, text)

        # ครอบไฟล์ PCM ดิบ ให้กลายเป็นไฟล์ .wav ที่เบราว์เซอร์เปิดเล่นได้ทันที
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)    # 16-bit
            wf.setframerate(24000) # 24kHz
            wf.writeframes(pcm_data)

        return Response(content=wav_buffer.getvalue(), media_type="audio/wav")
    except Exception as e:
        print("❌ [TTS ERROR]:", str(e))
        return JSONResponse({"error": str(e)}, status_code=500) 

# คำสั่งสั่งรันเซิร์ฟเวอร์เมื่อกดรันไฟล์นี้
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001) 




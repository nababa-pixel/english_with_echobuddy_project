import io
import wave
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from google.genai import types

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

GEMINI_API_KEY = "API_KEY"
client = genai.Client(api_key=GEMINI_API_KEY)

#พอมเอไอ
SYSTEM_PROMPT = """
I assign you the role of a young American guy who likes to chat and joke around, using everyday slang and a bit of Thai. You're friendly and caring but don't always have to be polite. Sometimes you can tease like best buddies do (keep it brief: 2-3 sentences, some profanity is okay). Adapt to the other person and act like a foreign friend who helps out when they accidentally speak Thai or can't find the right words in English, kind of like a friend teaching a friend. You can also sneak in grammar tips if they say something that sounds super unnatural (like if a native speaker heard it, they wouldn't understand). Don't forget to be a caring friend if the user shares their plans with you; this info will be in the "task_name" section, and try to respond in English.

Analyze the user's input simultaneously and ALWAYS respond in valid JSON format using the exact structure below:

{
  "reply": "Your normal conversational response to the user",
  "vocabularies": [{"word": "New/Interesting word", "meaning": "Thai translation", 
  "part_of_speech": "noun/verb/adjective/adverb", "phonetic": "IPA pronunciation e.g. /pəˈreɪ.daɪm/"}]
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

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "User_data.db"

# เชื่อมต่อกับSQlite3
def save_analysis_to_db(data):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    #insert ข้อมูลจากเว็บลงในตาราง
    try:
        #บันทึกข้อมูลลงในตาราง Vocabularies
        for item in data.get("vocabularies", []):
            cursor.execute(
                "INSERT INTO Vocabularies (word, meaning, part_of_speech, phonetic, status) VALUES (?, ?, ?, ?, ?)",
                (item.get("word"), item.get("meaning"), item.get("part_of_speech"), item.get("phonetic"), "New")
            )

        #บันทึกข้อมูลจุดที่ผิดแกรมม่า (common_errors)
        for item in data.get("errors",[]):
            cursor.execute(
                "INSERT INTO common_errors (user_said, correct, explanation) VALUES (?, ?, ?)",
                (item.get("user_said"), item.get("correct"), item.get("explanation"))
            )

        #บันทึกข้อมูล task
        for item in data.get("tasks", []):
            cursor.execute(
                "INSERT INTO tasks (task_name, is_completed) VALUES (?, ?)",
                (item.get("task_name"), 0)   
            )

       
        conn.commit()
        print("💾บันทึกข้อมูลลง SQLite เรียบร้อยแล้ว")

    except Exception as e:
        print("❌ เกิดข้อผิดพลาดในการบันทึกข้อมูลลง SQLite:", str(e))
        conn.rollback() 
    finally:
        conn.close() 

import time
from google.genai import errors

def generate_with_retry(**kwargs):
    
    models = ["gemini-3-flash-preview", "gemini-2.5-flash"]
    last_error = None

    for model in models:
        for attempt in range(3):
            try:
                return client.models.generate_content(model=model, **kwargs)
            except errors.APIError as e:
                
                if e.code in (429, 500, 503, 504):
                    last_error = e
                    time.sleep(2 ** attempt) 
                else:
                    raise
    raise last_error

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    print("📥 [RECEIVED] ได้รับข้อความจากหน้าเว็บแล้ว:", request.user_message)
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT task_name FROM tasks WHERE is_completed = 0 LIMIT 5")
        pending_tasks = [row[0] for row in cursor.fetchall()]
        conn.close()

        context_note = f"\n(ผู้ใช้มี task ค้างอยู่: {', '.join(pending_tasks)}. ถ้าเหมาะสม ให้ถามหรือเตือนเรื่องนี้แบบเป็นกันเองได้)" if pending_tasks else ""
       
        response = await asyncio.to_thread(
            generate_with_retry,
            contents=request.user_message + context_note,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json"
            )
        )

        raw_response = response.text.strip()

        try:
            
            data = json.loads(raw_response)
            user_reply = data.get("reply", "")
            print("คัดแยก JSON สำเร็จ! เตรียมบันทึกลง DB...")
        except json.JSONDecodeError:
            #กรณี JSON โดนตัดตอน ให้ใช้ Regex แกะเฉพาะข้อความใน "reply" ออกมา
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

@app.get("/api/insights")
async def get_insights():
    conn = sqlite3.connect(DB_PATH)  
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # นับคำศัพท์ใหม่เดือนนี้
    cursor.execute("""
        SELECT COUNT(*) as count FROM Vocabularies
        WHERE created_at >= date('now', 'start of month')
    """)
    vocab_count = cursor.fetchone()["count"]

    # ดึง 10 ข้อผิดพลาดล่าสุด
    cursor.execute("""
        SELECT user_said, correct, explanation
        FROM common_errors
        ORDER BY created_at DESC LIMIT 10
    """)
    mistakes = [dict(row) for row in cursor.fetchall()]
    

    conn.close()

    return JSONResponse(content={
        "vocab_count": vocab_count,
        "mistakes": mistakes
    })

# ---------- ดึงรายการ task ที่ยังไม่เสร็จ ----------
@app.get("/api/tasks")
async def get_tasks():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, task_name, is_completed, created_at
        FROM tasks
        ORDER BY created_at DESC
        LIMIT 10
    """)
    tasks = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return JSONResponse(content={"tasks": tasks})


# ---------- ติ๊กว่า task เสร็จแล้ว/ยังไม่เสร็จ ----------
class TaskUpdateRequest(BaseModel):
    is_completed: bool

@app.patch("/api/tasks/{task_id}")
async def update_task(task_id: int, request: TaskUpdateRequest):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE tasks SET is_completed = ? WHERE id = ?",
        (1 if request.is_completed else 0, task_id)
    )
    conn.commit()
    conn.close()

    return JSONResponse(content={"status": "ok", "task_id": task_id})


# ==========================================   
# 2. ส่วน TTS (แปลงข้อความ AI เป็นเสียงพูด)
# ==========================================
def _call_gemini_tts(text: str) -> bytes:
    last_error = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-preview-tts",
                contents=f"Please read this text aloud naturally: {text}",
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name="Puck",
                            )
                        )
                    ),
                ),
            )
            return response.candidates[0].content.parts[0].inline_data.data
        except errors.APIError as e:
            if e.code in (429, 500, 503, 504) and attempt < 2:
                last_error = e
                time.sleep(1)
            else:
                raise
    raise last_error

 

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

#==========================================
#=============แสดงรายการ page2==============
#==========================================
@app.get("/api/insights")
async def get_insights():
    conn = sqlite3.connect(DB_PATH)  
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # นับคำศัพท์ใหม่เดือนนี้
    cursor.execute("""
        SELECT COUNT(*) as count FROM Vocabularies
        WHERE created_at >= date('now', 'start of month')
    """)
    vocab_count = cursor.fetchone()["count"]

    # ดึง 10 ข้อผิดพลาดล่าสุด
    cursor.execute("""
        SELECT user_said, correct_version, explanation
        FROM common_errors
        ORDER BY created_at DESC LIMIT 10
    """)
    mistakes = [dict(row) for row in cursor.fetchall()]
    for m in mistakes:
        m["correct"] = m.pop("correct_version")  # ให้ key ตรงกับที่ frontend ใช้

    conn.close()

    return JSONResponse(content={
        "vocab_count": vocab_count,
        "mistakes": mistakes
    })

#==========================================
#============Proflie page3=================
#==========================================

# ---------- ดึงคำศัพท์ทั้งหมด ----------
@app.get("/api/vocabulary")
async def get_vocabulary():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, word, meaning, part_of_speech, phonetic, status, created_at
        FROM Vocabularies
        ORDER BY created_at DESC
    """)
    words = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return JSONResponse(content={"words": words})


# ---------- เพิ่มคำศัพท์เอง (ปุ่ม + Add New Word) ----------
class NewVocabRequest(BaseModel):
    word: str
    meaning: str
    part_of_speech: str | None = None
    phonetic: str | None = None

@app.post("/api/vocabulary")
async def add_vocabulary(request: NewVocabRequest):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO Vocabularies (word, meaning, part_of_speech, phonetic, status) VALUES (?, ?, ?, ?, ?)",
        (request.word, request.meaning, request.part_of_speech, request.phonetic, "New")
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()

    return JSONResponse(content={"status": "ok", "id": new_id})

# คำสั่งสั่งรันเซิร์ฟเวอร์เมื่อกดรันไฟล์นี้
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000) 





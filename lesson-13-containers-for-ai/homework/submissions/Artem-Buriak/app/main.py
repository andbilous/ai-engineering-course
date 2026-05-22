"""
FastAPI service — /health liveness + /ask LLM endpoint.

Environment variables:
  OPENROUTER_API_KEY  — required
  LLM_MODEL           — default: openai/gpt-4o-mini
"""

import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel

load_dotenv()

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
API_KEY = os.getenv("OPENROUTER_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")

client = AsyncOpenAI(api_key=API_KEY, base_url=OPENROUTER_BASE)

app = FastAPI(title="Ask API", version="1.0.0")


class AskRequest(BaseModel):
    question: str
    system: Optional[str] = "You are a helpful assistant. Answer in detail."


class AskResponse(BaseModel):
    answer: str
    model: str
    status: str = "ok"


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not set")
    if not req.question.strip():
        raise HTTPException(status_code=422, detail="question cannot be empty")

    completion = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": req.system},
            {"role": "user", "content": req.question},
        ],
    )
    return AskResponse(
        answer=completion.choices[0].message.content,
        model=LLM_MODEL,
    )

"""FastAPI app. Run from the repo root:  uvicorn backend.main:app --reload --port 8000"""

import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router

load_dotenv()
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="fakta.ai backend")
# shortcut: any origin allowed for local dev (Vite on :5173 etc.); restrict before deploying publicly
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)

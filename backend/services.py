# services.py
import os
import httpx
import json
import base64
from datetime import datetime
from typing import List, Dict, Any

import firebase_admin
from firebase_admin import credentials, firestore, storage
from fastapi import UploadFile, HTTPException
from dotenv import load_dotenv

load_dotenv()

# --- Configurações ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FIREBASE_STORAGE_BUCKET = os.environ.get("FIREBASE_STORAGE_BUCKET")

# --- Inicialização do Firebase ---
try:
    cred = credentials.Certificate("firebase-credentials.json")
    firebase_admin.initialize_app(cred, {'storageBucket': FIREBASE_STORAGE_BUCKET})
    db = firestore.client()
    bucket = storage.bucket()
except Exception as e:
    print(f"AVISO: Não foi possível inicializar o Firebase. Erro: {e}")
    db, bucket = None, None

def encode_image_to_base64(file: UploadFile) -> Dict[str, str]:
    content = file.file.read()
    encoded_data = base64.b64encode(content).decode('utf-8')
    return {"mime_type": file.content_type, "data": encoded_data}

class GeminiService:
    GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
    @staticmethod
    async def generate_content(payload: Dict[str, Any]) -> str:
        if not GEMINI_API_KEY:
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY não configurada.")
        headers = {"Content-Type": "application/json"}
        params = {"key": GEMINI_API_KEY}
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(GeminiService.GEMINI_API_URL, json=payload, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
                if "candidates" in data and data["candidates"]:
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                raise HTTPException(status_code=500, detail="Resposta inválida da API Gemini.")
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=f"Erro na API Gemini: {e.response.text}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro inesperado no Gemini Service: {str(e)}")

class FirebaseService:
    @staticmethod
    async def upload_images(files: List[UploadFile]) -> List[str]:
        if not bucket: raise HTTPException(status_code=500, detail="Firebase Storage não inicializado.")
        urls = []
        for file in files:
            filename = f"sinistros/{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
            blob = bucket.blob(filename)
            file.file.seek(0)
            blob.upload_from_file(file.file, content_type=file.content_type)
            blob.make_public()
            urls.append(blob.public_url)
        return urls
    @staticmethod
    async def save_document(collection: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if not db: raise HTTPException(status_code=500, detail="Firestore não inicializado.")
        data['timestamp'] = firestore.SERVER_TIMESTAMP
        doc_ref = db.collection(collection).document()
        doc_ref.set(data)
        data['id'] = doc_ref.id
        data['timestamp'] = str(data['timestamp'])
        return data
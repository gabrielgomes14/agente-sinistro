import os
import base64
import httpx
from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List

# --- Pydantic Model for Chat Request ---
# Defines the expected structure for a chat query
class ChatQuery(BaseModel):
    question: str

# Initialize the FastAPI application
app = FastAPI(title="Assistente de Frota IA API")

# --- CORS Middleware Configuration ---
# Allowing all origins for flexibility during development and deployment
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# --- Gemini API Configuration ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

# --- Helper Function for Image Encoding ---
def encode_image_to_base64(file: UploadFile) -> Dict[str, str]:
    """Reads an uploaded file and encodes it to a Base64 string."""
    try:
        content = file.file.read()
        encoded_data = base64.b64encode(content).decode('utf-8')
        return {"mime_type": file.content_type, "data": encoded_data}
    finally:
        file.file.close()

# ==========================================================
#  ENDPOINT 1: CHAT DE GESTÃO DE FROTAS
# ==========================================================
@app.post("/chat", summary="Conversational Fleet Management Expert")
async def chat_with_fleet_expert(query: ChatQuery) -> Dict[str, str]:
    """
    Receives a question from a driver, frames it with an expert prompt,
    and returns Gemini's answer on fleet management.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not set.")

    # This prompt instructs the AI on its personality and expertise
    expert_prompt = f"""
    Aja como um especialista em gestão de frotas chamado "Assistente de Frota IA".
    Sua função é fornecer conselhos claros, práticos e úteis para motoristas.
    Seu tom deve ser amigável, profissional e direto.
    Responda à seguinte pergunta do condutor: "{query.question}"
    """

    payload = {
        "contents": [{"parts": [{"text": expert_prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "topP": 1.0,
            "maxOutputTokens": 2048,
        }
    }
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(GEMINI_API_URL, json=payload, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            if "candidates" in data and data["candidates"]:
                text_content = data["candidates"][0]["content"]["parts"][0]["text"]
                return {"answer": text_content}

            raise HTTPException(status_code=500, detail="Could not extract content from Gemini API response.")

    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Error from Gemini API: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")


# ==========================================================
#  ENDPOINT 2: ANÁLISE DE SINISTROS (Existente)
# ==========================================================
@app.post("/analisar", summary="Analyze Vehicle Damage Images")
async def analisar(
    imagem: List[UploadFile] = Form(...),
    localizacao: str = Form(...),
    modelo: str = Form(...),
    ano: str = Form(...),
    relato_motorista: str = Form(...)
) -> Dict[str, Any]:
    """
    Analyzes vehicle damage images and returns a structured JSON report.
    (This endpoint remains unchanged)
    """
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not set.")

    prompt = f"""
    Você é um especialista em análise de sinistros de veículos. Analise as imagens de um {modelo} ano {ano} e o relato do motorista.
    Localização para cotação: {localizacao}.
    Relato: {relato_motorista}.
    
    Forneça uma análise estruturada em JSON com a seguinte estrutura:
    {{
      "analiseGeral": {{ "nivelDano": "...", "nivelUrgencia": "...", "areaVeiculo": "..." }},
      "descricaoDanos": "...",
      "coerenciaRelato": "...",
      "pecasNecessarias": [ {{"nome": "...", "custo": 123.45}} ],
      "estimativas": {{ "tempoReparo": "..." }}
    }}
    
    IMPORTANTE: Forneça custos realistas em Reais (BRL) para {localizacao}. A resposta deve ser apenas o JSON.
    """
    image_parts = [{"inline_data": encode_image_to_base64(file)} for file in imagem]
    
    payload = {
        "contents": [{"parts": [{"text": prompt}, *image_parts]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
        }
    }
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(GEMINI_API_URL, json=payload, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            if "candidates" in data and data["candidates"]:
                text_content = data["candidates"][0]["content"]["parts"][0]["text"]
                return {"descricao": text_content}
            
            raise HTTPException(status_code=500, detail="Could not extract content from Gemini API response.")
    
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Error from Gemini API: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")
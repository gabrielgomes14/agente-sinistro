import os
import base64
import httpx
from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List

# Initialize the FastAPI application
app = FastAPI(title="Vehicle Damage Analysis API")

# --- CORS Middleware Configuration (AJUSTADO PARA PRODUÇÃO) ---
origins = [
    "https://ecar-agente.web.app", # Domínio do seu frontend
    "http://127.0.0.1:5500",     # Para desenvolvimento local
    "http://localhost:5500",
    "http://localhost:8080",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["POST"],
    allow_headers=["*"],
)

# --- Gemini API Configuration (MODELO ATUALIZADO) ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
# Usando o modelo Flash mais recente recomendado
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# --- Helper Function ---
def encode_image_to_base64(file: UploadFile) -> Dict[str, str]:
    """Reads an uploaded file and encodes it to a Base64 string, returning a dictionary."""
    try:
        content = file.file.read()
        encoded_data = base64.b64encode(content).decode('utf-8')
        return {"mime_type": file.content_type, "data": encoded_data}
    finally:
        file.file.close()

# --- API Endpoint ---
@app.post("/analisar", summary="Analyze Vehicle Damage Images")
async def analisar(
    imagem: List[UploadFile] = Form(...),
    localizacao: str = Form(...),
    modelo: str = Form(...),
    ano: str = Form(...),
    relato_motorista: str = Form(...)
) -> Dict[str, Any]:
    """
    This endpoint receives multiple images of vehicle damage, location, car model,
    and a driver's report. It sends this data to the Gemini API for analysis
    and returns the model's structured JSON description.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY environment variable not set."
        )

    # 1. Construct the prompt for the AI internally
    prompt = f"""
      Você é um especialista em análise de sinistros de veículos. Sua tarefa é analisar as imagens de um carro danificado, o relato do motorista e a sua localização.
      O carro é um {modelo} ano {ano}.
      A localização para cotação de peças e serviços é: {localizacao}.
      
      Baseado nas imagens e no relato, forneça uma análise estruturada em JSON. O JSON deve ter a seguinte estrutura e nada mais:
      {{
        "analiseGeral": {{ "nivelDano": "...", "nivelUrgencia": "...", "areaVeiculo": "..." }},
        "descricaoDanos": "...",
        "coerenciaRelato": "...",
        "pecasNecessarias": [ {{"nome": "...", "custo": 123.45}} ],
        "estimativas": {{ "tempoReparo": "..." }}
      }}
      
      IMPORTANTE: Forneça estimativas de custo realistas em Reais (BRL) para o Brasil, considerando a localização informada ({localizacao}). A resposta deve ser apenas o JSON.
    """

    # 2. Encode all uploaded images to Base64
    image_parts = []
    for file in imagem:
        encoded_image = encode_image_to_base64(file)
        image_parts.append({"inline_data": encoded_image})

    # 3. Construct the payload for the Gemini API
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    *image_parts, # Unpack all image parts here
                    {"text": f"Adicionalmente, considere o seguinte relato do motorista: {relato_motorista}"}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.5,
            "topP": 1.0,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json", # Request a JSON response directly
        }
    }

    headers = { "Content-Type": "application/json" }
    params = { "key": GEMINI_API_KEY }

    # 4. Make the asynchronous API call to Gemini
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(GEMINI_API_URL, json=payload, headers=headers, params=params)
            response.raise_for_status()

            data = response.json()
            
            if "candidates" in data and data["candidates"]:
                first_candidate = data["candidates"][0]
                if "content" in first_candidate and "parts" in first_candidate["content"]:
                    text_content = "".join(part.get("text", "") for part in first_candidate["content"]["parts"])
                    return {"descricao": text_content}

            raise HTTPException(
                status_code=500,
                detail="Could not extract content from Gemini API response."
            )

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Error from Gemini API: {e.response.text}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {str(e)}"
        )
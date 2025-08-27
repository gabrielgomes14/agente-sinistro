# main.py
import json
from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List

from models import ChatQuery, MaintenanceReport
from services import (
    GeminiService, 
    FirebaseService, 
    encode_image_to_base64
)

app = FastAPI(
    title="Assistente de Frota IA 🦾 (Final)",
    description="API para chat, análise de sinistros e digitalização de despesas.",
    version="9.0.0"
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/", tags=["Root"])
def root():
    return {"message": "API Assistente de Frota IA v9.0 funcionando!"}

@app.post("/chat", tags=["Conversacional"])
# ... (código do endpoint /chat inalterado)

@app.post("/analisar-sinistro", tags=["Sinistros"])
# ... (código do endpoint /analisar-sinistro inalterado)

@app.post("/relatar-manutencao", tags=["Manutenção"])
# ... (código do endpoint /relatar-manutencao inalterado)

@app.post("/analisar-recibo", tags=["Despesas"])
async def analisar_recibo(imagem: UploadFile = Form(...)):
    prompt = f"""
    Aja como um assistente de finanças especialista em digitalizar recibos e notas fiscais para gestão de frotas.
    Analise a imagem fornecida e extraia as seguintes informações:
    - estabelecimento: O nome do local.
    - cnpj: O CNPJ do estabelecimento, se visível.
    - data: A data da transação no formato DD/MM/AAAA.
    - categoria: Classifique a despesa em uma das seguintes categorias: "Combustível", "Alimentação", "Pedágio", "Manutenção", "Hospedagem", "Outros".
    - valor_total: O valor total pago, como uma string no formato "XX,XX".

    Se uma informação não for encontrada, retorne null para o campo correspondente.
    Retorne **APENAS e SOMENTE** um objeto JSON válido.
    """
    
    image_part = {"inline_data": encode_image_to_base64(imagem)}
    payload = { "contents": [{"parts": [{"text": prompt}, image_part]}], "generationConfig": {"responseMimeType": "application/json"} }
    
    try:
        analysis_text = await GeminiService.generate_content(payload)
        analysis_json = json.loads(analysis_text)
        
        image_url = await FirebaseService.upload_images([imagem])
        analysis_json['imageUrl'] = image_url[0] if image_url else None
        
        saved_data = await FirebaseService.save_document("despesas", analysis_json)
        
        return saved_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro inesperado ao analisar o recibo: {str(e)}")
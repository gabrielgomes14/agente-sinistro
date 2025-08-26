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

# --- Inicialização da App FastAPI ---
app = FastAPI(
    title="Assistente de Frota IA 🦾 (Simplificado)",
    description="API para chat e análise de sinistros com Firebase.",
    version="5.0.0"
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- Endpoints da API ---

@app.get("/", tags=["Root"])
def root():
    return {"message": "API Assistente de Frota IA v5.0 funcionando!"}

@app.post("/chat", tags=["Conversacional"])
async def chat_with_fleet_expert(query: ChatQuery):
    prompt = f'Aja como um especialista em gestão de frotas chamado "Assistente de Frota IA". Seu tom deve ser amigável, profissional e direto. Responda à seguinte pergunta do condutor: "{query.question}"'
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    answer = await GeminiService.generate_content(payload)
    return {"answer": answer}

@app.post("/analisar-sinistro", tags=["Sinistros"])
async def analisar_sinistro(imagens: List[UploadFile] = Form(...), localizacao: str = Form(...), modelo: str = Form(...), ano: str = Form(...), relato_motorista: str = Form(...)):
    prompt = f'Você é um perito em sinistros de veículos. Analise as imagens de um {modelo} {ano} e o relato: "{relato_motorista}". A cotação deve ser baseada na região de {localizacao}, Brasil. Retorne **apenas** um JSON com: analiseGeral (nivelDano, nivelUrgencia, areaVeiculo), descricaoDanos, coerenciaRelato, pecasNecessarias (lista de nome e custo), estimativas (tempoReparo, custoTotal), carModel. Use valores em Reais (BRL).'
    image_parts = [{"inline_data": encode_image_to_base64(file)} for file in imagens]
    payload = { "contents": [{"parts": [{"text": prompt}, *image_parts]}], "generationConfig": {"responseMimeType": "application/json"} }
    
    analysis_text = await GeminiService.generate_content(payload)
    analysis_json = json.loads(analysis_text)
    
    image_urls = await FirebaseService.upload_images(imagens)
    analysis_json['imageUrls'] = image_urls
    analysis_json['status'] = "Pendente"
    
    saved_data = await FirebaseService.save_document("sinistros", analysis_json)
    return saved_data

@app.post("/relatar-manutencao", tags=["Manutenção"])
async def report_maintenance(report: MaintenanceReport):
    prompt = f'Aja como um mecânico especialista. Analise o relato para o veículo {report.vehicle_id} com {report.current_km} km: "{report.driver_report}". Retorne um JSON com: diagnostico_preliminar, componentes_provaveis (lista de strings), nivel_urgencia ("Baixa", "Média", "Alta", "Crítica - Parar Imediatamente"), acao_recomendada.'
    payload = { "contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"} }
    
    analysis_text = await GeminiService.generate_content(payload)
    analysis_json = json.loads(analysis_text)
    
    analysis_json.update({"vehicle_id": report.vehicle_id, "driver_report": report.driver_report, "km": report.current_km, "status": "Aberto"})
    
    saved_data = await FirebaseService.save_document("manutencao", analysis_json)
    return saved_data
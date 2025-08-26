# main.py
import json
from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List

from models import ChatQuery, RouteOptimizationRequest, MaintenanceReport
from services import (
    GeminiService, 
    FirebaseService, 
    RoutingService,
    encode_image_to_base64
)

app = FastAPI(
    title="Assistente de Frota IA 🦾 (OpenCage Edition)",
    description="API com otimização de rotas (OpenCage + ORS) e salvamento de dados no Firebase.",
    version="4.1.0"
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

routing_service = RoutingService()

@app.get("/", tags=["Root"])
def root():
    return {"message": "API Assistente de Frota IA v4.1 funcionando com OpenCage!"}

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

@app.post("/otimizar-e-salvar-rota", summary="Calcula a rota, gera um resumo e salva no Firestore", tags=["Otimização"])
async def optimize_and_save_route(request: RouteOptimizationRequest) -> Dict[str, Any]:
    
    all_addresses = [request.origin] + [stop.address for stop in request.stops] + [request.destination]
    
    try:
        coordinates = await routing_service.geocode_addresses_with_opencage(all_addresses)
        if None in coordinates:
            failed_address = all_addresses[coordinates.index(None)]
            raise HTTPException(status_code=400, detail=f"OpenCage não encontrou coordenadas para: '{failed_address}'")
            
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno durante a geocodificação: {str(e)}")

    if len(coordinates) < 2:
        raise HTTPException(status_code=400, detail="É necessário fornecer pelo menos dois endereços válidos (origem e destino) para calcular uma rota.")

    try:
        route_data = await routing_service.get_route_with_ors(coordinates)
        if 'features' not in route_data or not route_data['features']:
            error_message = route_data.get('error', {}).get('message', 'Ponto inacessível ou rota inválida.')
            raise HTTPException(status_code=400, detail=f"Erro do OpenRouteService ao calcular a rota: {error_message}")
        
        summary = route_data['features'][0]['properties']['summary']
        distance_km = round(summary['distance'] / 1000, 2)
        duration_min = round(summary['duration'] / 60)

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar os dados da rota: {str(e)}")

    summary_prompt = f"""Crie um resumo amigável para um motorista sobre a rota planejada.
    - Nome da Rota: {request.routeName}
    - Origem: {request.origin}
    - Destino: {request.destination}
    - Paradas: {', '.join([s.address for s in request.stops])}
    - Distância: {distance_km} km
    - Duração: {duration_min} minutos
    O resumo deve ser breve e claro."""
    payload = {"contents": [{"parts": [{"text": summary_prompt}]}]}
    natural_summary = await GeminiService.generate_content(payload)
    
    route_to_save = {
        "routeName": request.routeName, "origin": request.origin, "destination": request.destination,
        "stops": [stop.dict() for stop in request.stops], "status": "Planejada",
        "natural_summary": natural_summary,
        "route_data": {
            "total_distance_km": distance_km, "total_duration_minutes": duration_min,
            "coordinates_used": coordinates
        }
    }

    saved_route = await FirebaseService.save_document("rotas", route_to_save)
    return saved_route
# main.py (Versão completa com Mapas e Firebase)
import json
from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List

# Importa os modelos e os serviços completos
from models import ChatQuery, RouteOptimizationRequest, MaintenanceReport
from services import (
    GeminiService, 
    FirebaseService, 
    RoutingService, # <-- Alterado aqui
    encode_image_to_base64
)

# --- Inicialização da App FastAPI ---
app = FastAPI(
    title="Assistente de Frota IA 🦾 (Completo)",
    description="API com otimização de rotas (Nominatim + ORS) e salvamento de dados no Firebase.",
    version="2.1.0" # <-- Versão atualizada
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Instancia o novo serviço de roteirização
routing_service = RoutingService() # <-- Alterado aqui

# --- Endpoints da API ---

@app.get("/", tags=["Root"])
def root():
    return {"message": "API Assistente de Frota IA v2.1 funcionando com Nominatim!"}

# ... (Endpoints /chat, /analisar-sinistro, /relatar-manutencao permanecem inalterados) ...
@app.post("/chat", tags=["Conversacional"])
async def chat_with_fleet_expert(query: ChatQuery):
    # ... (código inalterado)
    prompt = f"""
    Aja como um especialista em gestão de frotas chamado "Assistente de Frota IA".
    Seu tom deve ser amigável, profissional e direto.
    Responda à seguinte pergunta do condutor: "{query.question}"
    """
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    answer = await GeminiService.generate_content(payload)
    return {"answer": answer}

@app.post("/analisar-sinistro", tags=["Sinistros"])
async def analisar_sinistro(imagens: List[UploadFile] = Form(...), localizacao: str = Form(...), modelo: str = Form(...), ano: str = Form(...), relato_motorista: str = Form(...)):
    # ... (código inalterado)
    prompt = f"""
    Você é um perito em sinistros de veículos. Analise as imagens de um {modelo} {ano} e o relato: "{relato_motorista}".
    A cotação deve ser baseada na região de {localizacao}, Brasil.
    Retorne **apenas** um JSON com: analiseGeral (nivelDano, nivelUrgencia, areaVeiculo), descricaoDanos, 
    coerenciaRelato, pecasNecessarias (lista de nome e custo), estimativas (tempoReparo, custoTotal), carModel.
    Use valores em Reais (BRL).
    """
    image_parts = [{"inline_data": encode_image_to_base64(file)} for file in imagens]
    payload = {
        "contents": [{"parts": [{"text": prompt}, *image_parts]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    analysis_text = await GeminiService.generate_content(payload)
    analysis_json = json.loads(analysis_text)
    
    image_urls = await FirebaseService.upload_images(imagens)
    analysis_json['imageUrls'] = image_urls
    analysis_json['status'] = "Pendente"
    
    saved_data = await FirebaseService.save_document("sinistros", analysis_json)
    return saved_data


@app.post("/relatar-manutencao", tags=["Manutenção"])
async def report_maintenance(report: MaintenanceReport):
    # ... (código inalterado)
    prompt = f"""
    Aja como um mecânico especialista. Analise o relato para o veículo {report.vehicle_id} com {report.current_km} km:
    "{report.driver_report}"
    Retorne um JSON com: diagnostico_preliminar, componentes_provaveis (lista de strings), 
    nivel_urgencia ("Baixa", "Média", "Alta", "Crítica - Parar Imediatamente"), acao_recomendada.
    """
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    analysis_text = await GeminiService.generate_content(payload)
    analysis_json = json.loads(analysis_text)
    
    analysis_json.update({
        "vehicle_id": report.vehicle_id,
        "driver_report": report.driver_report,
        "km": report.current_km,
        "status": "Aberto"
    })
    
    saved_data = await FirebaseService.save_document("manutencao", analysis_json)
    return saved_data

@app.post("/otimizar-e-salvar-rota", summary="Calcula a rota, gera um resumo e salva no Firestore", tags=["Otimização"])
async def optimize_and_save_route(request: RouteOptimizationRequest) -> Dict[str, Any]:
    
    all_addresses = [request.origin] + [stop.address for stop in request.stops] + [request.destination]
    
    try:
        # Usa o novo serviço para geocodificar com Nominatim
        coordinates = await routing_service.geocode_addresses_with_nominatim(all_addresses) # <-- Alterado aqui
        if None in coordinates:
            failed_address = all_addresses[coordinates.index(None)]
            raise HTTPException(status_code=400, detail=f"Nominatim não encontrou coordenadas para: '{failed_address}'")
    except Exception as e:
         raise HTTPException(status_code=500, detail=f"Erro durante a geocodificação: {str(e)}")

    try:
        # O cálculo da rota ainda usa o ORS, que é excelente para isso
        route_data = await routing_service.get_route_with_ors(coordinates) # <-- Alterado aqui
        summary = route_data['features'][0]['properties']['summary']
        distance_km = round(summary['distance'] / 1000, 2)
        duration_min = round(summary['duration'] / 60)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao calcular a rota: {str(e)}")

    summary_prompt = f"""
    Crie um resumo amigável para um motorista sobre a rota planejada.
    - Nome da Rota: {request.routeName}
    - Origem: {request.origin}
    - Destino: {request.destination}
    - Paradas: {', '.join([s.address for s in request.stops])}
    - Distância: {distance_km} km
    - Duração: {duration_min} minutos
    O resumo deve ser breve e claro.
    """
    payload = {"contents": [{"parts": [{"text": summary_prompt}]}]}
    natural_summary = await GeminiService.generate_content(payload)
    
    # Prepara o objeto de dados para salvar no Firestore
    route_to_save = {
        "routeName": request.routeName,
        "origin": request.origin,
        "destination": request.destination,
        "stops": [stop.dict() for stop in request.stops],
        "status": "Planejada",
        "natural_summary": natural_summary,
        "route_data": {
            "total_distance_km": distance_km,
            "total_duration_minutes": duration_min,
            "coordinates_used": coordinates
        }
    }

    # Salva o resultado em uma nova coleção "rotas"
    saved_route = await FirebaseService.save_document("rotas", route_to_save)
    
    return saved_route
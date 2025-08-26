import json
from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List

# Importa os modelos e os serviços completos
from models import ChatQuery, RouteOptimizationRequest, MaintenanceReport
from services import (
    GeminiService,
    FirebaseService,
    OpenRouteService,
    OPENROUTESERVICE_API_KEY,
    encode_image_to_base64
)

# --- Gemini API Configuration ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Instancia o serviço do ORS
ors_service = OpenRouteService(api_key=OPENROUTESERVICE_API_KEY)

# --- Endpoints da API ---

@app.get("/", tags=["Root"])
def root():
    return {"message": "API Assistente de Frota IA v2.0 funcionando!"}

@app.post("/chat", tags=["Conversacional"])
async def chat_with_fleet_expert(query: ChatQuery):
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
    prompt = f"""
    Você é um perito em sinistros de veículos. Analise as imagens de um {modelo} {ano} e o relato: "{relato_motorista}".
    A cotação deve ser baseada na região de {localizacao}, Brasil.
    Retorne **apenas** um JSON com: analiseGeral (nivelDano, nivelUrgencia, areaVeiculo), descricaoDanos, 
    coerenciaRelato, pecasNecessarias (lista de nome e custo), estimativas (tempoReparo, custoTotal), carModel.
    Use valores em Reais (BRL).
    """
    image_parts = [{"inline_data": await encode_image_to_base64(file)} for file in imagens]
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

# --- ENDPOINT DE ROTA ATUALIZADO COM SALVAMENTO ---
@app.post("/otimizar-e-salvar-rota", summary="Calcula a rota, gera um resumo e salva no Firestore", tags=["Otimização"])
async def optimize_and_save_route(request: RouteOptimizationRequest) -> Dict[str, Any]:

    all_addresses = [request.origin] + [stop.address for stop in request.stops] + [request.destination]

    try:
        coordinates = await ors_service.geocode_addresses(all_addresses)
        if None in coordinates:
            failed_address_index = coordinates.index(None)
            failed_address = all_addresses[failed_address_index]
            raise HTTPException(status_code=400, detail=f"Não foi possível encontrar coordenadas para: '{failed_address}'")
    except Exception as e:
         raise HTTPException(status_code=500, detail=f"Erro durante a geocodificação: {str(e)}")

    try:
        route_data = await ors_service.get_route(coordinates)
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

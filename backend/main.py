# main.py
import json
from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List

from models import ChatQuery, RouteOptimizationRequest, MaintenanceReport
from services import (
    GeminiService, 
    FirebaseService, 
    RoutingService
)

app = FastAPI(
    title="Assistente de Frota IA 🦾 (Nominatim Edition)",
    description="API com otimização de rotas (Nominatim + ORS) e salvamento de dados no Firebase.",
    version="3.1.0"
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

routing_service = RoutingService()

# ... (Endpoints /, /chat, /analisar-sinistro, /relatar-manutencao permanecem inalterados) ...
@app.get("/", tags=["Root"])
def root():
    return {"message": "API Assistente de Frota IA v3.1 funcionando com Nominatim!"}

# ... (código dos outros endpoints inalterado) ...

@app.post("/otimizar-e-salvar-rota", summary="Calcula a rota, gera um resumo e salva no Firestore", tags=["Otimização"])
async def optimize_and_save_route(request: RouteOptimizationRequest) -> Dict[str, Any]:
    
    all_addresses = [request.origin] + [stop.address for stop in request.stops] + [request.destination]
    
    try:
        # Chama o método de geocodificação da Nominatim
        coordinates = await routing_service.geocode_addresses_with_nominatim(all_addresses)
        if None in coordinates:
            failed_address = all_addresses[coordinates.index(None)]
            # Mensagem de erro atualizada
            raise HTTPException(status_code=400, detail=f"Nominatim não encontrou coordenadas para: '{failed_address}'")
            
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

    # O resto da função permanece igual
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
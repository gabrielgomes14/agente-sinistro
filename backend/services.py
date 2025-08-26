# services.py (Versão completa com Mapas e Firebase - Adaptado para Nominatim)
import os
import httpx
import json
import asyncio
import base64
from datetime import datetime
from typing import List, Dict, Any, Optional

import firebase_admin
from firebase_admin import credentials, firestore, storage
from fastapi import UploadFile, HTTPException
from dotenv import load_dotenv

# Carrega as variáveis de ambiente
load_dotenv()

# --- Configurações ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
FIREBASE_STORAGE_BUCKET = os.environ.get("FIREBASE_STORAGE_BUCKET")
OPENROUTESERVICE_API_KEY = os.environ.get("OPENROUTESERVICE_API_KEY")

# --- Inicialização do Firebase ---
try:
    cred = credentials.Certificate("firebase-credentials.json")
    firebase_admin.initialize_app(cred, {'storageBucket': FIREBASE_STORAGE_BUCKET})
    db = firestore.client()
    bucket = storage.bucket()
except Exception as e:
    print(f"AVISO: Não foi possível inicializar o Firebase. Erro: {e}")
    db, bucket = None, None

# --- Funções e Classes de Serviço ---

def encode_image_to_base64(file: UploadFile) -> Dict[str, str]:
    # ... (código inalterado)
    content = file.file.read()
    encoded_data = base64.b64encode(content).decode('utf-8')
    return {"mime_type": file.content_type, "data": encoded_data}

class GeminiService:
    # ... (código inalterado)
    @staticmethod
    async def generate_content(payload: Dict[str, Any]) -> str:
        if not GEMINI_API_KEY:
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY não configurada.")
        
        headers = {"Content-Type": "application/json"}
        params = {"key": GEMINI_API_KEY}
        
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(GEMINI_API_URL, json=payload, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
                if "candidates" in data and data["candidates"]:
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                raise HTTPException(status_code=500, detail="Resposta inválida da API Gemini.")
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=f"Erro na API Gemini: {e.response.text}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro inesperado: {str(e)}")

class FirebaseService:
    # ... (código inalterado)
    @staticmethod
    async def upload_images(files: List[UploadFile]) -> List[str]:
        if not bucket:
            raise HTTPException(status_code=500, detail="Firebase Storage não inicializado.")
        
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
        if not db:
            raise HTTPException(status_code=500, detail="Firestore não inicializado.")

        data['timestamp'] = firestore.SERVER_TIMESTAMP
        doc_ref = db.collection(collection).document()
        doc_ref.set(data)
        data['id'] = doc_ref.id
        # A conversão para string é necessária pois o timestamp não é serializável em JSON diretamente
        data['timestamp'] = str(data['timestamp'])
        return data

# --- CLASSE DE ROTEIRIZAÇÃO ATUALIZADA ---
class RoutingService:
    ORS_BASE_URL = "https://api.openrouteservice.org"
    NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org"

    def __init__(self):
        # A chave do ORS ainda é necessária para o cálculo da rota
        if not OPENROUTESERVICE_API_KEY:
            raise ValueError("Chave da API OpenRouteService não fornecida.")
        self.ors_api_key = OPENROUTESERVICE_API_KEY
        self.ors_headers = {'Authorization': self.ors_api_key, 'Content-Type': 'application/json'}
        # Headers para a Nominatim com o User-Agent obrigatório
        self.nominatim_headers = {'User-Agent': 'AssitenteDeFrotaIA/1.0 (seu-email@provedor.com)'}

    async def _geocode_address_with_nominatim_async(self, address: str, client: httpx.AsyncClient) -> Optional[List[float]]:
        params = {'q': address, 'format': 'jsonv2', 'limit': 1}
        try:
            # Respeitar o limite de 1 requisição por segundo da Nominatim
            await asyncio.sleep(1)
            
            response = await client.get(self.NOMINATIM_BASE_URL + "/search", params=params, headers=self.nominatim_headers)
            response.raise_for_status()
            data = response.json()
            if data:
                # Nominatim retorna lon/lat, ORS espera lon/lat. Perfeito.
                return [float(data[0]['lon']), float(data[0]['lat'])]
            return None
        except httpx.HTTPStatusError:
            return None

    async def geocode_addresses_with_nominatim(self, addresses: List[str]) -> List[Optional[List[float]]]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            tasks = [self._geocode_address_with_nominatim_async(addr, client) for addr in addresses]
            results = await asyncio.gather(*tasks)
            return results

    async def get_route_with_ors(self, coordinates: List[List[float]]) -> Dict[str, Any]:
        body = {"coordinates": coordinates}
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.ORS_BASE_URL}/v2/directions/driving-car/json",
                json=body,
                headers=self.ors_headers
            )
            response.raise_for_status()
            return response.json()
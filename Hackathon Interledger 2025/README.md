# Wallet WhatsApp Verify (Minimal)

Repo minimal para probar flujo **Lookup + Verify (WhatsApp)** usando Twilio y un backend en **FastAPI**.

## Estructura
- `backend/` - código fuente FastAPI
  - `main.py` - webhook y lógica principal
  - `models.py` - modelos SQLAlchemy
  - `twilio_client.py` - wrapper Twilio Lookup & Verify
  - `utils.py` - helpers (E.164, validate Twilio signature)
  - `requirements.txt` - dependencias
- `docker-compose.yml` - Postgres + app (opcional)
- `.env.example` - variables de entorno de ejemplo
- `.gitignore`

## Requisitos
- Docker (opcional)
- Ngrok (opcional para exponer local)
- Cuenta Twilio con Verify Service y WhatsApp sandbox/number
- Python 3.10+ recommended

## Cómo probar localmente (rápido)
1. Copia `.env.example` a `.env` y llena las variables con tus credenciales Twilio y DB.
2. Levanta Postgres o usa Docker Compose:
   ```bash
   docker-compose up -d
   ```
3. Instala dependencias e inicia la app:
   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```
4. Expone tu app con ngrok o deploy en un host con HTTPS:
   ```bash
   ngrok http 8000
   ```
5. En Twilio Console > Messaging > WhatsApp, configura "A MESSAGE COMES IN" con:
   `https://<tu-ngrok>/webhook/whatsapp`
6. Envía mensajes desde WhatsApp al número Twilio para probar.

## Notas
- Este repo es **minimal**: implementa exactamente lo pedido: **every message → Lookup + Verify**. 
- NO guardar OTPs en BD. Solo logs y verify_sid/status.
- En producción: añadir TLS, rate limits, migraciones y tests.

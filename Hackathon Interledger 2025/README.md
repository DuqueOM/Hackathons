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

## Arquitectura

- **Canal de entrada**: Webhook de WhatsApp vía Twilio (`POST /webhook/whatsapp`) implementado en `backend/main.py`.
- **Verificación de identidad**: Twilio Verify + Lookup (`backend/twilio_client.py`) y validación de firma (`backend/utils.py`).
- **NLU**: `backend/nlu.py` expone `parse_text` y soporta proveedor rule-based, OpenAI-compatible o Rasa según `NLU_PROVIDER`.
- **Core bancario mock**: `backend/bank_client.py` simula un core bancario con dos modos (`BANK_CLIENT_MODE=local|http`).
- **Persistencia**: `backend/models.py` define `User`, `Wallet`, `Transaction`, `LookupLog`, `VerifyLog`, `PendingRequest`.
- **Inicialización DB**: `backend/init_db.py` crea tablas y un usuario/wallet demo.
- **Pruebas**: `backend/tests/` cubre NLU, `bank_client` (local/http), API, seguridad y Twilio.

## Requisitos
- Docker (opcional)
- Ngrok (opcional para exponer local)
- Cuenta Twilio con Verify Service y WhatsApp sandbox/number
- Python 3.10+ recommended

## Configuración de variables de entorno

Las variables de entorno recomendadas están documentadas en `.env.example`. Resumen:

- **Twilio**:
  - `TWILIO_API_KEY`, `TWILIO_API_KEY_SECRET`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`
  - `VERIFY_SERVICE_SID`: servicio de Twilio Verify para OTP vía WhatsApp.
  - `TWILIO_WHATSAPP_FROM`: número remitente WhatsApp (opcional, según configuración de Twilio).
- **Base de datos**:
  - `DATABASE_URL`: URL SQLAlchemy. Ejemplo local con Postgres: `postgresql://postgres:postgres@localhost:5432/walletdb`.
- **Secrets de app**:
  - `HMAC_SECRET`, `JWT_SECRET`: claves para firmar tokens/HMAC.
- **OTP / rate limiting**:
  - `OTP_MAX_ATTEMPTS`, `OTP_LOCK_MINUTES`.
  - `RATE_LIMIT_WHATSAPP_PER_MINUTE`, `RATE_LIMIT_VERIFY_PER_MINUTE`.
- **NLU**:
  - `NLU_PROVIDER` (`rule`, `openai` o `rasa`).
  - `NLU_OPENAI_API_BASE`, `NLU_OPENAI_API_KEY`, `NLU_OPENAI_MODEL`.
  - `NLU_RASA_URL`.
- **Core bancario (modo HTTP)**:
  - `BANK_CLIENT_MODE` (`local` o `http`).
  - `BANK_API_BASE_URL`, `BANK_API_TOKEN_URL`, `BANK_API_CLIENT_ID`, `BANK_API_CLIENT_SECRET`, `BANK_API_SCOPE`.
  - `BANK_API_TLS_CA`, `BANK_API_TLS_CERT`, `BANK_API_TLS_KEY`.

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
- Este repo es **minimal**: implementa flujo WhatsApp + Lookup + Verify + intents básicos.
- No se almacenan **OTPs** en BD. Solo logs con `verify_sid` y `status`.
- En producción: añadir TLS obligatorio (idealmente mTLS hacia core bancario), rate limits y endurecer políticas de seguridad.

## Endpoints principales

- `POST /webhook/whatsapp`
  - Webhook de Twilio (WhatsApp). Valida `X-Twilio-Signature` y orquesta Lookup + Verify.

- `POST /api/v1/verify/send`
  - Envía un OTP vía WhatsApp usando Twilio Verify.

- `POST /api/v1/verify/check`
  - Verifica el OTP y marca al usuario como `verified` si es correcto.

- `POST /api/v1/nlu/parse`
  - NLU interno (rule-based) para intents `consultar_saldo` y `transferir`.

- `GET /api/v1/accounts/{user_id}/balance`
  - Consulta de saldo mock contra `bank_client`.

- `POST /api/v1/transfers`
  - Crea una transferencia mock con idempotencia (`client_tx_id`) y flag `requires_2fa` según umbral.

## Cómo correr tests

Dentro de `backend/`:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

Los tests incluyen:

- **Unit tests NLU**: parsing de intents y entidades.
- **Unit tests bank_client**: saldo, transferencias e idempotencia.
- **Tests API**: endpoints `/api/v1/*` con `TestClient`.
- **Tests de integración Twilio**: uso de `responses` para simular Twilio Verify.

## Ejecución con Docker Compose (app + DB)

Si prefieres no instalar Python localmente, puedes levantar app y base de datos en contenedores:

```bash
cp .env.example .env  # ajusta credenciales reales
docker-compose up --build
```

Puntos a considerar:
- El servicio `db` usa las credenciales definidas en `docker-compose.yml`.
- El servicio `app` toma `DATABASE_URL` y secretos desde tu `.env`.
- La API quedará disponible en `http://localhost:8000`.

## Ejemplos cURL

Asumiendo que la app corre en `http://localhost:8000`.

### Enviar OTP (Verify Send)

```bash
curl -X POST http://localhost:8000/api/v1/verify/send \
  -H "Content-Type: application/json" \
  -d '{"phone": "+521234567890", "channel": "whatsapp"}'
```

### Verificar OTP (Verify Check)

```bash
curl -X POST http://localhost:8000/api/v1/verify/check \
  -H "Content-Type: application/json" \
  -d '{"phone": "+521234567890", "code": "123456"}'
```

### Ejemplo Lookup directo contra Twilio (fuera de la API)

> Nota: este ejemplo pega directo a Twilio Lookup API usando tus credenciales.

```bash
PHONE="+521234567890"
curl -u "$TWILIO_API_KEY:$TWILIO_API_KEY_SECRET" \
  "https://lookups.twilio.com/v2/PhoneNumbers/$PHONE?Type=carrier&Type=line_type_intelligence"
```

### NLU parse

```bash
curl -X POST http://localhost:8000/api/v1/nlu/parse \
  -H "Content-Type: application/json" \
  -d '{"text": "Quiero transferir 150.50 a 012345678901234567"}'
```

### Transferencia mock con idempotencia

```bash
USER_ID="<uuid-de-usuario>"  # puedes usar el creado por init_db.py
curl -X POST http://localhost:8000/api/v1/transfers \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "'$USER_ID'",
    "amount": 200.0,
    "destination_account": "012345678901234567",
    "client_tx_id": "cli-tx-001"
  }'
```

## Despliegue en Kubernetes

En el directorio `k8s/` hay manifiestos de ejemplo:

- `deployment.yaml`: Deployment para la app FastAPI.
- `service.yaml`: Service tipo `ClusterIP` exponiendo el puerto 8000 como 80 dentro del cluster.

Pasos típicos:

- Construye y publica una imagen Docker propia (por ejemplo, la misma que se construye en CI).
- Actualiza el campo `image:` en `k8s/deployment.yaml` con tu imagen real (`ghcr.io/<org>/<repo>:<tag>`).
- Crea los secretos requeridos:
  - `wallet-db-secret` con la clave `DATABASE_URL`.
  - `wallet-twilio-secret` con `TWILIO_API_KEY`, `TWILIO_API_KEY_SECRET`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `VERIFY_SERVICE_SID`.
- Aplica los manifiestos:
  ```bash
  kubectl apply -f k8s/deployment.yaml
  kubectl apply -f k8s/service.yaml
  ```

Luego expón el Service (Ingress o LoadBalancer) y usa esa URL pública en Twilio para configurar el webhook de WhatsApp.

## CI/CD (GitHub Actions)

Este repo incluye un workflow en `.github/workflows/ci.yml` que:

- Ejecuta linting con `ruff` sobre `backend/`.
- Levanta Postgres en GitHub Actions y corre los tests (`pytest -q`).
- Construye una imagen Docker de la app (simulación de push a un registry).

Puedes extenderlo para publicar la imagen en tu registro y disparar despliegues en Kubernetes.

## Twilio Sandbox + ngrok (E2E rápido)

1. Levanta el backend (Docker o local) en `localhost:8000`.
2. Expón el puerto con ngrok:
   ```bash
   ngrok http 8000
   ```
3. Copia la URL HTTPS (`https://xxxxx.ngrok.io`).
4. En Twilio Console > Messaging > WhatsApp Sandbox, configura **A MESSAGE COMES IN** a:
   ```
   https://xxxxx.ngrok.io/webhook/whatsapp
   ```
5. Sigue las instrucciones del sandbox (enviar código de join desde tu WhatsApp).
6. Envía mensajes como:
   - `Saldo`
   - `Transferir 150 a 012345678901234567`
7. El flujo hará Lookup + Verify + ejecución mock según el intent.

## Checklist mínima PCI/OpenBanking

- **Segregación de secretos**
  - [x] Secretos (Twilio, DB, JWT, HMAC) via variables de entorno (`.env` / secretos K8s).
  - [ ] Rotación y gestión centralizada de secretos (p.ej. Vault/KMS).

- **Protección de credenciales/OTP**
  - [x] No se persisten OTPs en BD, solo `verify_sid` y `status` de Twilio Verify.
  - [x] Validación de `X-Twilio-Signature` en webhooks.

- **Transporte seguro**
  - [ ] Forzar HTTPS en todos los entornos (recomendado: reverse proxy tipo Nginx/Ingress con TLS).
  - [ ] mTLS hacia el core bancario cuando se reemplace `bank_client` mock por API real.

- **Autorización y límites**
  - [x] Rate limiting básico por número para `/webhook/whatsapp` y `/api/v1/verify/*` (configurable vía variables de entorno).
  - [x] Bloqueo temporal de cuenta tras múltiples intentos fallidos de OTP.
  - [ ] Rate limiting adicional por IP a nivel reverse proxy/API gateway.

- **Auditoría**
  - [x] Logs de Lookup (`LookupLog`) y Verify (`VerifyLog`) con timestamp.
  - [ ] Log de operaciones de transferencia/auditoría extendida para OpenBanking.

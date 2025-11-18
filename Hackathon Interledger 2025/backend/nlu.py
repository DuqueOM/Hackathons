"""NLU adapter for WhatsApp banking.

This module exposes a simple interface `parse_text` that returns a
normalized intent and entities. For now it implements a rule-based
parser for two intents:
- consultar_saldo
- transferir

Later this can be extended to call external NLU engines (OpenAI
compatible APIs or a Rasa server) based on configuration.
"""

import json
import os
import re
from typing import Any, Dict

import httpx

INTENT_CONSULTAR_SALDO = "consultar_saldo"
INTENT_TRANSFERIR = "transferir"
INTENT_DESCONOCIDO = "desconocido"

NLU_PROVIDER = os.getenv("NLU_PROVIDER", "rule").lower()


def _normalize(text: str) -> str:
    return (text or "").strip().lower()


def _parse_rule(text: str) -> Dict[str, Any]:
    """Rule-based parser for common intents.

    Returns a dict similar to Rasa / OpenAI tool-style output:
    {
      "intent": {"name": str, "confidence": float},
      "entities": {...},
      "text": original_text
    }
    """

    original = text or ""
    t = _normalize(original)

    # Detect consultar saldo
    if any(kw in t for kw in ["saldo", "balance"]):
        return {
            "intent": {"name": INTENT_CONSULTAR_SALDO, "confidence": 0.95},
            "entities": {},
            "text": original,
        }

    # Detect transfer intent with amount + destination
    if any(kw in t for kw in ["transferir", "enviar", "pagar"]):
        amount = None
        dest = None

        m_amount = re.search(r"(\d+[\.,]\d{1,2}|\d+)", t)
        if m_amount:
            amount_str = m_amount.group(1).replace(",", ".")
            try:
                amount = float(amount_str)
            except ValueError:
                amount = None

        # simplistic detection of CLABE or account number
        m_dest = re.search(r"(\d{14,20})", t)
        if m_dest:
            dest = m_dest.group(1)

        entities = {}
        if amount is not None:
            entities["amount"] = amount
        if dest is not None:
            entities["destination_account"] = dest

        return {
            "intent": {"name": INTENT_TRANSFERIR, "confidence": 0.9},
            "entities": entities,
            "text": original,
        }

    # Unknown intent
    return {
        "intent": {"name": INTENT_DESCONOCIDO, "confidence": 0.3},
        "entities": {},
        "text": original,
    }


def _parse_openai(text: str) -> Dict[str, Any]:
    """Parse text using an OpenAI-compatible chat completions API.

    Expects the model to return a JSON object with the same structure
    as the rule-based parser. If anything goes wrong, the caller
    should fall back to the rule-based implementation.
    """

    api_base = os.getenv("NLU_OPENAI_API_BASE", "https://api.openai.com/v1")
    api_key = os.getenv("NLU_OPENAI_API_KEY")
    model = os.getenv("NLU_OPENAI_MODEL", "gpt-3.5-turbo")

    if not api_key:
        raise RuntimeError("NLU_OPENAI_API_KEY not set")

    url = f"{api_base.rstrip('/')}/chat/completions"

    system_prompt = (
        "You are an NLU engine for a banking chatbot over WhatsApp. "
        "Given the user message, you MUST respond with a JSON object with keys "
        "'intent', 'entities', and 'text'. 'intent' must be an object with keys "
        "'name' and 'confidence'. 'name' MUST be one of: "
        f"'{INTENT_CONSULTAR_SALDO}', '{INTENT_TRANSFERIR}', "
        f"'{INTENT_DESCONOCIDO}'. 'entities' must be an object that may contain "
        "'amount' (number) and 'destination_account' (string). "
        "Return JSON only, no extra text."
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text or ""},
        ],
        "temperature": 0,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    resp = httpx.post(url, headers=headers, json=payload, timeout=10.0)
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("no choices in OpenAI-compatible response")
    content = choices[0].get("message", {}).get("content") or ""
    try:
        parsed = json.loads(content)
    except Exception:
        # If the model did not return pure JSON, fall back to rule-based.
        return _parse_rule(text)

    if "text" not in parsed:
        parsed["text"] = text
    return parsed


def _parse_rasa(text: str) -> Dict[str, Any]:
    """Parse text using a Rasa NLU HTTP endpoint.

    Expects the standard /model/parse response and converts it to the
    internal representation.
    """

    rasa_url = os.getenv("NLU_RASA_URL", "http://localhost:5005/model/parse")
    resp = httpx.post(rasa_url, json={"text": text or ""}, timeout=5.0)
    resp.raise_for_status()
    data = resp.json()

    intent = data.get("intent") or {}
    name = intent.get("name") or INTENT_DESCONOCIDO
    confidence = float(intent.get("confidence") or 0.0)

    entities_list = data.get("entities") or []
    entities: Dict[str, Any] = {}
    for ent in entities_list:
        key = ent.get("entity")
        value = ent.get("value")
        if key and value is not None:
            entities[key] = value

    return {
        "intent": {"name": name, "confidence": confidence},
        "entities": entities,
        "text": data.get("text") or (text or ""),
    }


def parse_text(text: str) -> Dict[str, Any]:
    """Main entry point: selects provider and applies fallbacks.

    Provider is chosen via the NLU_PROVIDER env var:
    - "rule"   (default): always use the internal rule-based parser.
    - "openai": try OpenAI-compatible API, then fall back to Rasa, then rule.
    - "rasa"  : try Rasa, then fall back to rule.
    """

    provider = NLU_PROVIDER

    if provider == "openai":
        try:
            return _parse_openai(text)
        except Exception:
            # Fallback chain: Rasa -> rule
            try:
                return _parse_rasa(text)
            except Exception:
                return _parse_rule(text)

    if provider == "rasa":
        try:
            return _parse_rasa(text)
        except Exception:
            return _parse_rule(text)

    # default: rule-based
    return _parse_rule(text)

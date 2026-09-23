"""Replaceable model boundary. Demo mode is explicit, never an AI fallback."""
import asyncio
import json
import re
from urllib.parse import urlparse
import httpx


class ModelUnavailable(RuntimeError):
    pass


def public_error(exc):
    # Never persist raw provider/transport errors: they can include credentials or URLs.
    if isinstance(exc, ModelUnavailable):
        return str(exc)
    if isinstance(exc, (ValueError, KeyError)):
        return "Model output or referenced data failed validation; inspect the run and retry."
    return "Processing failed (" + type(exc).__name__ + "); retry or inspect local configuration."


class CloudModel:
    def __init__(self, settings):
        self.settings = settings
        self.name = settings.model
        self.configured = bool(settings.api_key)

    def generate(self, step, system, context, schema):
        if not self.configured:
            raise ModelUnavailable("Set LLM_API_KEY in DeepNotes/.env and restart, then retry failed jobs.")
        parsed = urlparse(self.settings.base_url)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")):
            raise ModelUnavailable("LLM_BASE_URL must use HTTPS or local loopback HTTP.")
        try:
            return asyncio.run(self._request(system, context, schema))
        except (httpx.TimeoutException, TimeoutError):
            raise ModelUnavailable("Model request timed out; retry later.") from None
        except httpx.HTTPError:
            raise ModelUnavailable("Could not contact model provider; check connection and configuration.") from None
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise ModelUnavailable("Model provider returned an unsupported response format.") from None

    async def _request(self, system, context, schema):
        payload = {"model": self.name, "messages": [
            {"role": "system", "content": system + "\nReturn only JSON matching this schema:\n" + json.dumps(schema)},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
            "response_format": {"type": "json_object"}, "temperature": 0.2, "max_tokens": 6000}
        # Cancellation covers connect + headers + the ENTIRE response, not just inactivity.
        async with asyncio.timeout(self.settings.timeout):
            async with httpx.AsyncClient(timeout=self.settings.timeout, follow_redirects=False, trust_env=False) as client:
                async with client.stream("POST", self.settings.base_url + "/chat/completions",
                                         headers={"Authorization": "Bearer " + self.settings.api_key}, json=payload) as response:
                    if response.status_code != 200:
                        raise ModelUnavailable(f"Model provider returned HTTP {response.status_code}; check configuration or retry.")
                    buffer = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(buffer) + len(chunk) > 2_000_000:
                            raise ModelUnavailable("Model response exceeded the response size limit.")
                        buffer.extend(chunk)
                    body = json.loads(buffer)
                    raw = body["choices"][0]["message"]["content"]
                    if not isinstance(raw, str):
                        raise ModelUnavailable("Model provider did not return text content.")
                    return raw, body.get("usage", {})


class DemoModel:
    """Deterministic wiring demonstration, not meaningful knowledge extraction."""
    name = "DEMO (no AI calls)"
    configured = True

    def generate(self, step, system, context, schema):
        if step == "organize":
            text = context["entry"]["current"]["content"]
            available = context["catalog"]["overview"]
            selected = [c["id"] for c in available if c["id"] != "unclassified" and c["name"].lower() in text.lower()][:1]
            data = {"summary": text[:300], "intent": "demo-note", "class_ids": selected or ["unclassified"], "concepts": [], "relations": [], "rationale": "DEMO: text echoed; no AI interpretation performed.", "clarification": "Add entry or section context if you want to clarify its purpose."}
        elif step == "structure":
            data = {"upserts": [], "remove_ids": [], "rationale": "DEMO: no automatic structure changes.", "support_entry_ids": [], "support_guidance_ids": []}
        elif step == "plan":
            data = {"terms": re.findall(r"\w+", context["question"])[:12], "class_ids": [], "intent": "demo lookup"}
        else:
            notes = context["notes"]
            data = {"answer": "DEMO — this verifies the application flow, not AI answer quality. " + ("Related saved material: " + notes[0]["content"][:400] if notes else "No matching saved notes were found."), "coverage": "partial" if notes else "none", "general_knowledge": False, "explanation": "Deterministic demo output; no model knowledge or live web search was used.", "cited_entry_ids": [notes[0]["id"]] if notes else []}
        return json.dumps(data), {"demo": True}

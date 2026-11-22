"""Azure OpenAI adapter.

The agent loop speaks a tiny provider-neutral dialect (the shape the Anthropic Messages API uses):
    messages : user str | assistant [blocks] | user [tool_result dicts]
    response : .content [text|tool_use blocks], .stop_reason, .usage.input_tokens/output_tokens
This adapter translates that dialect to/from Azure OpenAI **Chat Completions** (function calling), so the
agent, policy, tools, guardrails and tests do not change when you switch provider. That is the point of
isolating the model behind `create(system, messages, tools)`.

AUTH (in order):
  1. AZURE_OPENAI_API_KEY                         - quick start / local dev only
  2. Microsoft Entra ID via DefaultAzureCredential - PRODUCTION: managed identity, no secret to leak or rotate.
     Needs role "Cognitive Services OpenAI User" on the Azure OpenAI resource.
     With a user-assigned identity set AZURE_CLIENT_ID to its client id.
CONFIG: AZURE_OPENAI_ENDPOINT (https://<resource>.openai.azure.com), AZURE_OPENAI_DEPLOYMENT (the DEPLOYMENT
name, not the model name), AZURE_OPENAI_API_VERSION (GA data-plane version; check docs for the current one).
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace as NS

from .config import Settings

COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"
DEFAULT_API_VERSION = "2024-10-21"


def _get(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


# ----------------------------------------------------------------------------- request translation
def to_openai_tools(tools: list[dict], strict: bool = True) -> list[dict]:
    """Our tool schema -> OpenAI function tools. strict=True makes the API guarantee arguments match the schema
    (requires additionalProperties:false and all properties listed in `required` - our tools already comply)."""
    out = []
    for t in tools:
        fn = {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}
        if strict:
            fn["strict"] = True
        out.append({"type": "function", "function": fn})
    return out


def to_openai_messages(system: str, messages: list) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        role, content = m["role"], m["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        if role == "assistant":
            text = "".join(_get(b, "text", "") for b in content if _get(b, "type") == "text")
            calls = [
                {"id": _get(b, "id"), "type": "function",
                 "function": {"name": _get(b, "name"), "arguments": json.dumps(_get(b, "input", {}))}}
                for b in content if _get(b, "type") == "tool_use"
            ]
            msg: dict = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
            continue

        # user content blocks: tool results become role=tool messages (must directly follow the assistant
        # tool_calls message); text / image blocks become one user message.
        parts: list[dict] = []
        for b in content:
            t = _get(b, "type")
            if t == "tool_result":
                body = _get(b, "content", "")
                body = body if isinstance(body, str) else json.dumps(body)
                if _get(b, "is_error"):
                    body = f"ERROR: {body}"
                out.append({"role": "tool", "tool_call_id": _get(b, "tool_use_id"), "content": body})
            elif t == "text":
                parts.append({"type": "text", "text": _get(b, "text", "")})
            elif t == "image":
                src = _get(b, "source", {})
                url = f"data:{src['media_type']};base64,{src['data']}"
                parts.append({"type": "image_url", "image_url": {"url": url}})
            else:
                raise ValueError(f"unsupported content block for Azure OpenAI chat: {t!r}")
        if parts:
            out.append({"role": "user", "content": parts})
    return out


# ----------------------------------------------------------------------------- response translation
def from_openai_response(resp) -> NS:
    choice = resp.choices[0]
    msg = choice.message
    blocks: list[NS] = []
    if getattr(msg, "content", None):
        blocks.append(NS(type="text", text=msg.content))
    for tc in getattr(msg, "tool_calls", None) or []:
        try:
            args = json.loads(tc.function.arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be an object")
        except (ValueError, TypeError):
            args = {"__invalid_json__": tc.function.arguments}     # fails schema -> tool returns a readable error
        blocks.append(NS(type="tool_use", id=tc.id, name=tc.function.name, input=args))

    finish = choice.finish_reason
    if getattr(msg, "refusal", None) or finish == "content_filter":
        stop = "refusal"
    elif any(b.type == "tool_use" for b in blocks):
        stop = "tool_use"
    elif finish == "length":
        stop = "max_tokens"
    else:
        stop = "end_turn"

    u = getattr(resp, "usage", None)
    details = getattr(u, "prompt_tokens_details", None)
    usage = NS(
        input_tokens=getattr(u, "prompt_tokens", 0) or 0,
        output_tokens=getattr(u, "completion_tokens", 0) or 0,
        cache_read_input_tokens=getattr(details, "cached_tokens", 0) or 0,
    )
    return NS(content=blocks, stop_reason=stop, usage=usage, model=getattr(resp, "model", None), id=getattr(resp, "id", None))


def _refusal_response(reason: str) -> NS:
    """Azure can reject a PROMPT with HTTP 400 code=content_filter. Surface it like a model refusal."""
    return NS(content=[], stop_reason="refusal", usage=NS(input_tokens=0, output_tokens=0, cache_read_input_tokens=0),
              model=None, id=None, refusal_reason=reason)


# ----------------------------------------------------------------------------- client
def build_azure_client():
    from openai import AzureOpenAI
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    common = dict(azure_endpoint=endpoint, api_version=os.getenv("AZURE_OPENAI_API_VERSION", DEFAULT_API_VERSION),
                  max_retries=3, timeout=120.0)           # SDK retries 408/409/429/5xx with backoff (honours Retry-After)
    key = os.getenv("AZURE_OPENAI_API_KEY")
    if key:
        return AzureOpenAI(api_key=key, **common)
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    provider = get_bearer_token_provider(DefaultAzureCredential(), COGNITIVE_SCOPE)
    return AzureOpenAI(azure_ad_token_provider=provider, **common)


class AzureOpenAILLM:
    def __init__(self, settings: Settings, client=None):
        self.s = settings
        self.client = client or build_azure_client()
        self.strict_tools = os.getenv("AZURE_OPENAI_STRICT_TOOLS", "1") == "1"
        self.reasoning_effort = os.getenv("AZURE_OPENAI_REASONING_EFFORT")   # only for o-series / gpt-5 deployments

    def create(self, system: str, messages: list, tools: list):
        kwargs = dict(
            model=self.s.model,                                   # = Azure DEPLOYMENT name
            messages=to_openai_messages(system, messages),
            max_completion_tokens=self.s.max_tokens,
        )
        if tools:
            kwargs["tools"] = to_openai_tools(tools, self.strict_tools)
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        try:
            return from_openai_response(self.client.chat.completions.create(**kwargs))
        except Exception as e:  # noqa: BLE001 - narrow by attribute, SDK import is optional
            if getattr(e, "code", None) == "content_filter":      # openai.BadRequestError from Azure content filter
                return _refusal_response("prompt blocked by Azure content filter")
            raise

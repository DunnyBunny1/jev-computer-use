"""Opt-in, bounded fallback for short structured writer requests.

Provider credentials are bound to fixed provider endpoints. A working provider
stays selected; an unsuccessful request tries each remaining provider once.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass

import anthropic
import openai

from .openai_writer import OpenAIWriter


@dataclass
class Endpoint:
    name: str
    client: object
    model: str
    reasoning: str | None = None


class FallbackWriter:
    def __init__(self, endpoints: list[Endpoint]):
        if not endpoints:
            raise ValueError("No configured writer provider has an API key")
        self.endpoints = endpoints
        self.active = 0
        self.disabled: set[int] = set()
        self.events: list[dict] = []
        self.messages = self

    @contextmanager
    def effort(self, level, *, expert=False):
        previous = [(endpoint.model, endpoint.reasoning) for endpoint in self.endpoints]
        try:
            for endpoint in self.endpoints:
                if "gpt-5.4-mini" in endpoint.model:
                    endpoint.reasoning = level
                    if expert:
                        endpoint.model = endpoint.model.replace("gpt-5.4-mini", "gpt-5.4")
            yield
        finally:
            for endpoint, original in zip(self.endpoints, previous, strict=True):
                endpoint.model, endpoint.reasoning = original

    @property
    def base_url(self):
        return self.endpoints[self.active].client.base_url

    def create(self, **kwargs):
        from .writer import WriterError, checked, parse_json

        for offset in range(len(self.endpoints)):
            index = (self.active + offset) % len(self.endpoints)
            if index in self.disabled:
                continue
            endpoint = self.endpoints[index]
            request = {**kwargs, "model": endpoint.model}
            request.pop("reasoning", None)
            request.pop("thinking", None)
            if endpoint.name == "fireworks":
                request["reasoning"] = "none"
            elif endpoint.reasoning and endpoint.name in {"openai", "openrouter"}:
                request["reasoning"] = endpoint.reasoning
            started = time.perf_counter()
            event = {"provider": endpoint.name, "model": endpoint.model, "reasoning": request.get("reasoning")}
            try:
                response = endpoint.client.messages.create(**request)
                usage = getattr(response, "usage", None)
                if usage:
                    event["tokens"] = {
                        name: getattr(usage, name, 0) or 0
                        for name in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
                    }
                text = "".join(block.text for block in response.content if block.type == "text")
                properties = request["output_config"]["format"]["schema"]["properties"]
                checked(parse_json(text), properties)
            except (anthropic.APIError, openai.APIError, WriterError) as exc:
                # Never log exception text: providers can echo headers or prompts.
                event.update(status="failed", error_type=type(exc).__name__)
                status = getattr(exc, "status_code", None)
                if status in {401, 402, 403, 404, 429}:
                    self.disabled.add(index)
            else:
                event["status"] = "ok"
                self.active = index
                return response
            finally:
                event["wall_ms"] = round((time.perf_counter() - started) * 1000, 1)
                self.events.append(event)
        raise WriterError("All configured writer providers failed; see sanitized writer events")


def from_env(*, planner: bool = False) -> FallbackWriter:
    providers = {
        "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4.1-nano"),
        "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com", "claude-haiku-4-5"),
        "fireworks": (
            "FIREWORKS_API_KEY",
            "https://api.fireworks.ai/inference/v1",
            "accounts/fireworks/models/deepseek-v4p1-flash",
        ),
        "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1", "openai/gpt-4.1-nano"),
    }
    endpoints = []
    order = os.environ.get("CLICKER_PLANNER_PROVIDERS") if planner else None
    order = order or os.environ.get("CLICKER_WRITER_PROVIDERS", "openai,anthropic,fireworks,openrouter")
    for name in dict.fromkeys(order.split(",")):
        name = name.strip()
        if name not in providers:
            raise ValueError(f"Unknown writer provider: {name}")
        key_name, url, default_model = providers[name]
        key = os.environ.get(key_name)
        if not key:
            continue
        if planner and name in {"openai", "openrouter"}:
            default_model = "gpt-5.4-mini" if name == "openai" else "openai/gpt-5.4-mini"
        model = os.environ.get(f"CLICKER_{'PLANNER_' if planner else ''}{name.upper()}_MODEL", default_model)
        client = (
            anthropic.Anthropic(api_key=key, base_url=url, max_retries=0, timeout=20)
            if name == "anthropic"
            else OpenAIWriter(url, key, max_retries=0, timeout=20)
        )
        effort = os.environ.get("CLICKER_PLANNER_REASONING", "low" if "gpt-5.4-mini" in model else "") if planner else None
        endpoints.append(Endpoint(name, client, model, effort))
    return FallbackWriter(endpoints)

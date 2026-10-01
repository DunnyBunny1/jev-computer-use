"""Provider selection and inference-only failover for the upstream model protocol."""

import os
from dataclasses import fields, replace


def funding_error(exc):
    status = getattr(exc, "status_code", None)
    message = str(exc).lower()
    return status in {401, 402, 403, 429} or (
        status in {400, 412}
        and any(
            word in message
            for word in ("credit balance", "insufficient credit", "billing", "quota", "spending limit", "invoices")
        )
    )


class ModelChain:
    """Only retry inference on unavailable credentials/funding, never browser actions."""

    _verified_api_keys = True

    def __init__(self, models):
        if not models:
            raise ValueError("Configure a Fireworks, OpenRouter, OpenAI or Anthropic API key")
        self.models = models
        self.index = 0
        self.failovers = []

    @property
    def model(self):
        return self.models[self.index].model

    @property
    def provider(self):
        return self.models[self.index].provider

    def limited(self, tokens):
        models = []
        for model in self.models[self.index :]:
            field_names = {f.name for f in fields(model)}
            key = "max_completion_tokens" if "max_completion_tokens" in field_names else "max_tokens"
            models.append(replace(model, **{key: tokens}))
        return ModelChain(models)

    async def ainvoke(self, messages, **kwargs):
        while True:
            try:
                return await self.models[self.index].ainvoke(messages, **kwargs)
            except Exception as exc:
                if not funding_error(exc) or self.index + 1 == len(self.models):
                    raise
                self.failovers.append({"model": self.model, "status": getattr(exc, "status_code", None)})
                self.index += 1


def make_models():
    # Imports stay inside the isolated upstream environment.
    from browser_use import ChatAnthropic, ChatOpenAI
    from browser_use_policy import omit_empty_cache_control

    class GatewayAnthropic(ChatAnthropic):
        async def _create_message(self, **params):
            params = omit_empty_cache_control(params)
            betas = params.pop("betas", None)
            async with self.get_client() as client:
                if betas is not None:
                    return await client.beta.messages.create(**params, betas=betas)
                return await client.messages.create(**params)

    selected = os.environ.get("BROWSER_USE_PROVIDER")
    providers = [selected] if selected else ["fireworks", "openrouter", "openai", "anthropic"]
    vision, writers, inspectors = [], [], []
    for provider in providers:
        if provider not in {"fireworks", "openrouter", "openai", "anthropic"}:
            raise ValueError("Unsupported BROWSER_USE_PROVIDER")
        key = os.environ.get(provider.upper() + "_API_KEY")
        if not key:
            continue
        defaults = {
            "fireworks": ("accounts/fireworks/models/kimi-k3", "accounts/fireworks/models/deepseek-v4p1-flash"),
            "openrouter": ("openai/gpt-5.4", "openai/gpt-4.1-mini"),
            "openai": ("gpt-5.4", "gpt-4.1-mini"),
            "anthropic": ("claude-sonnet-4-6", "claude-haiku-4-5-20251001"),
        }
        names = [
            os.environ.get(f"BROWSER_USE_{provider.upper()}_{suffix}", default)
            for suffix, default in zip(("MODEL", "TEXT_MODEL"), defaults[provider], strict=True)
        ]
        if selected:
            names = [
                os.environ.get("BROWSER_USE_" + suffix, name) for suffix, name in zip(("MODEL", "TEXT_MODEL"), names, strict=True)
            ]
        if provider == "anthropic":
            pair = [
                ChatAnthropic(
                    model=name, api_key=key, max_retries=0, timeout=35 if i == 0 else 15, max_tokens=4096 if i == 0 else 1024
                )
                for i, name in enumerate(names)
            ]
        else:
            base = {
                "fireworks": "https://api.fireworks.ai/inference/v1",
                "openrouter": "https://openrouter.ai/api/v1",
                "openai": "https://api.openai.com/v1",
            }[provider]
            pair = [
                ChatOpenAI(
                    model=name,
                    api_key=key,
                    base_url=base,
                    max_retries=0,
                    timeout=35 if i == 0 else 15,
                    max_completion_tokens=8192 if i == 0 else 1024,
                    reasoning_effort=os.environ.get("BROWSER_USE_REASONING", "low") if i == 0 else "low",
                    reasoning_models=[name] if provider == "fireworks" or i == 0 else [],
                    frequency_penalty=None,
                )
                for i, name in enumerate(names)
            ]
            if provider == "openrouter":
                pair[0] = GatewayAnthropic(
                    model=names[0],
                    auth_token=key,
                    api_key="",
                    base_url="https://openrouter.ai/api",
                    max_retries=0,
                    timeout=35,
                    max_tokens=4096,
                )
        vision.append(pair[0])
        writers.append(pair[1])
        if provider == "fireworks":
            inspectors.append(
                replace(
                    pair[0],
                    model=os.environ.get("BROWSER_USE_FIREWORKS_INSPECT_MODEL", "accounts/fireworks/models/glm-5p3-flash"),
                    reasoning_models=["accounts/fireworks/models/glm-5p3-flash"],
                    reasoning_effort="low",
                    max_completion_tokens=2048,
                )
            )
        else:
            inspectors.append(pair[0])
    return ModelChain(vision), ModelChain(writers), ModelChain(inspectors).limited(2048)

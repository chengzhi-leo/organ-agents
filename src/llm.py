import hashlib
import os
import threading
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from src.schemas import Completion

load_dotenv(Path(__file__).parent.parent / ".env")

MAX_CONTEXT_TOKENS = 200_000


class LLM:
    def __init__(self, config):
        self.client = genai.Client(
            vertexai=True,
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ["GOOGLE_CLOUD_LOCATION"],
        )
        self.model = config["model"]["name"]
        self.cache_system_prompts = config["model"]["cache_system_prompts"]
        self.cache_ttl = config["model"]["cache_ttl"] if self.cache_system_prompts else None
        self.temperature = config["generation"]["temperature"]
        self.max_output_tokens = config["generation"]["max_output_tokens"]
        if not 0 < self.max_output_tokens <= MAX_CONTEXT_TOKENS:
            raise ValueError(
                f"max_output_tokens must be between 1 and {MAX_CONTEXT_TOKENS:,}"
            )
        self.call_count = 0
        self.caches = {}
        self.lock = threading.Lock()

    def generate(self, system_prompt, user_prompt, response_model):
        generation = self._generation_settings(response_model)
        self._validate_token_budget(system_prompt, user_prompt, generation)
        anchor = (
            {"cached_content": self._cache(system_prompt)}
            if self.cache_system_prompts
            else {"system_instruction": system_prompt}
        )
        response = self.client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                **anchor,
                **generation,
            ),
        )
        if not response.text:
            raise RuntimeError(f"{self.model} returned an empty response for:\n{user_prompt}")

        usage = response.usage_metadata
        completion = Completion(
            response_model.model_validate_json(response.text),
            system_prompt,
            user_prompt,
            response.text,
            usage.prompt_token_count or 0,
            usage.cached_content_token_count or 0,
            usage.candidates_token_count or 0,
            usage.total_token_count or 0,
        )
        with self.lock:
            self.call_count += 1
        return completion

    def _generation_settings(self, response_model):
        return {
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "response_mime_type": "application/json",
            "response_schema": response_model,
        }

    def _validate_token_budget(self, system_prompt, user_prompt, generation):
        usage = self.client.models.count_tokens(
            model=self.model,
            contents=user_prompt,
            config=types.CountTokensConfig(
                system_instruction=system_prompt,
                generation_config=types.GenerationConfig(**generation),
            ),
        )
        if usage.total_tokens is None:
            raise RuntimeError(f"{self.model} did not return an input token count")
        request_tokens = usage.total_tokens + self.max_output_tokens
        if request_tokens > MAX_CONTEXT_TOKENS:
            raise ValueError(
                f"{self.model} request budget {request_tokens:,} exceeds the "
                f"{MAX_CONTEXT_TOKENS:,}-token context limit "
                f"({usage.total_tokens:,} input + {self.max_output_tokens:,} max output)"
            )

    def _cache(self, system_prompt):
        with self.lock:
            if system_prompt not in self.caches:
                self.caches[system_prompt] = self._reuse_or_create(system_prompt)
            return self.caches[system_prompt]

    def _reuse_or_create(self, system_prompt):
        digest = hashlib.sha256(f"{self.model}\n{system_prompt}".encode()).hexdigest()[:16]
        label = f"organ-agents-{digest}"
        for cached in self.client.caches.list():
            if cached.display_name == label:
                return cached.name
        return self.client.caches.create(
            model=self.model,
            config=types.CreateCachedContentConfig(
                system_instruction=system_prompt, ttl=self.cache_ttl, display_name=label
            ),
        ).name

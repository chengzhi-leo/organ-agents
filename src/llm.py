import hashlib
import json
import os
import threading
from pathlib import Path

import tiktoken
from dotenv import load_dotenv
from google import genai
from google.genai import types

from src.schemas import Completion

load_dotenv(Path(__file__).parent.parent / ".env")


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
        token_counting = config["token_counting"]
        self.encoding = tiktoken.get_encoding(token_counting["encoding"])
        self.max_context_tokens = token_counting["max_context_tokens"]
        if not 0 < self.max_output_tokens <= self.max_context_tokens:
            raise ValueError(
                "max_output_tokens must be positive and no greater than "
                "max_context_tokens"
            )
        self.call_count = 0
        self.caches = {}
        self.lock = threading.Lock()

    def generate(self, system_prompt, user_prompt, response_model):
        self._validate_token_budget(system_prompt, user_prompt, response_model)
        generation = self._generation_settings(response_model)
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
        if usage is None:
            raise RuntimeError(f"{self.model} returned no token usage metadata")
        required_usage = (
            usage.prompt_token_count,
            usage.candidates_token_count,
            usage.total_token_count,
        )
        if any(value is None for value in required_usage):
            raise RuntimeError(f"{self.model} returned incomplete token usage metadata")
        completion = Completion(
            response_model.model_validate_json(response.text),
            system_prompt,
            user_prompt,
            response.text,
            usage.prompt_token_count,
            usage.cached_content_token_count or 0,
            usage.candidates_token_count,
            usage.total_token_count,
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

    def _validate_token_budget(self, system_prompt, user_prompt, response_model):
        response_schema = json.dumps(
            response_model.model_json_schema(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        input_tokens = sum(
            len(self.encoding.encode(part))
            for part in (system_prompt, user_prompt, response_schema)
        )
        request_tokens = input_tokens + self.max_output_tokens
        if request_tokens > self.max_context_tokens:
            raise ValueError(
                f"tiktoken request estimate {request_tokens:,} exceeds the configured "
                f"{self.max_context_tokens:,}-token context limit "
                f"({input_tokens:,} input/schema + "
                f"{self.max_output_tokens:,} max output)"
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

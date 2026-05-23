"""
Script Generator
Supports three LLM providers: Gemini (primary/free), Groq (cheap), DeepSeek (paid).
Tries providers in order — first one that works wins. No manual switching needed.
"""

import json
import logging
from dataclasses import dataclass
from typing import Literal

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

FINANCE_SYSTEM_PROMPT = """
You are a viral Hinglish finance content writer for Indian Gen Z (18-28 yrs).
Write punchy, relatable 60-second Reel scripts.

Rules:
- Mix Hindi + English naturally (Hinglish). Example: "Yaar, ye SIP wali trick try ki?"
- Hook must be a shocking stat or question — first 3 seconds decide everything
- Body: 3-4 simple points, no jargon, relatable examples (chai, movies, salary)
- End with clear CTA: "Follow karo daily finance tips ke liye"
- Total narration: 130-160 words (fits 60 seconds at natural pace)
- visual_query: 3-word English phrase for stock video search (e.g. "money growing plant")

Respond ONLY with valid JSON. No markdown, no explanation.
""".strip()

STORY_SYSTEM_PROMPT = """
You are a dramatic storyteller for Indian short-form video (Reels/Shorts).
Write gripping betrayal/revenge/twist stories for Indian audiences.

Rules:
- Hook: Set the scene instantly — "Mera best friend ne mujhe dhoka diya..."
- Build tension fast — no slow intros
- Twist or revenge ending in last 15 seconds
- Relatable Indian setting (office, family, college, arranged marriage)
- Narration: 140-170 words for 60-second video
- Language: Mostly Hindi, some English words naturally

Respond ONLY with valid JSON. No markdown, no explanation.
""".strip()

RESPONSE_SCHEMA = """
{
  "hook": "opening line (max 12 words)",
  "body": "main narration text (3-4 sentences)",
  "full_narration": "complete script hook + body + CTA as one paragraph",
  "caption": "Instagram caption with 3 relevant hashtags",
  "visual_query": "3-word English stock video search term"
}
""".strip()

# Errors that mean "no point retrying" — billing/auth issues
FATAL_STATUS_CODES = {401, 402, 403}


@dataclass
class Script:
    hook: str
    body: str
    full_narration: str
    caption: str
    visual_query: str
    niche: str
    topic: str

    def build_caption(self, niche: str) -> str:
        common_tags = "#india #reels #viral"
        niche_tags = (
            "#finance #investing #paisa #moneyminds"
            if niche == "finance"
            else "#story #drama #twist #hindustanistories"
        )
        return f"{self.caption}\n\n{niche_tags} {common_tags}"


class ScriptGenerator:
    def __init__(self, settings):
        self.settings = settings

    async def generate(self, niche: Literal["finance", "story"], topic: str) -> Script:
        """
        Generate script trying each configured LLM provider in order.
        Skips providers with empty API keys automatically.
        Distinguishes fatal errors (billing/auth) from retryable ones (rate limits).
        """
        providers = self.settings.active_providers()
        caller_map = {
            "gemini": self._call_gemini,
            "groq": self._call_groq,
            "deepseek": self._call_deepseek,
        }

        last_error = None
        for provider_name in providers:
            caller = caller_map.get(provider_name)
            if not caller:
                continue
            try:
                logger.info("Trying LLM provider: %s", provider_name)
                raw = await caller(niche=niche, topic=topic)
                script = self._parse(raw, niche=niche, topic=topic)
                logger.info("Script generated via %s | hook: %s", provider_name, script.hook[:50])
                return script
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code in FATAL_STATUS_CODES:
                    logger.warning(
                        "%s: HTTP %d (billing/auth issue) — skipping this provider", provider_name, code
                    )
                else:
                    logger.warning("%s: HTTP %d — trying next provider", provider_name, code)
                last_error = exc
            except Exception as exc:
                logger.warning("%s failed: %s — trying next provider", provider_name, exc)
                last_error = exc

        raise RuntimeError(
            f"All LLM providers failed ({providers}). Last error: {last_error}\n"
            f"Check: (1) API keys in .env, (2) model IDs are valid, (3) account has quota."
        )

    def _build_user_prompt(self, niche: str, topic: str) -> str:
        verb = "finance Reel" if niche == "finance" else "story Reel"
        return (
            f"Write a viral Hinglish {verb} script about: '{topic}'.\n"
            f"Response schema:\n{RESPONSE_SCHEMA}"
        )

    @retry(
        retry=retry_if_exception_type(httpx.TimeoutException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _call_gemini(self, niche: str, topic: str) -> dict:
        system = FINANCE_SYSTEM_PROMPT if niche == "finance" else STORY_SYSTEM_PROMPT
        prompt = f"{system}\n\n{self._build_user_prompt(niche, topic)}"
        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.settings.gemini_model}:generateContent"
                f"?key={self.settings.gemini_api_key}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.85,
                        "maxOutputTokens": 700,
                        "responseMimeType": "application/json",
                    },
                },
            )
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                logger.error(
                    "Gemini HTTP %s | model=%s | body=%s",
                    resp.status_code,
                    self.settings.gemini_model,
                    resp.text[:500],
                )
                raise
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)

    @retry(
        retry=retry_if_exception_type(httpx.TimeoutException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _call_groq(self, niche: str, topic: str) -> dict:
        """Groq: OpenAI-compatible, very cheap, great free tier."""
        system = FINANCE_SYSTEM_PROMPT if niche == "finance" else STORY_SYSTEM_PROMPT
        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
            resp = await client.post(
                f"{self.settings.groq_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.groq_api_key}"},
                json={
                    "model": self.settings.groq_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": self._build_user_prompt(niche, topic)},
                    ],
                    "temperature": 0.85,
                    "max_tokens": 700,
                    "response_format": {"type": "json_object"},
                },
            )
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                logger.error(
                    "Groq HTTP %s | model=%s | body=%s",
                    resp.status_code,
                    self.settings.groq_model,
                    resp.text[:500],
                )
                raise
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)

    @retry(
        retry=retry_if_exception_type(httpx.TimeoutException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _call_deepseek(self, niche: str, topic: str) -> dict:
        system = FINANCE_SYSTEM_PROMPT if niche == "finance" else STORY_SYSTEM_PROMPT
        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
            resp = await client.post(
                f"{self.settings.deepseek_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.deepseek_api_key}"},
                json={
                    "model": self.settings.deepseek_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": self._build_user_prompt(niche, topic)},
                    ],
                    "temperature": 0.85,
                    "max_tokens": 700,
                    "response_format": {"type": "json_object"},
                },
            )
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                logger.error(
                    "DeepSeek HTTP %s | model=%s | body=%s",
                    resp.status_code,
                    self.settings.deepseek_model,
                    resp.text[:500],
                )
                raise
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)

    def _parse(self, raw: dict, niche: str, topic: str) -> Script:
        required = ["hook", "body", "full_narration", "caption", "visual_query"]
        missing = [k for k in required if not raw.get(k)]
        if missing:
            raise ValueError(f"LLM response missing fields: {missing}. Got: {list(raw.keys())}")
        return Script(
            hook=raw["hook"].strip(),
            body=raw["body"].strip(),
            full_narration=raw["full_narration"].strip(),
            caption=raw["caption"].strip(),
            visual_query=raw["visual_query"].strip(),
            niche=niche,
            topic=topic,
        )

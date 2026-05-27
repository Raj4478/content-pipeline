"""
Script Generator
Supports three LLM providers: Gemini (primary/free), Groq (cheap), DeepSeek (paid).
Tries providers in order — first one that works wins.

Finance scripts now lead with REAL facts/news, not ad-style invest karo content.
News is fetched from Google News RSS (free, no API key needed).
"""

import json
import logging
import re
import xml.etree.ElementTree as ET
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
You are a viral Hinglish finance educator for Indian Gen Z (18-28 yrs) on Instagram Reels.
Your job is to TEACH — not sell. Share facts that shock, surprise, or educate.

STRICT RULES:
- NEVER say "invest karo", "SIP karo", "financial advisor se poocho" — ye ad nahi hai
- ALWAYS lead with a shocking fact, stat, or news — something people don't know
- Use relatable comparisons: chai (₹30), movie ticket (₹300), iPhone (₹80k), salary (₹30k/month)
- Explain WHY the fact matters — connect to their daily life
- End with a mind-blowing implication or question that makes them share
- Hook must make someone stop scrolling in 2 seconds
- Language: Natural Hinglish — "Yaar", "soch", "matlab", "dekho", "actually"
- Total narration: 120-150 words

GOOD EXAMPLES of hooks:
- "India mein 97% log retirement ke liye kuch nahi bachate — aur wo 60 pe broke ho jaate hain"
- "Ek McDonald's burger ki price har saal 7% badhti hai — teri salary kitni badhti hai?"
- "RBI ne aaj interest rate ghata diya — iska matlab tera home loan sasta hoga"
- "Mukesh Ambani ek second mein ₹90,000 kamaata hai — teri poori month ki salary"

BAD examples (never do this):
- "SIP mein invest karo aur 1 crore banao"
- "Mutual funds sahi hai"
- Generic "paise bachao" advice

If a finance news headline is provided, base the script on that real news.
Otherwise use a shocking finance fact relevant to the topic.

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
  "hook": "shocking opening line (max 12 words, must be a fact or news — not advice)",
  "body": "main narration — explain the fact, why it matters, real numbers (3-4 sentences)",
  "full_narration": "complete script hook + body as one paragraph",
  "caption": "Instagram caption with 3 relevant hashtags",
  "visual_query": "3-word English stock video search term"
}
""".strip()

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


async def fetch_finance_news(topic: str) -> str:
    """
    Fetch latest Indian finance news from Google News RSS.
    Free, no API key needed. Returns top headline or empty string.
    """
    query = topic.replace(" ", "+") + "+india+finance"
    url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            items = root.findall(".//item")
            if items:
                title = items[0].findtext("title") or ""
                # Clean Google News title format "Headline - Source"
                title = re.sub(r"\s*-\s*[^-]+$", "", title).strip()
                logger.info("Finance news fetched: %s", title[:80])
                return title
    except Exception as e:
        logger.warning("News fetch failed (non-critical): %s", e)
    return ""


class ScriptGenerator:
    def __init__(self, settings):
        self.settings = settings

    async def generate(self, niche: Literal["finance", "story"], topic: str) -> Script:
        """
        Generate script trying each configured LLM provider in order.
        For finance niche — fetches real news first to ground the script in facts.
        """
        # Fetch real news for finance niche
        news_context = ""
        if niche == "finance":
            news_context = await fetch_finance_news(topic)

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
                raw = await caller(niche=niche, topic=topic, news_context=news_context)
                script = self._parse(raw, niche=niche, topic=topic)
                logger.info("Script generated via %s | hook: %s", provider_name, script.hook[:50])
                return script
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code in FATAL_STATUS_CODES:
                    logger.warning(
                        "%s: HTTP %d (billing/auth issue) — skipping", provider_name, code
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

    def _build_user_prompt(self, niche: str, topic: str, news_context: str = "") -> str:
        if niche == "finance":
            news_line = (
                f"\n\nTODAY'S NEWS TO BASE SCRIPT ON: \"{news_context}\"\n"
                f"Use this real news as the hook/fact. Explain what it means for common Indians."
                if news_context
                else "\n\nNo news available — use a shocking finance fact about this topic instead."
            )
            return (
                f"Write a viral Hinglish finance EDUCATION Reel about: '{topic}'."
                f"{news_line}\n\n"
                f"Remember: Teach a fact. Don't give advice. Shock them first.\n"
                f"Response schema:\n{RESPONSE_SCHEMA}"
            )
        else:
            return (
                f"Write a viral Hinglish story Reel about: '{topic}'.\n"
                f"Response schema:\n{RESPONSE_SCHEMA}"
            )

    @retry(
        retry=retry_if_exception_type(httpx.TimeoutException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _call_gemini(self, niche: str, topic: str, news_context: str = "") -> dict:
        system = FINANCE_SYSTEM_PROMPT if niche == "finance" else STORY_SYSTEM_PROMPT
        prompt = f"{system}\n\n{self._build_user_prompt(niche, topic, news_context)}"
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
                logger.error("Gemini HTTP %s | body=%s", resp.status_code, resp.text[:500])
                raise
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)

    @retry(
        retry=retry_if_exception_type(httpx.TimeoutException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _call_groq(self, niche: str, topic: str, news_context: str = "") -> dict:
        system = FINANCE_SYSTEM_PROMPT if niche == "finance" else STORY_SYSTEM_PROMPT
        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
            resp = await client.post(
                f"{self.settings.groq_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.groq_api_key}"},
                json={
                    "model": self.settings.groq_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": self._build_user_prompt(niche, topic, news_context)},
                    ],
                    "temperature": 0.85,
                    "max_tokens": 700,
                    "response_format": {"type": "json_object"},
                },
            )
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                logger.error("Groq HTTP %s | body=%s", resp.status_code, resp.text[:500])
                raise
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)

    @retry(
        retry=retry_if_exception_type(httpx.TimeoutException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _call_deepseek(self, niche: str, topic: str, news_context: str = "") -> dict:
        system = FINANCE_SYSTEM_PROMPT if niche == "finance" else STORY_SYSTEM_PROMPT
        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
            resp = await client.post(
                f"{self.settings.deepseek_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.deepseek_api_key}"},
                json={
                    "model": self.settings.deepseek_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": self._build_user_prompt(niche, topic, news_context)},
                    ],
                    "temperature": 0.85,
                    "max_tokens": 700,
                    "response_format": {"type": "json_object"},
                },
            )
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                logger.error("DeepSeek HTTP %s | body=%s", resp.status_code, resp.text[:500])
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

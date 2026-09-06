"""A scripted LLM provider for tests.

Records every call so tests can assert on what each agent was actually asked,
which is how the "identical settings for every participant" constraint gets
checked.
"""

import json
from typing import AsyncGenerator, Type

from pydantic import BaseModel

from app.llm.base import LLMProvider


class FakeLLM(LLMProvider):
    """Returns canned responses and remembers how it was called.

    `structured_responses` and `text_responses` are consumed in order; an
    entry that is an exception instance is raised instead of returned, which
    is how failure paths get exercised.
    """

    def __init__(
        self,
        structured_responses: list | None = None,
        text_responses: list | None = None,
    ):
        self.structured_responses = list(structured_responses or [])
        self.text_responses = list(text_responses or [])
        self.calls: list[dict] = []

    def _next(self, queue: list, kind: str):
        if not queue:
            raise AssertionError(f"FakeLLM ran out of {kind} responses")
        value = queue.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    async def generate_text(
        self, system_prompt, messages, *, temperature=0.8, max_tokens=500, top_p=1.0
    ) -> str:
        self.calls.append({
            "kind": "text",
            "system_prompt": system_prompt,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
        })
        return self._next(self.text_responses, "text")

    async def generate_structured(
        self,
        system_prompt,
        messages,
        response_model: Type[BaseModel],
        *,
        temperature=0.8,
        max_tokens=1000,
        top_p=1.0,
    ) -> BaseModel:
        self.calls.append({
            "kind": "structured",
            "system_prompt": system_prompt,
            "messages": messages,
            "response_model": response_model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
        })
        value = self._next(self.structured_responses, "structured")
        if isinstance(value, BaseModel):
            return value
        if isinstance(value, str):
            return response_model.model_validate_json(value)
        return response_model.model_validate(value)

    async def generate_stream(
        self,
        system_prompt,
        messages,
        *,
        temperature=0.8,
        max_tokens=500,
        top_p=1.0,
        json_output=False,
    ) -> AsyncGenerator[str, None]:
        """Stream the next scripted response, in small chunks.

        Streaming draws from the same queue as structured calls, so a script
        exercises whichever path the engine actually takes. Chunks are split
        at an awkward size on purpose, to land mid-word and mid-escape.
        """
        self.calls.append({
            "kind": "stream",
            "system_prompt": system_prompt,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
            "json_output": json_output,
        })
        value = self._next(self.structured_responses, "structured")
        raw = value if isinstance(value, str) else json.dumps(value)
        for i in range(0, len(raw), 7):
            yield raw[i : i + 7]


def argument(text: str, **overrides) -> dict:
    """One well-formed debater response."""
    return {
        "argument": text,
        "key_claims": ["a claim"],
        "opponent_claim_addressed": None,
        "confidence": 0.7,
        **overrides,
    }


def judge_verdict(winner: str = "Participant A") -> dict:
    """One well-formed judge response, keyed by anonymized label."""
    scores = {
        "logic": 8, "evidence": 7, "rebuttal": 9,
        "persuasiveness": 8, "overall": 8.0,
    }
    return {
        "winner": winner,
        "scores": {
            "Participant A": scores,
            "Participant B": {**scores, "logic": 6, "overall": 6.5},
        },
        "winner_reason": "Engaged the other side's strongest claim directly.",
        "strongest_argument": "The cost argument in the counter round.",
        "weakest_argument": "The unsupported appeal in the opening.",
    }


def debate_script(judge_winner: str = "Participant A") -> list:
    """Eight debater turns plus a verdict — one complete debate."""
    turns = [
        argument(f"Argument for {phase} turn {i}")
        for phase in ("opening", "rebuttal", "counter", "closing")
        for i in (1, 2)
    ]
    return turns + [judge_verdict(judge_winner)]


def json_response(payload: dict) -> str:
    return json.dumps(payload)

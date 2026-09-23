"""Gemini thinking control, input bounds, and what errors reach the browser."""

import pytest

from app.core.config import settings
from app.llm.errors import LLMRequestRejected, public_message
from app.llm.gemini_provider import GeminiProvider
from app.schemas import MAX_PERSONA_JSON_CHARS
from tests.conftest import PERSONA_FIXTURE
from tests.test_api import client, create_friends  # noqa: F401 — fixture


def _body(provider: GeminiProvider) -> dict:
    return provider._build_body(
        "system", [], temperature=0.8, max_tokens=500, top_p=1.0
    )


class TestGeminiThinking:
    def test_level_is_sent_on_a_3x_model(self, monkeypatch):
        monkeypatch.setattr(settings, "GEMINI_THINKING_BUDGET", None)
        monkeypatch.setattr(settings, "GEMINI_THINKING_LEVEL", "minimal")
        body = _body(GeminiProvider(model="gemini-3.5-flash"))
        assert body["generationConfig"]["thinkingConfig"] == {
            "thinkingLevel": "minimal"
        }

    def test_nothing_is_sent_when_unset(self, monkeypatch):
        monkeypatch.setattr(settings, "GEMINI_THINKING_BUDGET", None)
        monkeypatch.setattr(settings, "GEMINI_THINKING_LEVEL", "")
        assert "thinkingConfig" not in _body(GeminiProvider())["generationConfig"]

    def test_budget_wins_so_both_fields_are_never_sent(self, monkeypatch):
        monkeypatch.setattr(settings, "GEMINI_THINKING_BUDGET", 0)
        monkeypatch.setattr(settings, "GEMINI_THINKING_LEVEL", "minimal")
        config = _body(GeminiProvider())["generationConfig"]["thinkingConfig"]
        assert config == {"thinkingBudget": 0}

    def test_an_answer_lost_to_thinking_says_how_to_fix_it(self):
        payload = {
            "candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}],
            "usageMetadata": {"thoughtsTokenCount": 480},
        }
        with pytest.raises(ValueError, match="GEMINI_THINKING_LEVEL"):
            GeminiProvider._first_text(payload)

    def test_the_default_model_is_not_retired(self):
        # gemini-1.5-pro answers every request with a 404.
        default = type(settings).model_fields["LLM_MODEL"].default
        assert not default.startswith(("gemini-1.", "gemini-2."))


class TestPublicMessage:
    def test_a_provider_failure_keeps_its_user_message(self):
        error = LLMRequestRejected("404", detail="model not found")
        assert public_message(error) == error.user_message

    def test_an_internal_failure_reveals_nothing(self):
        error = RuntimeError(
            "connection to postgresql://app:hunter2@db.internal:5432 failed"
        )
        message = public_message(error)
        assert "hunter2" not in message
        assert "db.internal" not in message


class TestInputBounds:
    async def test_rejects_an_oversized_description(self, client):  # noqa: F811
        response = await client.post(
            "/api/friends", json={"name": "Sam", "raw_description": "x" * 2001}
        )
        assert response.status_code == 422

    async def test_rejects_an_oversized_topic(self, client):  # noqa: F811
        friend_ids = await create_friends(client)
        response = await client.post("/api/debates", json={
            "topic": "t" * 301, "participant_ids": friend_ids,
        })
        assert response.status_code == 422

    async def test_rejects_an_oversized_persona_edit(self, client):  # noqa: F811
        friend_ids = await create_friends(client)
        persona = dict(PERSONA_FIXTURE, values=["v" * 500] * 20)
        assert len(str(persona)) > MAX_PERSONA_JSON_CHARS
        response = await client.put(
            f"/api/personas/{friend_ids[0]}", json={"persona": persona}
        )
        assert response.status_code == 422

    async def test_accepts_a_normal_persona_edit(self, client):  # noqa: F811
        friend_ids = await create_friends(client)
        response = await client.put(
            f"/api/personas/{friend_ids[0]}", json={"persona": PERSONA_FIXTURE}
        )
        assert response.status_code == 200

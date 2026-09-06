"""Route behaviour: the MVP endpoint surface, and what it does and doesn't expose."""

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.llm.factory import get_llm_provider
from app.main import app
from app.services import debate_runner
from tests.fakes import FakeLLM, debate_script


@pytest.fixture
async def client(monkeypatch):
    """An API client backed by a throwaway database and a scripted LLM."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def override_db():
        async with session_factory() as session:
            yield session

    llm = FakeLLM(structured_responses=debate_script())
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr("app.core.database.AsyncSessionLocal", session_factory)
    monkeypatch.setattr(debate_runner, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(debate_runner, "get_llm_provider", lambda: llm)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.llm = llm
        yield ac

    app.dependency_overrides.clear()
    debate_runner._broadcasts.clear()
    await engine.dispose()


async def create_friends(client):
    ids = []
    for name in ("Rahul", "Aman"):
        response = await client.post("/api/friends", json={
            "name": name,
            "raw_description": f"{name} argues carefully and likes evidence.",
        })
        assert response.status_code == 201
        ids.append(response.json()["id"])
    return ids


class TestEndpointSurface:
    def test_only_the_mvp_routes_exist(self):
        """Deferred features must not exist as endpoints — not even disabled."""
        routes = {
            (method.upper(), path)
            for path, operations in app.openapi()["paths"].items()
            for method in operations
            if path.startswith("/api")
        }

        assert routes == {
            ("POST", "/api/friends"),
            ("GET", "/api/friends"),
            ("POST", "/api/personas/compile"),
            ("PUT", "/api/personas/{friend_id}"),
            ("POST", "/api/debates"),
            ("POST", "/api/debates/{debate_id}/start"),
            ("GET", "/api/debates/{debate_id}/stream"),
            ("GET", "/api/debates/{debate_id}/result"),
            ("GET", "/api/health"),
        }


class TestFriends:
    async def test_creates_and_lists_friends(self, client):
        await create_friends(client)
        response = await client.get("/api/friends")
        assert response.status_code == 200
        assert {f["name"] for f in response.json()} == {"Rahul", "Aman"}

    async def test_rejects_a_description_too_short_to_compile(self, client):
        response = await client.post(
            "/api/friends", json={"name": "Sam", "raw_description": "hi"}
        )
        assert response.status_code == 422


class TestDebateCreation:
    async def test_creates_a_debate_between_two_friends(self, client):
        friend_ids = await create_friends(client)
        response = await client.post("/api/debates", json={
            "topic": "Is remote work better than office work?",
            "participant_ids": friend_ids,
        })
        assert response.status_code == 201

        body = response.json()
        assert body["status"] == "CREATED"
        assert len(body["participants"]) == 2

    async def test_the_client_cannot_choose_the_model_settings(self, client):
        """Model config comes from the environment, never from the request.

        Asserted against the configured values rather than literals, so the
        suite does not depend on whatever is in the developer's own .env.
        """
        from app.core.config import settings

        friend_ids = await create_friends(client)
        response = await client.post("/api/debates", json={
            "topic": "Is remote work better than office work?",
            "participant_ids": friend_ids,
            "temperature": 0.1,
            "max_tokens": 4000,
            "model_name": "some-other-model",
        })
        assert response.status_code == 201

        body = response.json()
        assert body["temperature"] == settings.DEBATE_TEMPERATURE
        assert body["max_tokens"] == settings.DEBATE_MAX_TOKENS
        assert body["model_name"] == settings.LLM_MODEL
        # The values the client tried to set were ignored outright.
        assert body["temperature"] != 0.1
        assert body["max_tokens"] != 4000

    async def test_rejects_three_participants(self, client):
        friend_ids = await create_friends(client)
        response = await client.post("/api/debates", json={
            "topic": "Is remote work better than office work?",
            "participant_ids": friend_ids + [friend_ids[0]],
        })
        assert response.status_code == 422

    async def test_rejects_the_same_friend_twice(self, client):
        friend_ids = await create_friends(client)
        response = await client.post("/api/debates", json={
            "topic": "Is remote work better than office work?",
            "participant_ids": [friend_ids[0], friend_ids[0]],
        })
        assert response.status_code == 400


class TestStreaming:
    async def test_start_then_stream_delivers_the_whole_debate(self, client):
        friend_ids = await create_friends(client)
        debate = (await client.post("/api/debates", json={
            "topic": "Is remote work better than office work?",
            "participant_ids": friend_ids,
        })).json()

        start = await client.post(f"/api/debates/{debate['id']}/start")
        assert start.status_code == 202

        events = []
        async with client.stream("GET", f"/api/debates/{debate['id']}/stream") as stream:
            assert stream.status_code == 200
            assert stream.headers["content-type"].startswith("text/event-stream")
            async for line in stream.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                events.append(json.loads(payload))

        # Buffering means a client that connects after starting still gets
        # everything from the first event on.
        assert events[0]["event_type"] == "phase_start"
        assert events[0]["phase"] == "POSITIONING"
        assert sum(e["event_type"] == "message" for e in events) == 8
        assert events[-1]["event_type"] == "debate_complete"

    async def test_streaming_a_debate_that_was_never_started_is_refused(self, client):
        friend_ids = await create_friends(client)
        debate = (await client.post("/api/debates", json={
            "topic": "Is remote work better than office work?",
            "participant_ids": friend_ids,
        })).json()

        response = await client.get(f"/api/debates/{debate['id']}/stream")
        assert response.status_code == 409


class TestResult:
    async def test_the_verdict_is_available_once_the_debate_completes(self, client):
        friend_ids = await create_friends(client)
        debate = (await client.post("/api/debates", json={
            "topic": "Is remote work better than office work?",
            "participant_ids": friend_ids,
        })).json()
        await client.post(f"/api/debates/{debate['id']}/start")

        async with client.stream("GET", f"/api/debates/{debate['id']}/stream") as stream:
            async for _ in stream.aiter_lines():
                pass

        response = await client.get(f"/api/debates/{debate['id']}/result")
        assert response.status_code == 200

        body = response.json()
        assert body["winner_name"] in {"Rahul", "Aman"}
        assert body["winner_reason"]
        assert body["strongest_argument"]
        assert len(body["participants"]) == 2
        assert sum(p["is_winner"] for p in body["participants"]) == 1
        assert {p["position"] for p in body["participants"]} == {"FOR", "AGAINST"}

    async def test_asking_for_a_verdict_too_early_is_refused(self, client):
        friend_ids = await create_friends(client)
        debate = (await client.post("/api/debates", json={
            "topic": "Is remote work better than office work?",
            "participant_ids": friend_ids,
        })).json()

        response = await client.get(f"/api/debates/{debate['id']}/result")
        assert response.status_code == 409


class TestSecrets:
    async def test_no_response_carries_the_api_key_or_provider_config(self, client):
        """Acceptance criterion: no API keys reach the frontend."""
        from app.core.config import settings

        friend_ids = await create_friends(client)
        debate = (await client.post("/api/debates", json={
            "topic": "Is remote work better than office work?",
            "participant_ids": friend_ids,
        })).json()
        await client.post(f"/api/debates/{debate['id']}/start")

        bodies = [json.dumps(debate)]
        async with client.stream("GET", f"/api/debates/{debate['id']}/stream") as stream:
            async for line in stream.aiter_lines():
                bodies.append(line)
        bodies.append((await client.get("/api/friends")).text)
        bodies.append((await client.get(f"/api/debates/{debate['id']}/result")).text)

        combined = "\n".join(bodies)
        assert settings.LLM_API_KEY not in combined
        assert "LLM_API_KEY" not in combined
        assert "api_key" not in combined.lower()

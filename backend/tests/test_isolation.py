"""One visitor never sees, edits or runs what another visitor made.

Each AsyncClient keeps its own cookie jar, so two clients against the same app
and database are two browsers.
"""

import hashlib
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models import Debate, Friend
from tests.conftest import PERSONA_FIXTURE
from tests.test_api import client, create_friends  # noqa: F401 — fixture
from tests.test_history import run_debate

TOPIC = "Is remote work better than office work?"


@pytest.fixture
async def stranger(client):  # noqa: F811
    """A second browser on the same arena."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        yield other


class TestVisitorCookie:
    async def test_first_request_issues_an_httponly_samesite_cookie(self, client):  # noqa: F811
        response = await client.get("/api/friends")
        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"{settings.OWNER_COOKIE_NAME}=")
        assert "HttpOnly" in cookie
        assert "SameSite=Lax" in cookie
        # Plain-HTTP development; production turns Secure on.
        assert "Secure" not in cookie

    async def test_the_cookie_is_kept_across_requests(self, client):  # noqa: F811
        await client.get("/api/friends")
        first = client.cookies[settings.OWNER_COOKIE_NAME]
        await client.get("/api/friends")
        assert client.cookies[settings.OWNER_COOKIE_NAME] == first

    async def test_a_forged_cookie_is_replaced_not_trusted(self, client):  # noqa: F811
        client.cookies.set(settings.OWNER_COOKIE_NAME, "not-a-token-we-issued")
        response = await client.get("/api/friends")
        issued = response.headers["set-cookie"].split(";")[0].split("=", 1)[1]
        assert issued != "not-a-token-we-issued"
        assert len(issued) == 43

    async def test_the_database_stores_a_hash_never_the_token(self, client):  # noqa: F811
        await create_friends(client)
        token = client.cookies[settings.OWNER_COOKIE_NAME]

        async with client.session_factory() as db:
            owners = set((await db.execute(select(Friend.owner_key))).scalars())
        assert owners == {hashlib.sha256(token.encode()).hexdigest()}
        assert token not in owners

    async def test_health_checks_are_not_issued_an_identity(self, client):  # noqa: F811
        response = await client.get("/api/health")
        assert "set-cookie" not in response.headers


class TestFriendIsolation:
    async def test_another_visitor_sees_none_of_my_friends(self, client, stranger):  # noqa: F811
        await create_friends(client)

        assert (await stranger.get("/api/friends")).json() == []
        assert (await stranger.get("/api/personas")).json() == []
        # ...while I still see mine.
        assert len((await client.get("/api/friends")).json()) == 2

    async def test_another_visitor_cannot_edit_my_persona(self, client, stranger):  # noqa: F811
        friend_ids = await create_friends(client)
        response = await stranger.put(
            f"/api/personas/{friend_ids[0]}", json={"persona": PERSONA_FIXTURE}
        )
        assert response.status_code == 404

    async def test_another_visitor_cannot_compile_my_friend(self, client, stranger, monkeypatch):  # noqa: F811
        monkeypatch.setattr("app.api.friends.get_llm_provider", lambda: client.llm)
        friend_ids = await create_friends(client)
        response = await stranger.post(
            "/api/personas/compile", json={"friend_id": friend_ids[0]}
        )
        assert response.status_code == 404
        assert client.llm.calls == []  # not a single model call was spent

    async def test_another_visitor_cannot_debate_with_my_friends(self, client, stranger):  # noqa: F811
        friend_ids = await create_friends(client)
        response = await stranger.post("/api/debates", json={
            "topic": TOPIC, "participant_ids": friend_ids,
        })
        assert response.status_code == 404

    async def test_someone_elses_friend_looks_exactly_like_a_missing_one(self, client, stranger):  # noqa: F811
        friend_ids = await create_friends(client)
        mine = await stranger.put(
            f"/api/personas/{friend_ids[0]}", json={"persona": PERSONA_FIXTURE}
        )
        missing = await stranger.put(
            f"/api/personas/{uuid4()}", json={"persona": PERSONA_FIXTURE}
        )
        assert (mine.status_code, mine.json()) == (missing.status_code, missing.json())


class TestDebateIsolation:
    async def test_another_visitor_cannot_find_or_touch_my_debate(self, client, stranger):  # noqa: F811
        friend_ids = await create_friends(client)
        debate_id = await run_debate(client, friend_ids)

        assert (await stranger.get("/api/debates")).json() == []
        for method, path in [
            ("GET", f"/api/debates/{debate_id}"),
            ("POST", f"/api/debates/{debate_id}/start"),
            ("GET", f"/api/debates/{debate_id}/stream"),
            ("GET", f"/api/debates/{debate_id}/result"),
        ]:
            response = await stranger.request(method, path)
            assert response.status_code == 404, path

        # The owner still has all of it.
        assert (await client.get(f"/api/debates/{debate_id}/result")).status_code == 200

    async def test_another_visitor_cannot_start_my_unstarted_debate(self, client, stranger):  # noqa: F811
        friend_ids = await create_friends(client)
        debate = (await client.post("/api/debates", json={
            "topic": TOPIC, "participant_ids": friend_ids,
        })).json()

        response = await stranger.post(f"/api/debates/{debate['id']}/start")
        assert response.status_code == 404
        async with client.session_factory() as db:
            assert (await db.get(Debate, UUID(debate["id"]))).status == "CREATED"

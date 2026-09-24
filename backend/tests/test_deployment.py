"""What a public deployment adds: headers, limits, static serving, recovery."""

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings, settings
from app.core.security import RateLimiter
from app.main import app, create_app
from app.models import Debate
from app.services import debate_runner
from tests.test_api import client, create_friends  # noqa: F401 — fixture


async def request(target_app, method, path, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=target_app), base_url="http://test") as ac:
        return await ac.request(method, path, **kwargs)


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "COOKIE_SECURE", None)
    return create_app()


class TestHeaders:
    async def test_every_response_carries_the_basic_hardening(self, client):  # noqa: F811
        response = await client.get("/api/health")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert "referrer-policy" in response.headers
        # Development keeps the CDN-backed /docs working.
        assert "content-security-policy" not in response.headers

    async def test_production_adds_csp_and_hsts(self, production):
        response = await request(production, "GET", "/api/health")
        csp = response.headers["content-security-policy"]
        assert "script-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert response.headers["strict-transport-security"].startswith("max-age=")


class TestProductionMode:
    async def test_the_api_docs_are_not_published(self, production):
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await request(production, "GET", path)).status_code == 404

    async def test_the_visitor_cookie_is_secure(self, production):
        response = await request(production, "GET", "/api/nothing-here")
        assert "Secure" in response.headers["set-cookie"]

    async def test_loopback_origins_are_not_blanket_allowed(self, production):
        headers = {"Origin": "http://localhost:5999"}
        response = await request(production, "GET", "/api/health", headers=headers)
        assert "access-control-allow-origin" not in response.headers

    async def test_development_still_allows_any_loopback_port(self, client):  # noqa: F811
        response = await client.get("/api/health", headers={"Origin": "http://localhost:5999"})
        assert response.headers["access-control-allow-origin"] == "http://localhost:5999"

    def test_samesite_none_forces_secure(self, monkeypatch):
        monkeypatch.setattr(settings, "COOKIE_SAMESITE", "None")
        monkeypatch.setattr(settings, "COOKIE_SECURE", False)
        assert settings.cookie_secure is True


class TestRateLimits:
    async def test_friend_creation_is_throttled_per_client(self, client, monkeypatch):  # noqa: F811
        monkeypatch.setattr(settings, "RATE_LIMIT_FRIENDS_PER_HOUR", 2)
        await create_friends(client)  # two allowed

        response = await client.post("/api/friends", json={
            "name": "Third", "raw_description": "One more than the limit allows.",
        })
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) > 0
        assert "Try again" in response.json()["detail"]

    async def test_debate_starts_are_throttled(self, client, monkeypatch):  # noqa: F811
        monkeypatch.setattr(settings, "RATE_LIMIT_DEBATES_PER_HOUR", 1)
        friend_ids = await create_friends(client)
        ids = []
        for _ in range(2):
            debate = await client.post("/api/debates", json={
                "topic": "Cats are better than dogs", "participant_ids": friend_ids,
            })
            ids.append(debate.json()["id"])

        assert (await client.post(f"/api/debates/{ids[0]}/start")).status_code == 202
        assert (await client.post(f"/api/debates/{ids[1]}/start")).status_code == 429

    async def test_a_full_arena_refuses_rather_than_queueing(self, client, monkeypatch):  # noqa: F811
        monkeypatch.setattr(settings, "MAX_CONCURRENT_DEBATES", 1)
        monkeypatch.setitem(debate_runner._tasks, "someone-elses-debate", object())
        friend_ids = await create_friends(client)
        debate = (await client.post("/api/debates", json={
            "topic": "Cats are better than dogs", "participant_ids": friend_ids,
        })).json()

        response = await client.post(f"/api/debates/{debate['id']}/start")
        assert response.status_code == 503
        assert response.headers["retry-after"] == "60"

    def test_the_window_slides(self):
        limiter = RateLimiter(window=100)
        assert limiter.check("b", "ip", 2, now=0) is None
        assert limiter.check("b", "ip", 2, now=10) is None
        assert limiter.check("b", "ip", 2, now=50) == pytest.approx(50)
        assert limiter.check("b", "other-ip", 2, now=50) is None
        # The first hit ages out and frees a slot.
        assert limiter.check("b", "ip", 2, now=100) is None


class TestFrontendServing:
    @pytest.fixture
    def site(self, tmp_path, monkeypatch):
        build = tmp_path / "dist"
        (build / "assets").mkdir(parents=True)
        (build / "index.html").write_text("<!doctype html><title>shell</title>")
        (build / "assets" / "index-abc123.js").write_text("console.log(1)")
        (build / "favicon.svg").write_text("<svg/>")
        (tmp_path / "secret.txt").write_text("outside the build")
        monkeypatch.setattr(settings, "STATIC_DIR", str(build))
        return create_app()

    async def test_the_shell_is_served_for_client_routes(self, site):
        for path in ("/", "/personas", "/debate/123/verdict"):
            response = await request(site, "GET", path)
            assert response.status_code == 200
            assert "shell" in response.text
            assert response.headers["cache-control"] == "no-cache"

    async def test_assets_are_cached_for_good(self, site):
        response = await request(site, "GET", "/assets/index-abc123.js")
        assert response.status_code == 200
        assert "immutable" in response.headers["cache-control"]

    async def test_top_level_files_are_served(self, site):
        response = await request(site, "GET", "/favicon.svg")
        assert response.text == "<svg/>"

    async def test_an_unknown_api_path_is_a_404_not_the_shell(self, site):
        response = await request(site, "GET", "/api/does-not-exist")
        assert response.status_code == 404
        assert "shell" not in response.text

    async def test_no_path_escapes_the_build_directory(self, site):
        for path in ("/../secret.txt", "/..%2Fsecret.txt", "/assets/..%2F..%2Fsecret.txt"):
            response = await request(site, "GET", path)
            assert "outside the build" not in response.text, path

    def test_a_missing_build_fails_at_startup(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "STATIC_DIR", str(tmp_path / "nope"))
        with pytest.raises(RuntimeError, match="index.html"):
            create_app()


class TestRestartRecovery:
    async def test_debates_cut_off_mid_run_are_marked_failed(self, db):
        def debate(status):
            return Debate(
                topic="t" * 10, status=status, model_provider="p", model_name="m",
                created_at=datetime.now(timezone.utc),
            )

        running, done, fresh = debate("REBUTTAL"), debate("COMPLETED"), debate("CREATED")
        db.add_all([running, done, fresh])
        await db.commit()

        assert await debate_runner.fail_interrupted(db) == 1
        for row in (running, done, fresh):
            await db.refresh(row)
        assert (running.status, done.status, fresh.status) == ("FAILED", "COMPLETED", "CREATED")


class TestDatabaseUrl:
    def test_a_hosted_postgres_url_is_made_asyncpg_compatible(self):
        url = Settings(
            DATABASE_URL="postgresql://u:p@host/db?sslmode=require&channel_binding=require"
        ).DATABASE_URL
        assert url == "postgresql+asyncpg://u:p@host/db?ssl=require"

    def test_a_plain_url_is_left_alone(self):
        url = Settings(DATABASE_URL="postgres://u:p@host:5432/db").DATABASE_URL
        assert url == "postgresql+asyncpg://u:p@host:5432/db"


def test_the_module_app_is_the_development_one():
    """Guards the fixtures above: they rebuild the app, never mutate this one."""
    assert app.docs_url == "/docs"

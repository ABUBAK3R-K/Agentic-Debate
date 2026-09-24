"""The seeded public figures: valid, shared read-only, and safe to reseed."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.main import app
from app.models import Friend, Persona
from app.services import public_figures
from app.services.public_figures import (
    CATEGORIES,
    PublicFigure,
    load_public_figures,
    seed_public_figures,
)
from tests.conftest import PERSONA_FIXTURE
from tests.test_api import client, create_friends  # noqa: F401 — fixture
from tests.test_history import run_debate


class TestDataFile:
    def test_every_entry_is_a_valid_persona(self):
        figures = load_public_figures()
        assert len(figures) >= 20
        for figure in figures:
            assert figure.persona.name == figure.name
            assert figure.persona.core_traits and figure.persona.values
            assert figure.persona.debate_style.preferred_tactics

    def test_every_category_is_represented(self):
        present = {figure.category for figure in load_public_figures()}
        assert present == set(CATEGORIES)

    def test_ids_are_stable_and_unique(self):
        figures = load_public_figures()
        assert len({f.id for f in figures}) == len(figures)
        again = PublicFigure.model_validate(figures[0].model_dump())
        assert again.id == figures[0].id

    def test_the_traits_the_judge_sees_never_name_the_person(self):
        """The judge is blind, and is shown core traits. A trait that names
        its owner — or a nickname — would un-blind it."""
        for figure in load_public_figures():
            traits = " ".join(figure.persona.core_traits).lower()
            for part in figure.name.lower().replace(".", "").split():
                if len(part) > 2:
                    assert part not in traits, (figure.name, traits)


async def seed(client):  # noqa: F811
    async with client.session_factory() as db:
        return await seed_public_figures(db)


async def public_rows(client):  # noqa: F811
    return [row for row in (await client.get("/api/personas")).json() if row["is_public"]]


class TestSeeding:
    async def test_seeding_twice_changes_nothing_the_second_time(self, client):  # noqa: F811
        assert await seed(client) > 0
        assert await seed(client) == 0

        async with client.session_factory() as db:
            count = await db.scalar(select(func.count()).select_from(Friend))
            versions = await db.scalar(select(func.count()).select_from(Persona))
        assert count == versions == len(load_public_figures())

    async def test_a_changed_persona_becomes_a_new_version(self, client, monkeypatch):  # noqa: F811
        await seed(client)
        first = load_public_figures()[0]
        changed = first.model_copy(update={
            "persona": first.persona.model_copy(update={"values": ["Something new"]}),
        })
        monkeypatch.setattr(public_figures, "load_public_figures", lambda: (changed,))

        assert await seed(client) == 1
        [row] = [r for r in await public_rows(client) if r["friend_id"] == str(first.id)]
        assert row["version"] == 2
        assert row["persona"]["values"] == ["Something new"]

    async def test_a_public_id_is_never_left_owned(self, client):  # noqa: F811
        figure = load_public_figures()[0]
        async with client.session_factory() as db:
            db.add(Friend(
                id=figure.id, name="Squatter", raw_description="Took the id first",
                owner_key="someone", is_public=False,
            ))
            await db.commit()

        await seed(client)
        async with client.session_factory() as db:
            friend = await db.get(Friend, figure.id)
        assert (friend.owner_key, friend.is_public, friend.name) == (None, True, figure.name)


class TestSharedReadOnly:
    async def test_every_visitor_sees_the_public_figures(self, client):  # noqa: F811
        await seed(client)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
            theirs = [r for r in (await other.get("/api/personas")).json() if r["is_public"]]
        mine = await public_rows(client)
        assert len(mine) == len(theirs) == len(load_public_figures())
        assert all(r["persona"] and r["category"] in CATEGORIES for r in mine)

    async def test_own_personas_come_first_then_figures_by_category(self, client):  # noqa: F811
        await seed(client)
        await create_friends(client)
        rows = (await client.get("/api/personas")).json()

        assert [r["is_public"] for r in rows[:2]] == [False, False]
        categories = [r["category"] for r in rows[2:]]
        assert categories == sorted(categories, key=CATEGORIES.index)

    async def test_public_figures_are_not_listed_as_my_friends(self, client):  # noqa: F811
        await seed(client)
        assert (await client.get("/api/friends")).json() == []

    async def test_nobody_can_edit_a_public_figure_in_place(self, client):  # noqa: F811
        await seed(client)
        figure = load_public_figures()[0]
        response = await client.put(
            f"/api/personas/{figure.id}", json={"persona": PERSONA_FIXTURE}
        )
        assert response.status_code == 404

        [row] = [r for r in await public_rows(client) if r["friend_id"] == str(figure.id)]
        assert row["persona"]["name"] == figure.name
        assert row["version"] == 1

    async def test_nobody_can_recompile_a_public_figure(self, client):  # noqa: F811
        await seed(client)
        response = await client.post(
            "/api/personas/compile", json={"friend_id": str(load_public_figures()[0].id)}
        )
        assert response.status_code == 404


class TestDebatingPublicFigures:
    async def test_two_public_figures_can_debate(self, client):  # noqa: F811
        await seed(client)
        dhoni, kohli = (
            next(f for f in load_public_figures() if f.slug == slug)
            for slug in ("ms-dhoni", "virat-kohli")
        )
        debate_id = await run_debate(client, [str(dhoni.id), str(kohli.id)])

        result = (await client.get(f"/api/debates/{debate_id}/result")).json()
        assert {p["name"] for p in result["participants"]} == {"MS Dhoni", "Virat Kohli"}

    async def test_a_friend_can_debate_a_public_figure(self, client):  # noqa: F811
        await seed(client)
        [friend_id, _] = await create_friends(client)
        figure = load_public_figures()[0]
        debate = await client.post("/api/debates", json={
            "topic": "Is remote work better than office work?",
            "participant_ids": [friend_id, str(figure.id)],
        })
        assert debate.status_code == 201

    async def test_debate_counts_are_private_to_each_visitor(self, client):  # noqa: F811
        await seed(client)
        a, b = load_public_figures()[:2]
        await run_debate(client, [str(a.id), str(b.id)])

        counts = {r["friend_id"]: r["debate_count"] for r in await public_rows(client)}
        assert counts[str(a.id)] == counts[str(b.id)] == 1

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
            theirs = [r for r in (await other.get("/api/personas")).json() if r["is_public"]]
        assert all(r["debate_count"] == 0 for r in theirs)


@pytest.fixture(autouse=True)
def _fresh_figures():
    """Tests above swap the loader out; never let one leak into the next."""
    yield
    load_public_figures.cache_clear()

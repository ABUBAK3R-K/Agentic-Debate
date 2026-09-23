"""Past debates and saved personas, read back after the fact."""

from uuid import uuid4

from tests.conftest import PERSONA_FIXTURE
from tests.test_api import client, create_friends  # noqa: F401 — fixture


async def run_debate(client, friend_ids, topic="Is remote work better than office work?"):  # noqa: F811
    debate = (await client.post("/api/debates", json={
        "topic": topic, "participant_ids": friend_ids,
    })).json()
    await client.post(f"/api/debates/{debate['id']}/start")
    async with client.stream("GET", f"/api/debates/{debate['id']}/stream") as stream:
        async for _ in stream.aiter_lines():
            pass
    return debate["id"]


class TestPastDebates:
    async def test_the_list_starts_empty(self, client):  # noqa: F811
        response = await client.get("/api/debates")
        assert response.status_code == 200
        assert response.json() == []

    async def test_a_finished_debate_is_listed_with_its_winner(self, client):  # noqa: F811
        friend_ids = await create_friends(client)
        debate_id = await run_debate(client, friend_ids)

        [row] = (await client.get("/api/debates")).json()
        assert row["id"] == debate_id
        assert row["status"] == "COMPLETED"
        assert row["winner_name"] in {"Rahul", "Aman"}
        assert {p["friend_name"] for p in row["participants"]} == {"Rahul", "Aman"}
        assert {p["position"] for p in row["participants"]} == {"FOR", "AGAINST"}

    async def test_a_debate_not_yet_run_is_listed_without_a_winner(self, client):  # noqa: F811
        friend_ids = await create_friends(client)
        await client.post("/api/debates", json={
            "topic": "Cats are better than dogs", "participant_ids": friend_ids,
        })

        [row] = (await client.get("/api/debates")).json()
        assert row["status"] == "CREATED"
        assert row["winner_name"] is None

    async def test_the_transcript_holds_every_turn_in_order(self, client):  # noqa: F811
        friend_ids = await create_friends(client)
        debate_id = await run_debate(client, friend_ids)

        response = await client.get(f"/api/debates/{debate_id}")
        assert response.status_code == 200
        body = response.json()

        phases = [m["phase"] for m in body["messages"]]
        assert phases == ["OPENING"] * 2 + ["REBUTTAL"] * 2 + ["COUNTER"] * 2 + ["CLOSING"] * 2
        assert all(m["content"] and not m["failed"] for m in body["messages"])
        speakers = {m["participant_id"] for m in body["messages"]}
        assert speakers == {p["id"] for p in body["participants"]}

    async def test_an_unknown_debate_is_not_found(self, client):  # noqa: F811
        response = await client.get(f"/api/debates/{uuid4()}")
        assert response.status_code == 404


class TestSavedPersonas:
    async def test_a_friend_without_a_persona_is_listed_uncompiled(self, client):  # noqa: F811
        await create_friends(client)
        rows = (await client.get("/api/personas")).json()
        assert {row["name"] for row in rows} == {"Rahul", "Aman"}
        assert all(row["persona"] is None and row["version"] is None for row in rows)

    async def test_only_the_latest_persona_version_is_shown(self, client):  # noqa: F811
        friend_ids = await create_friends(client)
        await client.put(f"/api/personas/{friend_ids[0]}", json={"persona": PERSONA_FIXTURE})
        edited = dict(PERSONA_FIXTURE, values=["candour"])
        await client.put(f"/api/personas/{friend_ids[0]}", json={"persona": edited})

        rows = {row["friend_id"]: row for row in (await client.get("/api/personas")).json()}
        latest = rows[friend_ids[0]]
        assert latest["version"] == 2
        assert latest["persona"]["values"] == ["candour"]

    async def test_debates_are_counted_per_friend(self, client):  # noqa: F811
        friend_ids = await create_friends(client)
        await run_debate(client, friend_ids)

        rows = (await client.get("/api/personas")).json()
        assert all(row["debate_count"] == 1 for row in rows)

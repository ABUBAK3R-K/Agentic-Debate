"""The debate state machine, position assignment, and turn handling."""

import pytest
from sqlalchemy import select

from app.llm.structured import StructuredOutputError
from app.models import Debate, DebateMessage, DebateParticipant
from app.services.debate_engine import DebateEngine
from tests.fakes import FakeLLM, argument, debate_script


async def make_debate(db, friends, llm=None):
    engine = DebateEngine(db, llm or FakeLLM())
    debate = await engine.create_debate(
        topic="Is remote work better than office work?",
        participant_friend_ids=[f.id for f in friends],
        model_provider="test",
        model_name="test-model",
        temperature=0.8,
        top_p=1.0,
        max_tokens=500,
    )
    return engine, debate


class TestCreation:
    async def test_creates_two_participants_in_slot_order(self, db, two_friends):
        _, debate = await make_debate(db, two_friends)

        result = await db.execute(
            select(DebateParticipant)
            .where(DebateParticipant.debate_id == debate.id)
            .order_by(DebateParticipant.slot)
        )
        participants = list(result.scalars().all())

        assert [p.slot for p in participants] == [0, 1]
        assert [p.friend_id for p in participants] == [f.id for f in two_friends]

    async def test_rejects_anything_other_than_two_participants(self, db, two_friends):
        engine = DebateEngine(db, FakeLLM())
        with pytest.raises(ValueError, match="exactly two"):
            await engine.create_debate(
                topic="A topic that is long enough",
                participant_friend_ids=[two_friends[0].id],
                model_provider="test",
                model_name="test-model",
                temperature=0.8,
                top_p=1.0,
                max_tokens=500,
            )

    async def test_stores_the_model_settings_it_will_run_under(self, db, two_friends):
        _, debate = await make_debate(db, two_friends)
        assert (debate.model_name, debate.temperature, debate.top_p, debate.max_tokens) \
            == ("test-model", 0.8, 1.0, 500)

    async def test_assigns_both_judge_labels_exactly_once(self, db, two_friends):
        _, debate = await make_debate(db, two_friends)
        result = await db.execute(
            select(DebateParticipant).where(DebateParticipant.debate_id == debate.id)
        )
        labels = {p.participant_label for p in result.scalars().all()}
        assert labels == {"Participant A", "Participant B"}

    async def test_label_assignment_is_randomized_across_debates(self, db, two_friends):
        """The judge's "Participant A" must not always be the first friend —
        that would reintroduce exactly the ordering bias labels exist to remove."""
        seen = set()
        for _ in range(30):
            _, debate = await make_debate(db, two_friends)
            result = await db.execute(
                select(DebateParticipant)
                .where(DebateParticipant.debate_id == debate.id)
                .order_by(DebateParticipant.slot)
            )
            seen.add(list(result.scalars().all())[0].participant_label)
        assert seen == {"Participant A", "Participant B"}


class TestStateMachine:
    async def test_follows_the_prescribed_path(self, db, two_friends):
        engine, debate = await make_debate(db, two_friends)
        path = [
            "POSITIONING", "OPENING", "REBUTTAL",
            "COUNTER", "CLOSING", "JUDGING", "COMPLETED",
        ]
        for status in path:
            await engine._transition(debate, status)
            assert debate.status == status

    async def test_refuses_to_skip_a_phase(self, db, two_friends):
        engine, debate = await make_debate(db, two_friends)
        with pytest.raises(ValueError, match="Invalid transition"):
            await engine._transition(debate, "CLOSING")

    async def test_refuses_to_go_backwards(self, db, two_friends):
        engine, debate = await make_debate(db, two_friends)
        await engine._transition(debate, "POSITIONING")
        await engine._transition(debate, "OPENING")
        with pytest.raises(ValueError, match="Invalid transition"):
            await engine._transition(debate, "POSITIONING")

    async def test_stamps_completed_at_only_at_the_end(self, db, two_friends):
        engine, debate = await make_debate(db, two_friends)
        for status in ["POSITIONING", "OPENING", "REBUTTAL", "COUNTER", "CLOSING", "JUDGING"]:
            await engine._transition(debate, status)
            assert debate.completed_at is None
        await engine._transition(debate, "COMPLETED")
        assert debate.completed_at is not None


class TestPositions:
    async def test_backend_assigns_one_side_each(self, db, two_friends):
        engine, debate = await make_debate(db, two_friends)
        await engine.assign_positions(debate)

        participants = await engine._get_participants(debate.id)
        assert [p.position for p in participants] == ["FOR", "AGAINST"]

    async def test_positions_are_assigned_during_the_positioning_phase(self, db, two_friends):
        engine, debate = await make_debate(db, two_friends)
        await engine.assign_positions(debate)
        assert debate.status == "POSITIONING"


class TestTurns:
    async def test_a_failed_turn_is_recorded_as_failed_not_faked(self, db, two_friends):
        """The PRD forbids silently continuing with invalid data."""
        # Stream, then both structured retries, then unparseable text.
        llm = FakeLLM(
            structured_responses=[RuntimeError("nope")] * 3,
            text_responses=["I decline to produce JSON."],
        )
        engine, debate = await make_debate(db, two_friends, llm)
        await engine.assign_positions(debate)
        participants = await engine._get_participants(debate.id)
        context = await engine._load_participant_context(participants[0])

        events = [
            e async for e in engine._run_turn(
                debate, participants[0], context, "OPENING", 1, ""
            )
        ]

        assert [e.event_type for e in events] == ["turn_start", "turn_failed"]

        result = await db.execute(select(DebateMessage))
        message = result.scalar_one()
        assert message.content == ""
        assert message.structured_output["failed"] is True

    async def test_a_successful_turn_stores_the_full_structured_output(self, db, two_friends):
        llm = FakeLLM(structured_responses=[
            argument("Remote work wins on focus.", key_claims=["focus"], confidence=0.9)
        ])
        engine, debate = await make_debate(db, two_friends, llm)
        await engine.assign_positions(debate)
        participants = await engine._get_participants(debate.id)
        context = await engine._load_participant_context(participants[0])

        events = [
            e async for e in engine._run_turn(
                debate, participants[0], context, "OPENING", 1, ""
            )
        ]

        assert events[0].event_type == "turn_start"
        assert events[-1].event_type == "message"
        assert events[-1].content == "Remote work wins on focus."
        assert events[-1].position == "FOR"

        # The argument arrived as tokens before the final message.
        tokens = [e.content for e in events if e.event_type == "token"]
        assert "".join(tokens) == "Remote work wins on focus."

        result = await db.execute(select(DebateMessage))
        message = result.scalar_one()
        # The frontend renders `argument`; the rest is kept for later work.
        assert message.content == "Remote work wins on focus."
        assert message.structured_output["key_claims"] == ["focus"]
        assert message.structured_output["confidence"] == 0.9


class TestLivePreview:
    """A turn must reach the screen while it is being written, not after.

    The whole token/`JsonStringFieldExtractor` pipeline exists for this, and
    it is the part that silently stopped working: with the provider's JSON
    mode switched on, a real turn arrived as a single chunk and the debate
    screen sat empty for the length of every turn.
    """

    @staticmethod
    async def _turn_events(db, friends, llm):
        engine, debate = await make_debate(db, friends, llm)
        await engine.assign_positions(debate)
        participants = await engine._get_participants(debate.id)
        context = await engine._load_participant_context(participants[0])
        return [
            e async for e in engine._run_turn(
                debate, participants[0], context, "OPENING", 1, ""
            )
        ]

    async def test_a_chunked_turn_is_previewed_progressively(self, db, two_friends):
        text = "Remote work wins on focus, cost, and hiring reach."
        events = await self._turn_events(
            db, two_friends,
            FakeLLM(structured_responses=[argument(text)], chunk_size=7),
        )

        tokens = [e for e in events if e.event_type == "token"]
        assert len(tokens) > 1, (
            "one token event for a whole turn is not a live preview"
        )
        assert "".join(e.content for e in tokens) == text
        assert events[-1].content == text

    async def test_a_single_chunk_turn_is_still_correct(self, db, two_friends):
        """Degraded, but never wrong: `message` is the authoritative text."""
        text = "Remote work wins on focus, cost, and hiring reach."
        events = await self._turn_events(
            db, two_friends,
            FakeLLM(structured_responses=[argument(text)], chunk_size=None),
        )

        assert events[-1].event_type == "message"
        assert events[-1].content == text

        result = await db.execute(select(DebateMessage))
        assert result.scalar_one().content == text


class TestFullDebate:
    async def test_runs_all_four_rounds_and_completes(self, db, two_friends):
        llm = FakeLLM(structured_responses=debate_script())
        engine, debate = await make_debate(db, two_friends, llm)

        events = [event async for event in engine.run_debate(debate)]

        assert debate.status == "COMPLETED"
        assert [e.event_type for e in events].count("message") == 8
        assert events[-1].event_type == "debate_complete"

        phases = [e.phase for e in events if e.event_type == "phase_start"]
        assert phases == [
            "POSITIONING", "OPENING", "REBUTTAL", "COUNTER", "CLOSING", "JUDGING"
        ]

    async def test_every_participant_gets_identical_model_settings(self, db, two_friends):
        """The core constraint: agents differ by persona and position only."""
        llm = FakeLLM(structured_responses=debate_script())
        engine, debate = await make_debate(db, two_friends, llm)

        [event async for event in engine.run_debate(debate)]

        debater_calls = llm.calls[:-1]  # the last call is the judge
        settings = {
            (c["temperature"], c["max_tokens"], c["top_p"]) for c in debater_calls
        }
        assert settings == {(0.8, 500, 1.0)}

        # ...and the system prompts do differ, because the personas do.
        assert len({c["system_prompt"] for c in debater_calls}) == 2

    async def test_each_turn_sees_the_transcript_so_far(self, db, two_friends):
        llm = FakeLLM(structured_responses=debate_script())
        engine, debate = await make_debate(db, two_friends, llm)

        [event async for event in engine.run_debate(debate)]

        opening = llm.calls[0]["messages"][0]["content"]
        closing = llm.calls[7]["messages"][0]["content"]
        assert "TRANSCRIPT SO FAR" not in opening
        assert "Argument for opening turn 1" in closing

    async def test_no_backend_metadata_leaks_into_a_turn_prompt(self, db, two_friends):
        """A turn gets persona, topic, position, phase, transcript. Nothing else."""
        llm = FakeLLM(structured_responses=debate_script())
        engine, debate = await make_debate(db, two_friends, llm)

        [event async for event in engine.run_debate(debate)]

        for call in llm.calls[:-1]:
            prompt = call["messages"][0]["content"]
            assert str(debate.id) not in prompt
            assert "Participant A" not in prompt
            assert "Participant B" not in prompt

    async def test_a_crash_marks_the_debate_failed_and_reports_it(self, db, two_friends):
        llm = FakeLLM(structured_responses=[])  # runs out immediately
        engine, debate = await make_debate(db, two_friends, llm)

        events = [event async for event in engine.run_debate(debate)]

        assert debate.status == "FAILED"
        assert events[-1].event_type == "error"

    async def test_a_failed_turn_does_not_abort_the_debate(self, db, two_friends):
        script = debate_script()
        # The stream, the attempt and its retry all fail for one speaker.
        script[2:3] = [RuntimeError("stream breaks"), RuntimeError("attempt breaks"),
                       RuntimeError("retry breaks")]
        llm = FakeLLM(
            structured_responses=script,
            text_responses=["not json at all"],
        )
        engine, debate = await make_debate(db, two_friends, llm)

        events = [event async for event in engine.run_debate(debate)]

        assert debate.status == "COMPLETED"
        assert any(e.event_type == "turn_failed" for e in events)

"""The judge: blind to identity, and correctly un-blinded afterwards."""

import pytest
from sqlalchemy import select

from app.models import Evaluation
from app.services.debate_engine import DebateEngine
from app.services.judge_engine import JudgeEngine
from tests.fakes import FakeLLM, debate_script, judge_verdict


async def run_debate_to_verdict(db, friends, judge_winner="Participant A"):
    llm = FakeLLM(structured_responses=debate_script(judge_winner))
    engine = DebateEngine(db, llm)
    debate = await engine.create_debate(
        topic="Is remote work better than office work?",
        participant_friend_ids=[f.id for f in friends],
        model_provider="test",
        model_name="test-model",
        temperature=0.8,
        top_p=1.0,
        max_tokens=500,
    )
    events = [event async for event in engine.run_debate(debate)]
    return llm, debate, events


class TestBlindness:
    async def test_the_judge_never_sees_a_real_name(self, db, two_friends):
        llm, _, _ = await run_debate_to_verdict(db, two_friends)
        judge_call = llm.calls[-1]
        prompt = judge_call["messages"][0]["content"] + judge_call["system_prompt"]

        assert "Rahul" not in prompt
        assert "Aman" not in prompt
        assert "Participant A" in prompt
        assert "Participant B" in prompt

    async def test_the_judge_is_a_separate_call_from_the_debaters(self, db, two_friends):
        llm, _, _ = await run_debate_to_verdict(db, two_friends)
        judge_call = llm.calls[-1]
        debater_prompts = {c["system_prompt"] for c in llm.calls[:-1]}

        assert judge_call["system_prompt"] not in debater_prompts
        assert "impartial debate judge" in judge_call["system_prompt"]

    async def test_the_judge_runs_cooler_than_the_debaters(self, db, two_friends):
        llm, debate, _ = await run_debate_to_verdict(db, two_friends)
        assert llm.calls[-1]["temperature"] < debate.temperature


class TestVerdictMapping:
    async def test_the_winning_label_maps_back_to_the_right_friend(self, db, two_friends):
        llm, debate, events = await run_debate_to_verdict(db, two_friends)

        participants = await DebateEngine(db, llm)._get_participants(debate.id)
        winner_by_label = next(
            p for p in participants if p.participant_label == "Participant A"
        )
        expected_name = next(
            f.name for f in two_friends if f.id == winner_by_label.friend_id
        )

        assert events[-1].data["winner_name"] == expected_name

    async def test_it_maps_back_correctly_when_b_wins_too(self, db, two_friends):
        llm, debate, events = await run_debate_to_verdict(
            db, two_friends, judge_winner="Participant B"
        )

        participants = await DebateEngine(db, llm)._get_participants(debate.id)
        winner_by_label = next(
            p for p in participants if p.participant_label == "Participant B"
        )
        expected_name = next(
            f.name for f in two_friends if f.id == winner_by_label.friend_id
        )

        assert events[-1].data["winner_name"] == expected_name

    async def test_scores_are_stored_against_participant_ids_not_labels(self, db, two_friends):
        _, debate, _ = await run_debate_to_verdict(db, two_friends)

        result = await db.execute(
            select(Evaluation).where(Evaluation.debate_id == debate.id)
        )
        evaluation = result.scalar_one()
        scores = evaluation.scores_json["scores"]

        participants = await DebateEngine(db, FakeLLM())._get_participants(debate.id)
        assert set(scores) == {str(p.id) for p in participants}
        assert evaluation.scores_json["strongest_argument"]
        assert evaluation.scores_json["weakest_argument"]

    async def test_an_unknown_winner_label_is_an_error_not_a_guess(self, db, two_friends):
        llm = FakeLLM(structured_responses=debate_script())
        engine = DebateEngine(db, llm)
        debate = await engine.create_debate(
            topic="A topic that is long enough",
            participant_friend_ids=[f.id for f in two_friends],
            model_provider="test",
            model_name="test-model",
            temperature=0.8,
            top_p=1.0,
            max_tokens=500,
        )
        await engine.assign_positions(debate)

        rogue = FakeLLM(structured_responses=[judge_verdict("Participant Q")])
        with pytest.raises(ValueError, match="unknown participant"):
            await JudgeEngine(db, rogue).evaluate_debate(debate)


class TestJudgeModelRouting:
    """The judge may run on its own provider so it can be given a different
    model, and with it a rate-limit budget the eight turns are not competing
    for. It is the request most likely to be refused: it comes last, when the
    window is fullest."""

    async def test_the_judge_uses_the_judge_provider_when_given_one(
        self, db, two_friends
    ):
        debaters = FakeLLM(structured_responses=debate_script()[:-1])  # turns only
        judge = FakeLLM(structured_responses=[judge_verdict()])

        engine = DebateEngine(db, debaters, judge_llm=judge)
        debate = await engine.create_debate(
            topic="Is remote work better than office work?",
            participant_friend_ids=[f.id for f in two_friends],
            model_provider="test", model_name="test-model",
            temperature=0.8, top_p=1.0, max_tokens=500,
        )
        async for _ in engine.run_debate(debate):
            pass

        assert len(judge.calls) == 1, "the judge ran exactly once, on its own provider"
        assert not any(c["kind"] == "structured" and "impartial" in c["system_prompt"]
                       for c in debaters.calls), "no judging on the debaters' provider"

    async def test_it_falls_back_to_the_debaters_provider(self, db, two_friends):
        """One-argument construction is what every other caller uses."""
        llm = FakeLLM(structured_responses=debate_script())

        engine = DebateEngine(db, llm)
        debate = await engine.create_debate(
            topic="Is remote work better than office work?",
            participant_friend_ids=[f.id for f in two_friends],
            model_provider="test", model_name="test-model",
            temperature=0.8, top_p=1.0, max_tokens=500,
        )
        async for _ in engine.run_debate(debate):
            pass

        assert engine.judge_llm is llm

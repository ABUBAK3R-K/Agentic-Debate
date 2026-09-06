"""Prompt building — the one place personas become system prompts."""

import pytest

from app.llm.prompts import (
    build_debate_system_prompt,
    build_turn_prompt,
    format_transcript,
)
from tests.conftest import PERSONA_FIXTURE


class TestDebateSystemPrompt:
    def test_includes_every_part_of_the_persona(self):
        prompt = build_debate_system_prompt(PERSONA_FIXTURE)

        assert "Rahul" in prompt
        assert "skeptical" in prompt
        assert "rigor" in prompt
        assert "quantitative" in prompt          # reasoning style
        assert "spots weak claims" in prompt     # strengths
        assert "slow to commit" in prompt        # weaknesses
        assert "deadpan" in prompt               # communication style
        assert "asks for sources" in prompt      # debate tactics

    def test_states_that_this_is_a_simulation(self):
        prompt = build_debate_system_prompt(PERSONA_FIXTURE)
        assert "NOT the real person" in prompt

    def test_carries_the_six_rules_the_prd_specifies(self):
        prompt = build_debate_system_prompt(PERSONA_FIXTURE)
        rules = prompt.split("RULES")[1]
        assert "6." in rules
        assert "7." not in rules

    def test_survives_a_persona_with_empty_fields(self):
        prompt = build_debate_system_prompt({"name": "Sam"})
        assert "Sam" in prompt
        assert "unspecified" in prompt


class TestTurnPrompts:
    def test_the_opening_has_no_transcript_to_show(self):
        prompt = build_turn_prompt("OPENING", "Topic", "FOR", "")
        assert "TRANSCRIPT SO FAR" not in prompt
        assert "FOR" in prompt

    @pytest.mark.parametrize("phase", ["REBUTTAL", "COUNTER", "CLOSING"])
    def test_later_phases_carry_the_transcript(self, phase):
        prompt = build_turn_prompt(phase, "Topic", "AGAINST", "Earlier arguments here")
        assert "Earlier arguments here" in prompt
        assert "AGAINST" in prompt

    @pytest.mark.parametrize(
        "phase", ["OPENING", "REBUTTAL", "COUNTER", "CLOSING"]
    )
    def test_every_phase_asks_for_structured_output(self, phase):
        prompt = build_turn_prompt(phase, "Topic", "FOR", "transcript")
        assert "opponent_claim_addressed" in prompt
        assert "confidence" in prompt

    def test_an_unknown_phase_is_refused(self):
        with pytest.raises(ValueError, match="No prompt builder"):
            build_turn_prompt("FREESTYLE", "Topic", "FOR", "")


class TestTranscript:
    def test_labels_each_turn_with_speaker_and_phase(self):
        transcript = format_transcript([
            {"participant_name": "Rahul", "phase": "OPENING", "content": "First."},
            {"participant_name": "Aman", "phase": "OPENING", "content": "Second."},
        ])
        assert "[Rahul — OPENING]" in transcript
        assert "[Aman — OPENING]" in transcript
        assert transcript.index("First.") < transcript.index("Second.")

    def test_an_empty_transcript_is_empty(self):
        assert format_transcript([]) == ""

"""The structured-output recovery chain: retry → parser → fail."""

import json

import pytest

from app.llm.structured import (
    JsonStringFieldExtractor,
    StructuredOutputError,
    generate_structured_resilient,
    lenient_parse,
)
from app.schemas import AgentStructuredOutput
from tests.fakes import FakeLLM, argument, json_response


async def _run(llm):
    return await generate_structured_resilient(
        llm,
        system_prompt="system",
        messages=[{"role": "user", "content": "go"}],
        response_model=AgentStructuredOutput,
        temperature=0.8,
        max_tokens=500,
        context="test",
    )


class TestLenientParse:
    def test_parses_bare_json(self):
        result = lenient_parse(json_response(argument("hello")), AgentStructuredOutput)
        assert result.argument == "hello"

    def test_strips_markdown_fences(self):
        raw = f"```json\n{json_response(argument('fenced'))}\n```"
        assert lenient_parse(raw, AgentStructuredOutput).argument == "fenced"

    def test_ignores_commentary_around_the_object(self):
        raw = (
            "Sure! Here is the JSON you asked for:\n"
            f"{json_response(argument('surrounded'))}\n"
            "Let me know if you want changes."
        )
        assert lenient_parse(raw, AgentStructuredOutput).argument == "surrounded"

    def test_braces_inside_argument_text_do_not_confuse_it(self):
        raw = json_response(argument("Consider the set {a, b} — it proves nothing."))
        assert "{a, b}" in lenient_parse(raw, AgentStructuredOutput).argument

    def test_prose_with_no_json_is_a_failure_not_a_guess(self):
        with pytest.raises(StructuredOutputError):
            lenient_parse("I think the answer is probably yes.", AgentStructuredOutput)

    def test_json_of_the_wrong_shape_is_a_failure(self):
        with pytest.raises(StructuredOutputError):
            lenient_parse('{"unrelated": true}', AgentStructuredOutput)


class TestRecoveryChain:
    async def test_first_attempt_succeeds_without_retrying(self):
        llm = FakeLLM(structured_responses=[argument("clean")])
        result = await _run(llm)
        assert result.argument == "clean"
        assert len(llm.calls) == 1

    async def test_retries_once_after_a_failure(self):
        llm = FakeLLM(structured_responses=[RuntimeError("flaky"), argument("second")])
        result = await _run(llm)
        assert result.argument == "second"
        assert len(llm.calls) == 2

    async def test_falls_back_to_text_and_parses_it(self):
        llm = FakeLLM(
            structured_responses=[RuntimeError("no"), RuntimeError("still no")],
            text_responses=[f"```json\n{json_response(argument('salvaged'))}\n```"],
        )
        result = await _run(llm)
        assert result.argument == "salvaged"
        assert [c["kind"] for c in llm.calls] == ["structured", "structured", "text"]

    async def test_raises_rather_than_inventing_data(self):
        llm = FakeLLM(
            structured_responses=[RuntimeError("no"), RuntimeError("no")],
            text_responses=["Honestly, I'd rather not answer that."],
        )
        with pytest.raises(StructuredOutputError):
            await _run(llm)

    async def test_raises_when_the_text_fallback_itself_errors(self):
        llm = FakeLLM(
            structured_responses=[RuntimeError("no"), RuntimeError("no")],
            text_responses=[ConnectionError("provider down")],
        )
        with pytest.raises(StructuredOutputError):
            await _run(llm)


class TestJsonStringFieldExtractor:
    """Pulling live text out of a JSON stream, chunked at awkward boundaries."""

    @staticmethod
    def _stream(raw: str, size: int) -> tuple[str, bool]:
        extractor = JsonStringFieldExtractor("argument")
        out = "".join(
            extractor.feed(raw[i : i + size]) for i in range(0, len(raw), size)
        )
        return out, extractor.done

    @pytest.mark.parametrize("size", [1, 2, 3, 7, 100])
    def test_reassembles_the_argument_at_any_chunk_size(self, size):
        raw = json.dumps(argument("Remote work wins on focus."))
        text, done = self._stream(raw, size)
        assert text == "Remote work wins on focus."
        assert done

    @pytest.mark.parametrize("size", [1, 2, 3, 5, 7])
    def test_escape_sequences_split_across_chunks(self, size):
        original = 'She said "no" —\nthen left.\tBackslash: \\ and a slash /'
        raw = json.dumps(argument(original))
        text, _ = self._stream(raw, size)
        assert text == original

    @pytest.mark.parametrize("size", [1, 3, 7])
    def test_unicode_escapes_split_across_chunks(self, size):
        raw = json.dumps(argument("café — naïve"), ensure_ascii=True)
        text, _ = self._stream(raw, size)
        assert text == "café — naïve"

    def test_stops_at_the_end_of_the_field(self):
        raw = json.dumps(argument("Short.")) + '{"argument": "later noise"}'
        text, done = self._stream(raw, 4)
        assert text == "Short."
        assert done

    def test_yields_nothing_until_the_field_appears(self):
        extractor = JsonStringFieldExtractor("argument")
        assert extractor.feed('{"confidence": 0.7, "key_claims": ["a"], ') == ""
        assert extractor.feed('"argument": "Now it starts') == "Now it starts"

    def test_keeps_the_raw_text_for_validation_afterwards(self):
        payload = argument("Anything at all.")
        extractor = JsonStringFieldExtractor("argument")
        raw = json.dumps(payload)
        for i in range(0, len(raw), 5):
            extractor.feed(raw[i : i + 5])
        assert lenient_parse(extractor.raw, AgentStructuredOutput).confidence == 0.7

"""Tests for relevance scoring and embedding reuse."""

# pylint: disable=missing-function-docstring

import pytest


def test_keyword_match_outscores_unrelated_text(llm_processor):
    matched = llm_processor.generate_relevance_score(
        "climbing harness buying guide", "harness"
    )
    unrelated = llm_processor.generate_relevance_score(
        "sourdough bread starter recipes", "harness"
    )

    assert matched > unrelated


@pytest.mark.parametrize(
    "text",
    ["harness harness harness", "sourdough bread starter recipes", ""],
)
def test_scores_stay_within_the_unit_range(llm_processor, text):
    assert 0.0 <= llm_processor.generate_relevance_score(text, "harness") <= 1.0


def test_repeated_text_is_embedded_only_once(llm_processor):
    llm_processor.generate_relevance_score("climbing harness guide", "harness")
    after_first_pass = list(llm_processor.model.encoded)

    llm_processor.generate_relevance_score("climbing harness guide", "harness")

    assert llm_processor.model.encoded == after_first_pass


def test_embeddings_are_written_to_the_cache_directory(llm_processor, tmp_path):
    llm_processor.generate_relevance_score("climbing harness guide", "harness")

    assert list((tmp_path / "embeddings_cache").glob("*.npy"))


def test_process_item_resolves_relative_hrefs(llm_processor):
    result = llm_processor.process_item(
        {
            "keyword": "Harness",
            "processed_text": "climbing harness buying guide",
            "source_url": "https://example.com",
            "href": "/reviews/harness-guide",
        }
    )

    analysis = result["relevance_analysis"]
    assert analysis["href_url"] == "https://example.com/reviews/harness-guide"
    assert analysis["keyword"] == "harness"
    assert 0.0 <= analysis["score"] <= 1.0


def test_process_item_leaves_absolute_hrefs_alone(llm_processor):
    result = llm_processor.process_item(
        {
            "keyword": "ropes",
            "processed_text": "climbing ropes",
            "source_url": "https://example.com",
            "href": "https://shop.example.com/ropes",
        }
    )

    assert result["relevance_analysis"]["href_url"] == "https://shop.example.com/ropes"


def test_process_item_leaves_the_queued_item_untouched(llm_processor):
    item = {
        "keyword": "harness",
        "processed_text": "climbing harness guide",
        "source_url": "https://example.com",
        "href": "/guide",
    }

    result = llm_processor.process_item(item)

    assert "relevance_analysis" not in item
    assert result["href"] == "/guide"

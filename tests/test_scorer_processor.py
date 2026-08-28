"""Tests for relevance scoring and embedding reuse."""

# pylint: disable=missing-function-docstring

import pytest


def test_keyword_match_outscores_unrelated_text(scorer_processor):
    matched = scorer_processor.generate_relevance_score(
        "climbing harness buying guide", "harness"
    )
    unrelated = scorer_processor.generate_relevance_score(
        "sourdough bread starter recipes", "harness"
    )

    assert matched > unrelated


@pytest.mark.parametrize(
    "text",
    ["harness harness harness", "sourdough bread starter recipes", ""],
)
def test_scores_stay_within_the_unit_range(scorer_processor, text):
    assert 0.0 <= scorer_processor.generate_relevance_score(text, "harness") <= 1.0


def test_repeated_text_is_embedded_only_once(scorer_processor):
    scorer_processor.generate_relevance_score("climbing harness guide", "harness")
    after_first_pass = list(scorer_processor.model.encoded)

    scorer_processor.generate_relevance_score("climbing harness guide", "harness")

    assert scorer_processor.model.encoded == after_first_pass


def test_embeddings_are_written_to_the_cache_directory(scorer_processor, tmp_path):
    scorer_processor.generate_relevance_score("climbing harness guide", "harness")

    assert list((tmp_path / "embeddings_cache").glob("*.npy"))


def test_process_item_resolves_relative_hrefs(scorer_processor):
    result = scorer_processor.process_item(
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


@pytest.mark.parametrize(
    "source_url, href, expected",
    [
        (
            "https://example.com/",
            "/reviews/harness-guide",
            "https://example.com/reviews/harness-guide",
        ),
        ("https://example.com/", "#anchor", "https://example.com/#anchor"),
        # Non-http schemes are not page-relative and must survive untouched.
        ("https://example.com/", "mailto:shop@example.com", "mailto:shop@example.com"),
        ("https://example.com/", "tel:15550100", "tel:15550100"),
    ],
)
def test_process_item_resolves_hrefs_against_the_source_page(
    scorer_processor, source_url, href, expected
):
    result = scorer_processor.process_item(
        {
            "keyword": "harness",
            "processed_text": "climbing harness buying guide",
            "source_url": source_url,
            "href": href,
        }
    )

    assert result["relevance_analysis"]["href_url"] == expected


def test_process_item_leaves_absolute_hrefs_alone(scorer_processor):
    result = scorer_processor.process_item(
        {
            "keyword": "ropes",
            "processed_text": "climbing ropes",
            "source_url": "https://example.com",
            "href": "https://shop.example.com/ropes",
        }
    )

    assert result["relevance_analysis"]["href_url"] == "https://shop.example.com/ropes"


def test_process_item_leaves_the_queued_item_untouched(scorer_processor):
    item = {
        "keyword": "harness",
        "processed_text": "climbing harness guide",
        "source_url": "https://example.com",
        "href": "/guide",
    }

    result = scorer_processor.process_item(item)

    assert "relevance_analysis" not in item
    assert result["href"] == "/guide"

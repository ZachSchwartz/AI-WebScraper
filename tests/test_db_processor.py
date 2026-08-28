"""Tests for the database layer that stores scored links."""

# pylint: disable=missing-function-docstring,redefined-outer-name,unused-argument

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from db_processor import Base, DatabaseProcessor, ScrapedItem


@pytest.fixture
def processor():
    """A processor bound to a throwaway in-memory database."""
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield DatabaseProcessor(engine=engine)
    engine.dispose()


def stored_items(processor):
    """Every row currently in the database."""
    session = processor.session()
    try:
        return session.query(ScrapedItem).all()
    finally:
        session.close()


def test_process_item_stores_the_scored_link(processor, scored):
    processor.process_item(scored())

    item = stored_items(processor)[0]
    assert item.keyword == "harness"
    assert item.source_url == "https://example.com/"
    assert item.href_url == "https://example.com/harness"
    assert item.relevance_score == 0.8
    assert item.job_id == "job-1"
    assert item.raw_data["relevance_analysis"]["score"] == 0.8


def test_process_item_returns_the_item_it_was_given(processor, scored):
    item = scored()

    assert processor.process_item(item) is item


def test_rescraping_a_link_replaces_its_row_rather_than_duplicating_it(
    processor, scored
):
    processor.process_item(scored(score=0.3))
    processor.process_item(scored(score=0.9))

    items = stored_items(processor)
    assert len(items) == 1
    assert items[0].relevance_score == 0.9


def test_a_different_link_on_the_same_page_gets_its_own_row(processor, scored):
    processor.process_item(scored(href="https://example.com/harness"))
    processor.process_item(scored(href="https://example.com/rope"))

    assert len(stored_items(processor)) == 2


def test_a_link_the_scorer_never_scored_stores_a_null_score(processor, scored):
    item = scored()
    del item["relevance_analysis"]["score"]

    processor.process_item(item)

    assert stored_items(processor)[0].relevance_score is None


def test_an_item_the_scorer_could_not_analyse_is_rejected(processor):
    with pytest.raises(ValueError):
        processor.process_item({"job_id": "job-1", "relevance_analysis": {}})

    assert stored_items(processor) == []


def test_a_failed_write_is_raised_rather_than_reported_as_stored(
    processor, scored, monkeypatch
):
    def refuse_to_commit(self):
        raise SQLAlchemyError("the database is unreachable")

    monkeypatch.setattr(sa.orm.Session, "commit", refuse_to_commit)

    with pytest.raises(SQLAlchemyError):
        processor.process_item(scored())


def test_the_repr_names_the_columns_the_model_actually_has(processor, scored):
    processor.process_item(scored())

    assert repr(stored_items(processor)[0]) == (
        "<ScrapedItem(id=1, href_url='https://example.com/harness', "
        "relevance_score=0.8)>"
    )

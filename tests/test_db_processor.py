"""Tests for the database layer that stores scored links."""

# pylint: disable=missing-function-docstring,redefined-outer-name,unused-argument

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from db_processor import Base, DatabaseProcessor, ScrapedItem, ensure_schema


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
    processor.process_item(scored(score=0.3, job_id="job-1"))
    processor.process_item(scored(score=0.9, job_id="job-2"))

    items = stored_items(processor)
    assert len(items) == 1
    assert items[0].relevance_score == 0.9


def test_rescraping_a_link_may_lower_its_score(processor, scored):
    """A page that stops being about the keyword has to be allowed to say so."""
    processor.process_item(scored(score=0.9, job_id="job-1"))
    processor.process_item(scored(score=0.3, job_id="job-2"))

    items = stored_items(processor)
    assert len(items) == 1
    assert items[0].relevance_score == 0.3
    assert items[0].job_id == "job-2"


@pytest.mark.parametrize("scores", [(0.3, 0.9), (0.9, 0.3)])
def test_a_link_found_twice_on_a_page_keeps_its_strongest_score(
    processor, scored, scores
):
    """One job collides with itself, and the API reports the strongest score.

    A page can link to the same place from its nav and its body, and each
    occurrence is scored on different surrounding text. Whichever occurrence
    drains last must not decide the row, or the stored score disagrees with the
    one the scrape returned.
    """
    for score in scores:
        processor.process_item(scored(score=score, job_id="job-1"))

    items = stored_items(processor)
    assert len(items) == 1
    assert items[0].relevance_score == 0.9


def test_a_second_occurrence_scores_a_link_the_scorer_left_unscored(processor, scored):
    unscored = scored(job_id="job-1")
    del unscored["relevance_analysis"]["score"]

    processor.process_item(unscored)
    processor.process_item(scored(score=0.4, job_id="job-1"))

    assert stored_items(processor)[0].relevance_score == 0.4


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


def test_the_database_refuses_a_second_row_for_the_same_link(processor, scored):
    """The constraint, not the write path, is what keeps a link to one row.

    Two scrapes of a page running at once would both find no existing row, so
    the guarantee has to live somewhere neither of them can race past.
    """
    processor.process_item(scored())

    session = processor.session()
    try:
        session.add(
            ScrapedItem(
                keyword="harness",
                source_url="https://example.com/",
                href_url="https://example.com/harness",
                relevance_score=0.1,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_a_rescrape_keeps_the_row_it_replaces(processor, scored):
    processor.process_item(scored(score=0.3))
    first_id = stored_items(processor)[0].id

    processor.process_item(scored(score=0.9))

    assert stored_items(processor)[0].id == first_id


@pytest.mark.parametrize("missing", ["keyword", "source_url", "href_url"])
def test_a_link_missing_part_of_its_identity_is_rejected(processor, scored, missing):
    item = scored()
    del item["relevance_analysis"][missing]

    with pytest.raises(ValueError):
        processor.process_item(item)


def test_an_engine_with_no_upsert_says_so_rather_than_storing_a_duplicate(
    processor, scored, monkeypatch
):
    monkeypatch.setattr(type(processor.engine.dialect), "name", "oracle")

    with pytest.raises(NotImplementedError):
        processor.process_item(scored())


def test_ensure_schema_creates_the_tables_the_models_declare():
    engine = sa.create_engine("sqlite://")

    ensure_schema(engine)

    assert "scraped_items" in sa.inspect(engine).get_table_names()
    engine.dispose()

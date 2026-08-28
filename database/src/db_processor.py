"""
Database persistence for scored items taken off the Redis queue.
"""

import logging
import os
from datetime import datetime
from typing import Any, Callable, Dict, Optional
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import QueuePool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LINK_IDENTITY = ("keyword", "source_url", "href_url")
NOW = sa.text("CURRENT_TIMESTAMP")

_UPSERT_INSERT: Dict[str, Callable[..., Any]] = {
    "postgresql": postgresql.insert,
    "sqlite": sqlite.insert,
}


class Base(DeclarativeBase):
    """Declarative base for the models this service stores."""


class ScrapedItem(Base):
    """One link, scored against the keyword the page was scraped for.

    The unique constraint indexes the keyword as its leading column, which
    serves a filter on the keyword alone; a second index would be dead weight.
    """

    __tablename__ = "scraped_items"
    __table_args__ = (
        sa.UniqueConstraint(*LINK_IDENTITY, name="uq_scraped_items_link"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    keyword: Mapped[str]
    source_url: Mapped[str] = mapped_column(index=True)
    href_url: Mapped[str] = mapped_column(index=True)
    relevance_score: Mapped[Optional[float]] = mapped_column(index=True)
    job_id: Mapped[Optional[str]] = mapped_column(index=True)
    raw_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        sa.JSON().with_variant(postgresql.JSONB, "postgresql")
    )
    processed_date: Mapped[datetime] = mapped_column(server_default=NOW)

    def __repr__(self):
        return (
            f"<ScrapedItem(id={self.id}, href_url='{self.href_url}', "
            f"relevance_score={self.relevance_score})>"
        )


class DatabaseProcessor:
    """Processes items from Redis queue and stores them in SQL database."""

    _engine = None

    @classmethod
    def get_engine(cls) -> sa.Engine:
        """Get or create the shared Postgres engine with connection pooling."""
        if cls._engine is None:
            db_user = os.getenv("DB_USER", "postgres")
            db_password = os.getenv("DB_PASSWORD", "postgres")
            db_host = os.getenv("DB_HOST", "postgres")
            db_port = os.getenv("DB_PORT", "5432")
            db_name = os.getenv("DB_NAME", "scraper")

            db_url = (
                f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            )

            cls._engine = sa.create_engine(
                db_url,
                poolclass=QueuePool,
                pool_size=5,
                max_overflow=10,
                pool_timeout=30,
                pool_recycle=1800,
                pool_pre_ping=True,
                connect_args={"application_name": "scraper"},
            )

            logger.info("DatabaseProcessor connected to %s", db_host)

        return cls._engine

    def __init__(self, engine: Optional[sa.Engine] = None):
        """Initialize the database processor.

        Args:
            engine: Engine to bind sessions to. Defaults to the pooled Postgres
                engine; tests bind a throwaway one instead.
        """
        self.engine = engine if engine is not None else self.get_engine()
        self.session = sessionmaker(bind=self.engine)

    def _upsert(self, values: Dict[str, Any]) -> sa.Executable:
        """Build the statement that stores a link, replacing any earlier row.

        The unique constraint on the link is what makes a rescrape idempotent,
        and the collision is settled by the database rather than by reading
        first and writing after: two scrapes of one page running at once would
        both find no existing row and both insert.
        """
        try:
            insert = _UPSERT_INSERT[self.engine.dialect.name]
        except KeyError as error:
            raise NotImplementedError(
                f"Storing a link needs an upsert, which {self.engine.dialect.name} "
                "has no statement for"
            ) from error

        statement = insert(ScrapedItem).values(**values)
        return statement.on_conflict_do_update(
            index_elements=list(LINK_IDENTITY),
            set_={
                "relevance_score": statement.excluded.relevance_score,
                "job_id": statement.excluded.job_id,
                "raw_data": statement.excluded.raw_data,
                "processed_date": NOW,
            },
        )

    def process_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Store one scored item from the Redis queue in the database.

        Args:
            item: Dictionary containing processed data from the scorer

        Returns:
            The original item, for compatibility with queue_util

        Raises:
            ValueError: if the scorer left no analysis to store.
            SQLAlchemyError: if the row cannot be written.

            Either way the caller drops the item rather than reporting an
            unstored link back to the user as a result.
        """
        analysis = item.get("relevance_analysis", {})
        values: Dict[str, Any] = {
            column: analysis.get(column) for column in LINK_IDENTITY
        }
        if not all(values.values()):
            raise ValueError("Item names no link, page, and keyword to store it under")

        values["relevance_score"] = analysis.get("score")
        values["job_id"] = item.get("job_id")
        values["raw_data"] = item

        session = self.session()
        try:
            session.execute(self._upsert(values))
            session.commit()
            logger.debug("Stored %s", values["href_url"])
        except SQLAlchemyError:
            session.rollback()
            logger.exception("Failed to store %s", values["href_url"])
            raise
        finally:
            session.close()

        return item


def ensure_schema(engine: Optional[sa.Engine] = None) -> None:
    """Create the tables the models declare, if they are not there already.

    The models are the only definition of this schema, so there is no
    hand-written DDL for them to drift from. This is not a migration: a change
    to a table that already exists still needs the volume recreated.
    """
    Base.metadata.create_all(
        engine if engine is not None else DatabaseProcessor.get_engine()
    )

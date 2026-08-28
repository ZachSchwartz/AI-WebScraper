"""
Database persistence for scored items taken off the Redis queue.
"""

import logging
import os
from typing import Any, Dict, Optional
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create SQLAlchemy base
Base = declarative_base()


# Define ScrapedItem model
class ScrapedItem(Base):
    """Model for storing scraped items in the database."""

    __tablename__ = "scraped_items"

    id = sa.Column(sa.Integer, primary_key=True)
    keyword = sa.Column(sa.String, nullable=True)
    source_url = sa.Column(sa.String, nullable=False)
    href_url = sa.Column(sa.String, nullable=True)
    relevance_score = sa.Column(sa.Float, nullable=True)
    job_id = sa.Column(sa.String, nullable=True)
    raw_data = sa.Column(sa.JSON, nullable=True)

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
            # Get database connection details from environment variables
            db_user = os.getenv("DB_USER", "postgres")
            db_password = os.getenv("DB_PASSWORD", "postgres")
            db_host = os.getenv("DB_HOST", "postgres")
            db_port = os.getenv("DB_PORT", "5432")
            db_name = os.getenv("DB_NAME", "scraper")

            # Create database URL
            db_url = (
                f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            )

            # Create the SQLAlchemy engine with connection pooling
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

    def check_existing_item(
        self, session, keyword: str, source_url: str, href_url: str
    ) -> None:
        """Delete the row a rescrape of this link is about to replace."""
        existing_item = (
            session.query(ScrapedItem)
            .filter(
                ScrapedItem.keyword == keyword,
                ScrapedItem.source_url == source_url,
                ScrapedItem.href_url == href_url,
            )
            .first()
        )

        if existing_item:
            logger.info("Replacing existing item %d", existing_item.id)
            session.delete(existing_item)

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
        relevance_analysis = item.get("relevance_analysis", {})
        if not relevance_analysis.get("source_url"):
            raise ValueError("Item carries no scored link to store")

        db_item = ScrapedItem(
            keyword=relevance_analysis.get("keyword"),
            source_url=relevance_analysis.get("source_url"),
            href_url=relevance_analysis.get("href_url"),
            relevance_score=relevance_analysis.get("score"),
            job_id=item.get("job_id"),
            raw_data=item,
        )

        session = self.session()
        try:
            self.check_existing_item(
                session, db_item.keyword, db_item.source_url, db_item.href_url
            )
            session.add(db_item)
            session.commit()
            logger.debug("Stored %r", db_item)
        except SQLAlchemyError:
            session.rollback()
            logger.exception("Failed to store %s", relevance_analysis.get("href_url"))
            raise
        finally:
            session.close()

        return item

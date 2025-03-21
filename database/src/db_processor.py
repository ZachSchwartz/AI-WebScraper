from typing import Dict, Any
import sqlalchemy as sa
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
import os
import logging
from sqlalchemy import create_engine

# Create SQLAlchemy base
Base = declarative_base()

# Define ScrapedItem model
class ScrapedItem(Base):
    """Model for storing scraped items in the database."""
    
    __tablename__ = "scraped_items"
    
    id = sa.Column(sa.Integer, primary_key=True)
    url = sa.Column(sa.String, nullable=False)
    title = sa.Column(sa.String, nullable=True)
    text_content = sa.Column(sa.Text, nullable=True)
    source_url = sa.Column(sa.String, nullable=True)
    keyword = sa.Column(sa.String, nullable=True)
    relevance_score = sa.Column(sa.Float, nullable=True)
    processed_date = sa.Column(sa.DateTime, default=sa.func.now())
    raw_data = sa.Column(sa.JSON, nullable=True)
    
    def __repr__(self):
        return f"<ScrapedItem(id={self.id}, url='{self.url}', relevance_score={self.relevance_score})>"


class DatabaseProcessor:
    """Processes items from Redis queue and stores them in SQL database."""
    
    _engine = None
    _Session = None
    
    @classmethod
    def get_engine(cls):
        """Get or create the SQLAlchemy engine with connection pooling."""
        if cls._engine is None:
            # Get database connection details from environment variables
            db_user = os.getenv("DB_USER", "postgres")
            db_password = os.getenv("DB_PASSWORD", "postgres")
            db_host = os.getenv("DB_HOST", "postgres")
            db_port = os.getenv("DB_PORT", "5432")
            db_name = os.getenv("DB_NAME", "scraper")
            
            # Create database URL
            db_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            
            # Create the SQLAlchemy engine with connection pooling
            cls._engine = sa.create_engine(
                db_url,
                poolclass=QueuePool,
                pool_size=5,
                max_overflow=10,
                pool_timeout=30,
                pool_recycle=1800,
                pool_pre_ping=True,
                connect_args={"application_name": "scraper"}
            )
            
            # Create session factory
            cls._Session = sessionmaker(bind=cls._engine)
            
            print(f"DatabaseProcessor initialized with connection to {db_host}")
        
        return cls._engine
    
    def __init__(self):
        """Initialize the database processor."""
        self.engine = self.get_engine()
        self.Session = self._Session
    
    def process_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process an item from the Redis queue and store it in the database.
        
        Args:
            item: Dictionary containing processed data from LLM
            
        Returns:
            The original item, for compatibility with queue_manager
        """
        try:
            print(f"\nProcessing item from Redis queue:")
            print(f"Item keys: {list(item.keys())}")
            relevance_analysis = item.get("relevance_analysis", {})
            
            # Extract data from item
            keyword = relevance_analysis.get("keyword", "")
            source_url = relevance_analysis.get("source_url", "")
            href_url = relevance_analysis.get("scraped_url", "")
            score = relevance_analysis.get("score", "")
            
            # Create new database item
            db_item = ScrapedItem(
                keyword=keyword,
                source_url=source_url,
                href_url=href_url,
                relevance_score=score,
                raw_data=item
            )
            
            # Save to database
            session = self.Session()
            try:
                print("\nAttempting to save to database...")
                session.add(db_item)
                session.commit()
                print(f"Database item: {db_item}")
            except Exception as e:
                session.rollback()
                print(f"Error saving item to database: {str(e)}")
                print(f"Error type: {type(e)}")
                import traceback
                print(f"Traceback: {traceback.format_exc()}")
            finally:
                session.close()

            return item  # Return the original item for compatibility
            
        except Exception as e:
            print(f"Error processing item: {str(e)}")
            return item 

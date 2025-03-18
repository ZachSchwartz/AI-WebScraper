"""
Database processor for storing processed items from Redis queue into SQL database.
"""

from typing import Dict, Any
import sqlalchemy as sa
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
import json
import os

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
            
            # Create SQLAlchemy engine with connection pooling
            cls._engine = sa.create_engine(
                db_url,
                poolclass=QueuePool,
                pool_size=5,  # Number of permanent connections to keep
                max_overflow=10,  # Number of additional connections to allow
                pool_timeout=30,  # Seconds to wait before giving up on getting a connection
                pool_recycle=1800,  # Recycle connections after 30 minutes
                pool_pre_ping=True  # Enable connection health checks
            )
            
            # Create tables if they don't exist
            Base.metadata.create_all(cls._engine)
            
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
            # Extract data from item
            url = item.get("href", "")
            title = item.get("title", "")
            text_content = item.get("processed_text", "")
            source_url = item.get("source_url", "")
            
            # Extract relevance analysis if available
            relevance_analysis = item.get("relevance_analysis", {})
            keyword = relevance_analysis.get("keyword", "")
            relevance_score = relevance_analysis.get("score", 0.0)
            
            # Create new database item
            db_item = ScrapedItem(
                url=url,
                title=title,
                text_content=text_content,
                source_url=source_url,
                keyword=keyword,
                relevance_score=relevance_score,
                raw_data=item  # Store the entire item as JSON
            )
            
            # Save to database
            session = self.Session()
            try:
                session.add(db_item)
                session.commit()
                print(f"Item from {url} saved to database with relevance score: {relevance_score}")
                print(db_item)
            except Exception as e:
                session.rollback()
                print(f"Error saving item to database: {str(e)}")
            finally:
                session.close()
                
            return item  # Return the original item for compatibility
            
        except Exception as e:
            print(f"Error processing item for database: {str(e)}")
            return item  # Return the original item if processing fails 
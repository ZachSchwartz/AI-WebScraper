"""
Error utility functions for the web scraper.
"""

from typing import Dict, Any, Optional

def format_error(error_type: str, message: str, url: Optional[str] = None) -> Dict[str, Any]:
    """
    Format an error message for the web scraper.
    """
    return {"error": error_type, "message": message, "url": url}
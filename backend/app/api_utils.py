"""Utilities for API failover logic and rate limit handling."""
import time
import logging
from typing import Callable, Any, Optional, List
from functools import wraps
from app.exceptions import APIFailoverException, RateLimitException
from app.logging_config import api_call_logger

logger = logging.getLogger(__name__)


class APIFailoverHandler:
    """Handles API failover logic with multiple data sources."""
    
    def __init__(self):
        self.attempted_sources = []
    
    def try_sources(self, sources: List[tuple], field: str = None) -> Any:
        """
        Try multiple API sources in sequence until one succeeds.
        
        Args:
            sources: List of tuples (source_name, callable_function, *args)
            field: Optional field name being retrieved
            
        Returns:
            Result from first successful source
            
        Raises:
            APIFailoverException: If all sources fail
        """
        self.attempted_sources = []
        last_error = None
        
        for source_info in sources:
            source_name = source_info[0]
            source_func = source_info[1]
            source_args = source_info[2:] if len(source_info) > 2 else ()
            
            self.attempted_sources.append(source_name)
            
            try:
                start_time = time.time()
                result = source_func(*source_args)
                response_time = time.time() - start_time
                
                # Log successful API call
                api_call_logger.log_api_call(
                    source=source_name,
                    endpoint=source_func.__name__,
                    status='success',
                    response_time=response_time
                )
                
                # Log failover if this wasn't the first source
                if len(self.attempted_sources) > 1:
                    api_call_logger.log_failover(
                        primary_source=self.attempted_sources[0],
                        fallback_source=source_name,
                        field=field or 'unknown',
                        success=True
                    )
                
                logger.info(f"Successfully retrieved data from {source_name}")
                return result
                
            except Exception as e:
                last_error = e
                response_time = time.time() - start_time
                
                # Log failed API call
                api_call_logger.log_api_call(
                    source=source_name,
                    endpoint=source_func.__name__,
                    status='failure',
                    response_time=response_time,
                    error=str(e)
                )
                
                logger.warning(f"Failed to retrieve data from {source_name}: {str(e)}")
                continue
        
        # All sources failed
        error_msg = f"All API sources failed for field '{field or 'unknown'}'"
        logger.error(f"{error_msg}. Attempted sources: {self.attempted_sources}")
        
        raise APIFailoverException(
            message=error_msg,
            attempted_sources=self.attempted_sources
        )


class RateLimitHandler:
    """Handles rate limiting with request queuing."""
    
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
    
    def handle_rate_limit(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with rate limit handling and exponential backoff.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            RateLimitException: If max retries exceeded
        """
        retries = 0
        
        while retries <= self.max_retries:
            try:
                return func(*args, **kwargs)
                
            except RateLimitException as e:
                retries += 1
                
                if retries > self.max_retries:
                    logger.error(f"Max retries ({self.max_retries}) exceeded for rate limit")
                    raise
                
                # Calculate exponential backoff delay
                delay = self.base_delay * (2 ** (retries - 1))
                retry_after = e.payload.get('retry_after', delay)
                
                logger.warning(
                    f"Rate limit hit, retry {retries}/{self.max_retries} "
                    f"after {retry_after}s"
                )
                
                time.sleep(retry_after)
                continue
            
            except Exception as e:
                # Re-raise non-rate-limit exceptions
                raise


def with_api_failover(sources_key: str = 'sources'):
    """
    Decorator for automatic API failover handling.
    
    Args:
        sources_key: Key in kwargs containing list of source tuples
        
    Usage:
        @with_api_failover(sources_key='data_sources')
        def fetch_data(address, data_sources=None):
            # Function will automatically try all sources
            pass
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            sources = kwargs.pop(sources_key, None)
            
            if not sources:
                # No failover sources provided, execute normally
                return func(*args, **kwargs)
            
            handler = APIFailoverHandler()
            return handler.try_sources(sources)
        
        return wrapper
    return decorator


def with_rate_limit_handling(max_retries: int = 3, base_delay: float = 1.0):
    """
    Decorator for automatic rate limit handling.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds for exponential backoff
        
    Usage:
        @with_rate_limit_handling(max_retries=3, base_delay=1.0)
        def api_call():
            # Function will automatically retry on rate limits
            pass
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            handler = RateLimitHandler(max_retries, base_delay)
            return handler.handle_rate_limit(func, *args, **kwargs)
        
        return wrapper
    return decorator


def log_api_call(source: str):
    """
    Decorator to automatically log API calls.
    
    Args:
        source: API source name
        
    Usage:
        @log_api_call(source='MLS')
        def fetch_from_mls(address):
            pass
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                response_time = time.time() - start_time
                
                api_call_logger.log_api_call(
                    source=source,
                    endpoint=func.__name__,
                    status='success',
                    response_time=response_time
                )
                
                return result
                
            except Exception as e:
                response_time = time.time() - start_time
                
                api_call_logger.log_api_call(
                    source=source,
                    endpoint=func.__name__,
                    status='failure',
                    response_time=response_time,
                    error=str(e)
                )
                
                raise
        
        return wrapper
    return decorator

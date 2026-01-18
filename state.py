"""
Application state management - single source of truth for the application.
"""
import logging
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, Any, Optional


logger = logging.getLogger(__name__)


@dataclass
class AppState:
    """
    Central application state that acts as the single source of truth.
    Thread-safe state management for the application.
    
    This is a bare structure ready to be extended with:
    - Multiple users
    - Multiple auth tokens
    - Browser sessions
    - Configuration data
    """
    
    # Application state
    is_running: bool = False
    
    # Data storage (extend as needed)
    data: Dict[str, Any] = field(default_factory=dict)
    
    # Thread safety
    _lock: Lock = field(default_factory=Lock, repr=False)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from state."""
        with self._lock:
            return self.data.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set a value in state."""
        with self._lock:
            self.data[key] = value
            logger.debug(f"State updated: {key}")
    
    def delete(self, key: str) -> None:
        """Delete a value from state."""
        with self._lock:
            if key in self.data:
                del self.data[key]
                logger.debug(f"State deleted: {key}")
    
    def start(self) -> None:
        """Mark application as running."""
        with self._lock:
            self.is_running = True
            logger.info("Application state: RUNNING")
    
    def stop(self) -> None:
        """Mark application as stopped."""
        with self._lock:
            self.is_running = False
            logger.info("Application state: STOPPED")
    
    def cleanup(self) -> None:
        """Clean up resources."""
        with self._lock:
            self.data.clear()
            self.is_running = False
            logger.info("State cleanup completed")


# Global application state instance
_app_state: Optional[AppState] = None


def get_app_state() -> AppState:
    """
    Get the global application state instance.
    Creates it if it doesn't exist.
    """
    global _app_state
    if _app_state is None:
        _app_state = AppState()
    return _app_state


def reset_app_state() -> None:
    """
    Reset the global application state.
    Useful for testing or reinitialization.
    """
    global _app_state
    if _app_state:
        _app_state.cleanup()
    _app_state = AppState()

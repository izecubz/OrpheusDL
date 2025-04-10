from typing import Callable, Dict, List, Any
import threading
import time
import logging
from dataclasses import dataclass
from enum import Enum

# Configure logging
logger = logging.getLogger('event-manager')

class EventType(Enum):
    PROGRESS = "progress"
    MESSAGE = "message"
    STATUS = "status"
    ERROR = "error"
    COMPLETE = "complete"

@dataclass
class DownloadEvent:
    download_id: str
    event_type: EventType
    data: Dict[str, Any]
    timestamp: float = time.time()

class EventManager:
    def __init__(self):
        logger.debug("Initializing EventManager")
        self._subscribers: Dict[str, Dict[EventType, List[Callable]]] = {}
        self._event_history: Dict[str, List[DownloadEvent]] = {}
        self._lock = threading.Lock()
    
    def subscribe(self, download_id: str, event_type: EventType, callback: Callable):
        """Subscribe to events for a specific download ID and event type."""
        logger.debug(f"Subscribing to {event_type.value} events for download ID: {download_id}")
        with self._lock:
            if download_id not in self._subscribers:
                self._subscribers[download_id] = {}
            if event_type not in self._subscribers[download_id]:
                self._subscribers[download_id][event_type] = []
            self._subscribers[download_id][event_type].append(callback)
            logger.debug(f"Current subscribers for {download_id}: {len(self._subscribers[download_id][event_type])}")
    
    def unsubscribe(self, download_id: str, event_type: EventType, callback: Callable):
        """Unsubscribe from events for a specific download ID and event type."""
        logger.debug(f"Unsubscribing from {event_type.value} events for download ID: {download_id}")
        with self._lock:
            if download_id in self._subscribers and event_type in self._subscribers[download_id]:
                if callback in self._subscribers[download_id][event_type]:
                    self._subscribers[download_id][event_type].remove(callback)
                    logger.debug(f"Remaining subscribers for {download_id}: {len(self._subscribers[download_id][event_type])}")
    
    def emit(self, event: DownloadEvent):
        """Emit an event to all subscribers for the specific download ID and event type."""
        logger.debug(f"Emitting event: {event.event_type.value} for download ID: {event.download_id}")
        with self._lock:
            # Store event in history
            if event.download_id not in self._event_history:
                self._event_history[event.download_id] = []
            self._event_history[event.download_id].append(event)
            
            # Notify subscribers
            if event.download_id in self._subscribers and event.event_type in self._subscribers[event.download_id]:
                callbacks = self._subscribers[event.download_id][event.event_type]
                logger.debug(f"Notifying {len(callbacks)} subscribers for {event.download_id}")
                for callback in callbacks:
                    try:
                        callback(event)
                    except Exception as e:
                        logger.error(f"Error in event callback for {event.download_id}: {str(e)}")
    
    def get_events(self, download_id: str, event_type: EventType = None) -> List[DownloadEvent]:
        """Get all events for a specific download ID, optionally filtered by event type."""
        logger.debug(f"Getting events for download ID: {download_id}, event type: {event_type.value if event_type else 'all'}")
        with self._lock:
            if download_id not in self._event_history:
                logger.debug(f"No events found for download ID: {download_id}")
                return []
            
            events = self._event_history[download_id]
            if event_type:
                events = [e for e in events if e.event_type == event_type]
            
            logger.debug(f"Found {len(events)} events for {download_id}")
            return events
    
    def clear_events(self, download_id: str):
        """Clear all events for a specific download ID."""
        logger.debug(f"Clearing events for download ID: {download_id}")
        with self._lock:
            if download_id in self._event_history:
                del self._event_history[download_id]
            if download_id in self._subscribers:
                del self._subscribers[download_id]
            logger.debug(f"Cleared events and subscribers for {download_id}")

# Global instance
event_manager = EventManager() 
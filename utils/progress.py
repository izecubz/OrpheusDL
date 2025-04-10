from typing import Optional
import time
import logging
from .events import EventManager, EventType, DownloadEvent

# Configure logging
logger = logging.getLogger('progress-reporter')

class ProgressReporter:
    def __init__(self, download_id: str):
        logger.debug(f"Initializing ProgressReporter for download ID: {download_id}")
        self.download_id = download_id
        self.event_manager = EventManager()
        self.total_items = 0
        self.current_item = 0
        self.last_progress = 0
        self.last_update_time = time.time()
        self.update_interval = 0.5  # Minimum time between progress updates in seconds
        self.indent_number = 0
        self.completion_detected = False
    
    def set_indent_number(self, number: int):
        """Set the indent number for message formatting."""
        logger.debug(f"Setting indent number to {number} for download ID: {self.download_id}")
        self.indent_number = number
    
    def report_progress(self, current: int, total: int, message: Optional[str] = None):
        """Report progress for the current download."""
        logger.debug(f"Reporting progress for download ID {self.download_id}: {current}/{total} ({int((current/total)*100) if total > 0 else 0}%)")
        
        if total > 0:
            progress = int((current / total) * 100)
            current_time = time.time()
            
            # Only update if enough time has passed since last update
            if current_time - self.last_update_time >= self.update_interval:
                logger.debug(f"Updating progress for download ID {self.download_id}: {progress}%")
                self.last_update_time = current_time
                self.last_progress = progress
                
                # Emit progress event
                event = DownloadEvent(
                    download_id=self.download_id,
                    event_type=EventType.PROGRESS,
                    data={"current": current, "total": total, "progress": progress}
                )
                logger.debug(f"Emitting progress event: {event}")
                self.event_manager.emit(event)
                
                # If there's a message, emit it separately
                if message:
                    logger.debug(f"Reporting message with progress: {message}")
                    self.report_message(message)
            else:
                logger.debug(f"Skipping progress update due to rate limiting for download ID {self.download_id}")
    
    def report_message(self, message: str, level: int = 0):
        """Report a message for the current download."""
        # Add timestamp to message
        timestamp = time.strftime("%H:%M:%S")
        formatted_message = f"{timestamp} {message}"
        
        logger.debug(f"Reporting message for download ID {self.download_id}: {formatted_message}")
        
        # Emit message event
        event = DownloadEvent(
            download_id=self.download_id,
            event_type=EventType.MESSAGE,
            data={"message": formatted_message, "level": level}
        )
        logger.debug(f"Emitting message event: {event}")
        self.event_manager.emit(event)
    
    def report_status(self, status: str):
        """Report a status change for the current download."""
        logger.debug(f"Reporting status for download ID {self.download_id}: {status}")
        
        event = DownloadEvent(
            download_id=self.download_id,
            event_type=EventType.STATUS,
            data={"status": status}
        )
        logger.debug(f"Emitting status event: {event}")
        self.event_manager.emit(event)
    
    def report_error(self, error: str):
        """Report an error for the current download."""
        logger.error(f"Reporting error for download ID {self.download_id}: {error}")
        
        event = DownloadEvent(
            download_id=self.download_id,
            event_type=EventType.ERROR,
            data={"error": error}
        )
        logger.debug(f"Emitting error event: {event}")
        self.event_manager.emit(event)
    
    def report_complete(self):
        """Report completion of the current download."""
        if not self.completion_detected:
            logger.debug(f"Reporting completion for download ID {self.download_id}")
            self.completion_detected = True
            
            event = DownloadEvent(
                download_id=self.download_id,
                event_type=EventType.COMPLETE,
                data={"progress": 100}
            )
            logger.debug(f"Emitting complete event: {event}")
            self.event_manager.emit(event)
    
    def get_progress(self) -> int:
        """Get the current progress percentage."""
        logger.debug(f"Getting progress for download ID {self.download_id}: {self.last_progress}%")
        return self.last_progress 
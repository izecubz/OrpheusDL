from flask import Flask, render_template, request, jsonify, send_file, flash, redirect, url_for, session
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from wtforms import StringField, SelectField, BooleanField, SubmitField
from wtforms.validators import DataRequired, URL
import os
import json
import sys
import traceback
import threading
import time
from queue import Queue
import re
from utils.events import event_manager, EventType
from utils.progress import ProgressReporter
import logging

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('orpheus-web')

# Add parent directory to Python path to allow importing modules
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Try to import Orpheus modules
try:
    from orpheus.core import Orpheus
    from orpheus.music_downloader import beauty_format_seconds
    from utils.models import MediaIdentification, DownloadTypeEnum, ModuleModes
    from orpheus.core import orpheus_core_download
except ImportError as e:
    print(f"Error importing Orpheus modules: {e}")
    print(f"Python path: {sys.path}")
    print(f"Current directory: {os.getcwd()}")
    print("Traceback:")
    traceback.print_exc()

app = Flask(__name__)
# load WEB_SECRET from environment variable
app.config['SECRET_KEY'] = os.environ.get('WEB_SECRET', 'orpheusdl-web-secret-key-2025')
csrf = CSRFProtect(app)  # Initialize CSRF protection

# Global variables for tracking download progress
download_progress = {}
download_status = {}
download_messages = {}
download_queue = []
active_downloads = {}
MAX_CONCURRENT_DOWNLOADS = 1  # Process one download at a time

# Set default download path
DEFAULT_DOWNLOAD_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'downloads')

# Initialize Orpheus
try:
    # Ensure modules directory exists
    modules_dir = os.path.join(parent_dir, 'modules')
    os.makedirs(modules_dir, exist_ok=True)
    
    # Check if modules directory is empty
    if not os.listdir(modules_dir):
        print("Modules directory is empty. Please install at least one module.")
        raise Exception("Modules directory is empty. Please install at least one module.")
    
    # Initialize Orpheus with proper module loading
    orpheus_instance = Orpheus()
    
    # Verify modules are loaded
    if not orpheus_instance.module_list:
        print("No modules are installed. Please install at least one module.")
        raise Exception("No modules are installed. Please install at least one module.")
    
    # Ensure settings are properly initialized
    if not hasattr(orpheus_instance, 'settings') or not orpheus_instance.settings:
        print("Settings not properly initialized, creating default settings")
        orpheus_instance.settings = {
            'global': {
                'general': {
                    'download_path': DEFAULT_DOWNLOAD_PATH,
                    'download_quality': 'hifi',
                    'search_limit': 10
                },
                'artist_downloading': {
                    'return_credited_albums': True,
                    'separate_tracks_skip_downloaded': True
                },
                'formatting': {
                    'album_format': '{name}{explicit}',
                    'track_filename_format': '{track_number}. {name}'
                },
                'advanced': {
                    'proprietary_codecs': False,
                    'spatial_codecs': True,
                    'debug_mode': False,
                    'disable_subscription_checks': False
                }
            },
            'modules': {}
        }
    
    # Ensure module_controls is properly initialized
    if not hasattr(orpheus_instance, 'module_controls'):
        print("module_controls not properly initialized, creating default module_controls")
        orpheus_instance.module_controls = {
            'module_list': orpheus_instance.module_list,
            'module_settings': orpheus_instance.module_settings,
            'loaded_modules': {},
            'module_loader': orpheus_instance.load_module
        }
        
except Exception as e:
    print(f"Error initializing Orpheus: {e}")
    traceback.print_exc()
    
    # Create a mock Orpheus instance for the web interface
    class MockOrpheus:
        def __init__(self):
            self.module_list = []
            self.module_settings = {}
            self.module_netloc_constants = {}
            self.settings = {
                'global': {
                    'general': {
                        'download_path': DEFAULT_DOWNLOAD_PATH,
                        'download_quality': 'hifi',
                        'search_limit': 10
                    },
                    'formatting': {
                        'album_format': '{name}{explicit}',
                        'track_filename_format': '{track_number}. {name}'
                    },
                    'advanced': {
                        'proprietary_codecs': False,
                        'spatial_codecs': True,
                        'debug_mode': False,
                        'disable_subscription_checks': False
                    }
                },
                'modules': {}
            }
            self.module_controls = {
                'module_list': self.module_list,
                'module_settings': self.module_settings,
                'loaded_modules': {},
                'module_loader': self.load_module
            }
        
        def load_module(self, module_name):
            raise Exception("No modules are installed. Please install at least one module.")
    
    orpheus_instance = MockOrpheus()

class DownloadForm(FlaskForm):
    url = StringField('URL', validators=[DataRequired()])
    output_path = StringField('Output Path', default='./downloads/')
    lyrics_module = SelectField('Lyrics Module', choices=[('default', 'Default')])
    covers_module = SelectField('Covers Module', choices=[('default', 'Default')])
    credits_module = SelectField('Credits Module', choices=[('default', 'Default')])

class SearchForm(FlaskForm):
    module = SelectField('Module', validators=[DataRequired()])
    query_type = SelectField('Type', choices=[
        ('track', 'Track'),
        ('album', 'Album'), 
        ('playlist', 'Playlist'),
        ('artist', 'Artist')
    ], validators=[DataRequired()])
    query = StringField('Query', validators=[DataRequired()])
    submit = SubmitField('Search')

# Update form choices if Orpheus is initialized
if orpheus_instance and hasattr(orpheus_instance, 'module_list') and orpheus_instance.module_list:
    DownloadForm.lyrics_module.choices = [('default', 'Default')] + [(m, m) for m in orpheus_instance.module_list]
    DownloadForm.covers_module.choices = [('default', 'Default')] + [(m, m) for m in orpheus_instance.module_list]
    DownloadForm.credits_module.choices = [('default', 'Default')] + [(m, m) for m in orpheus_instance.module_list]
    SearchForm.module.choices = [(m, m) for m in orpheus_instance.module_list]

# Custom Oprinter class to capture progress
class WebOprinter:
    def __init__(self, download_id):
        self.download_id = download_id
        self.job_completed = False
        self.total_items = 0
        self.current_item = 0
        self.last_progress = 0
        self.last_update_time = time.time()
        self.update_interval = 0.5  # Minimum time between progress updates in seconds
        self.indent_number = 0  # Add indent_number attribute
        self.messages = []  # Store messages for this download
        self.completion_detected = False  # Flag to track if completion has been detected

    def set_indent_number(self, number):
        """Set the indent number for message formatting."""
        self.indent_number = number

    def oprint(self, message, level=0, drop_level=None):
        """Print a message with optional indentation level and drop level.
        
        Args:
            message (str): The message to print
            level (int): The indentation level
            drop_level (int, optional): The level to drop to after printing
        """
        # Add timestamp to message
        timestamp = time.strftime("%H:%M:%S")
        formatted_message = f"{timestamp} {message}"
        
        # Add message to the download's message list
        if self.download_id not in download_messages:
            download_messages[self.download_id] = []
        download_messages[self.download_id].append(formatted_message)
        
        # Also store in local messages list
        self.messages.append(formatted_message)
        
        # Print to console for debugging
        print(formatted_message)

        # Extract progress information from the message
        progress_info = self._extract_progress_info(message)
        if progress_info:
            self._update_progress(*progress_info)
            
        # Check for completion messages
        if ("Download completed" in message or "All downloads completed" in message) and not self.completion_detected:
            self.completion_detected = True
            self.job_completed = True
            download_status[self.download_id] = "completed"
            download_progress[self.download_id] = 100
            print(f"Download {self.download_id} marked as completed")

    def _extract_progress_info(self, message):
        # Check for job completion messages
        if "All downloads completed successfully" in message and not self.completion_detected:
            self.completion_detected = True
            self.job_completed = True
            return (self.total_items, self.total_items, True)

        # Check for total items information
        total_match = re.search(r"Total items to download: (\d+)", message)
        if total_match:
            self.total_items = int(total_match.group(1))
            return None

        # Check for various progress patterns
        patterns = [
            r"Downloading (\d+)/(\d+)",  # General progress
            r"Track (\d+)/(\d+)",        # Track progress
            r"Album (\d+)/(\d+)",        # Album progress
            r"Playlist (\d+)/(\d+)"      # Playlist progress
        ]

        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                current = int(match.group(1))
                total = int(match.group(2))
                return (current, total, False)

        return None

    def _update_progress(self, current, total, is_completed):
        # Update current item and total
        self.current_item = current
        self.total_items = max(self.total_items, total)

        # Calculate progress percentage
        if self.total_items > 0:
            progress = int((self.current_item / self.total_items) * 100)
        else:
            progress = 0

        # Only update if enough time has passed since the last update
        current_time = time.time()
        if (current_time - self.last_update_time >= self.update_interval or 
            progress == 100 or 
            progress - self.last_progress >= 5):
            
            # Update global tracking
            download_progress[self.download_id] = progress
            if is_completed or progress == 100:
                self.completion_detected = True
                self.job_completed = True
                download_status[self.download_id] = "completed"
                print(f"Download {self.download_id} marked as completed in _update_progress")
            else:
                download_status[self.download_id] = "running"

            self.last_progress = progress
            self.last_update_time = current_time

# Function to run download in a separate thread
def run_download(download_id, orpheus_instance, media_to_download, tpm, separate_download_module, output_path):
    logger.debug(f"Starting download process for ID: {download_id}")
    logger.debug(f"Media to download: {media_to_download}")
    logger.debug(f"Third-party modules: {tpm}")
    logger.debug(f"Separate download module: {separate_download_module}")
    logger.debug(f"Output path: {output_path}")
    
    try:
        # Set up progress reporter
        logger.debug(f"Setting up progress reporter for download ID: {download_id}")
        progress_reporter = orpheus_instance.set_progress_reporter(download_id)
        
        # Subscribe to events
        logger.debug(f"Subscribing to events for download ID: {download_id}")
        
        def handle_event(event):
            logger.debug(f"Event received for download ID {download_id}: {event.event_type} - {event.data}")
            if event.event_type == EventType.PROGRESS:
                download_progress[download_id] = event.data["progress"]
                logger.debug(f"Progress updated for download ID {download_id}: {event.data['progress']}%")
            elif event.event_type == EventType.MESSAGE:
                if download_id not in download_messages:
                    download_messages[download_id] = []
                download_messages[download_id].append(event.data["message"])
                logger.debug(f"Message for download ID {download_id}: {event.data['message']}")
            elif event.event_type == EventType.STATUS:
                download_status[download_id] = event.data["status"]
                logger.debug(f"Status updated for download ID {download_id}: {event.data['status']}")
            elif event.event_type == EventType.ERROR:
                download_status[download_id] = "error"
                if download_id not in download_messages:
                    download_messages[download_id] = []
                download_messages[download_id].append(f"Error: {event.data['error']}")
                logger.error(f"Error for download ID {download_id}: {event.data['error']}")
            elif event.event_type == EventType.COMPLETE:
                download_status[download_id] = "completed"
                download_progress[download_id] = 100
                logger.debug(f"Download ID {download_id} marked as completed")
        
        # Subscribe to all event types
        for event_type in EventType:
            event_manager.subscribe(download_id, event_type, handle_event)
        
        # Start the download
        logger.debug(f"Starting download for ID: {download_id}")
        orpheus_instance.report_status("starting")
        orpheus_core_download(orpheus_instance, media_to_download, tpm, separate_download_module, output_path)
        
        # Clean up
        logger.debug(f"Cleaning up for download ID: {download_id}")
        for event_type in EventType:
            event_manager.unsubscribe(download_id, event_type, handle_event)
        event_manager.clear_events(download_id)
        
    except Exception as e:
        logger.error(f"Exception in run_download for ID {download_id}: {str(e)}", exc_info=True)
        orpheus_instance.report_error(str(e))
        print(f"Download error: {str(e)}")
        traceback.print_exc()
    finally:
        # Remove from active downloads
        if download_id in active_downloads:
            logger.debug(f"Removing download ID {download_id} from active downloads")
            del active_downloads[download_id]
        
        # Process next item in queue
        logger.debug("Processing next item in queue")
        process_queue()

# Function to process the download queue
def process_queue():
    """Process the download queue and start new downloads if possible."""
    logger.debug(f"Processing queue. Active downloads: {len(active_downloads)}, Queue length: {len(download_queue)}")
    
    # Check if we can start a new download
    if len(active_downloads) < MAX_CONCURRENT_DOWNLOADS and download_queue:
        # Get the next download from the queue
        next_download = download_queue.pop(0)
        download_id = next_download['download_id']
        
        logger.debug(f"Starting next download from queue. ID: {download_id}")
        
        # Start the download
        active_downloads[download_id] = next_download
        
        # Update status to indicate it's starting
        download_status[download_id] = "starting"
        
        # Start the download in a new thread
        thread = threading.Thread(
            target=run_download,
            args=(
                download_id, 
                next_download['orpheus_instance'], 
                next_download['media_to_download'], 
                next_download['tpm'], 
                next_download['separate_download_module'], 
                next_download['output_path']
            )
        )
        thread.daemon = True
        thread.start()
        
        # Log that we're starting a new download
        logger.debug(f"Started download thread for ID: {download_id}")
    else:
        logger.debug("No new downloads started. Queue empty or max concurrent downloads reached.")

@app.route('/')
def index():
    if not orpheus_instance or not hasattr(orpheus_instance, 'module_list') or not orpheus_instance.module_list:
        flash('No modules are installed. Please install at least one module to use OrpheusDL.', 'warning')
        return render_template('no_modules.html')
    
    return render_template('index.html', 
                         modules=orpheus_instance.module_list,
                         orpheus=orpheus_instance,
                         form=DownloadForm())

@app.route('/search', methods=['GET', 'POST'])
def search():
    if not orpheus_instance or not hasattr(orpheus_instance, 'module_list') or not orpheus_instance.module_list:
        flash('No modules are installed. Please install at least one module to use OrpheusDL.', 'warning')
        return render_template('no_modules.html')
    
    form = SearchForm()
    form.module.choices = [(module, module) for module in orpheus_instance.module_list]
    
    if form.validate_on_submit():
        try:
            module = orpheus_instance.load_module(form.module.data)
            # Convert query type to lowercase before passing to module
            query_type = DownloadTypeEnum[form.query_type.data.lower()]
            items = module.search(query_type, form.query.data, limit=orpheus_instance.settings['global']['general']['search_limit'])
            
            results = []
            for item in items:
                result = {
                    'name': item.name,
                    'artists': item.artists,
                    'year': item.year,
                    'explicit': item.explicit,
                    'duration': beauty_format_seconds(item.duration) if item.duration else None,
                    'additional': item.additional
                }
                results.append(result)
            
            return jsonify(results)
        except Exception as e:
            return jsonify({'error': str(e)}), 400
            
    return render_template('search.html', form=form)

@app.route('/download', methods=['POST'])
def download():
    logger.debug("Download endpoint called")
    
    if not orpheus_instance or not hasattr(orpheus_instance, 'module_list') or not orpheus_instance.module_list:
        logger.error("No modules are installed")
        return jsonify({'error': 'No modules are installed. Please install at least one module to use OrpheusDL.'}), 500
    
    form = DownloadForm()
    
    # Debug information
    logger.debug(f"Form data: {request.form}")
    logger.debug(f"Form validation: {form.validate()}")
    if not form.validate():
        logger.debug(f"Form errors: {form.errors}")
    
    if form.validate_on_submit():
        try:
            url = form.url.data
            output_path = form.output_path.data or orpheus_instance.settings['global']['general']['download_path']
            
            logger.debug(f"Processing download request for URL: {url}")
            logger.debug(f"Output path: {output_path}")
            
            # Prepare third-party modules
            tpm = {}
            if form.lyrics_module.data and form.lyrics_module.data != 'default':
                tpm[ModuleModes.lyrics] = form.lyrics_module.data
            if form.covers_module.data and form.covers_module.data != 'default':
                tpm[ModuleModes.covers] = form.covers_module.data
            if form.credits_module.data and form.credits_module.data != 'default':
                tpm[ModuleModes.credits] = form.credits_module.data
            
            logger.debug(f"Third-party modules: {tpm}")
            
            # Parse URL and prepare media_to_download
            from urllib.parse import urlparse
            
            url_parsed = urlparse(url)
            components = url_parsed.path.split('/')
            
            logger.debug(f"Parsed URL: {url_parsed}")
            logger.debug(f"URL components: {components}")
            
            service_name = None
            for pattern in orpheus_instance.module_netloc_constants:
                if re.findall(pattern, url_parsed.netloc):
                    service_name = orpheus_instance.module_netloc_constants[pattern]
                    break
                    
            logger.debug(f"Service name: {service_name}")
            
            if not service_name:
                logger.error(f"URL location '{url_parsed.netloc}' is not found in modules!")
                return jsonify({'error': f'URL location "{url_parsed.netloc}" is not found in modules!'}), 400
                
            media_to_download = {service_name: []}
            
            # Extract media ID from URL
            media_id = None
            media_type = DownloadTypeEnum.track  # Default to track
            
            # Try to determine media type from URL
            for i, component in enumerate(components):
                if component and component != '':
                    # Check if this component is a media type indicator
                    if component.lower() in ['track', 'album', 'playlist', 'artist']:
                        media_type_str = component.lower()
                        if media_type_str == 'track':
                            media_type = DownloadTypeEnum.track
                        elif media_type_str == 'album':
                            media_type = DownloadTypeEnum.album
                        elif media_type_str == 'playlist':
                            media_type = DownloadTypeEnum.playlist
                        elif media_type_str == 'artist':
                            media_type = DownloadTypeEnum.artist
                        
                        # The next component should be the media ID
                        if i + 1 < len(components) and components[i + 1]:
                            media_id = components[i + 1]
                            break
                    else:
                        # If we find a component that's not a media type indicator, assume it's the media ID
                        media_id = component
                        break
            
            logger.debug(f"Media ID: {media_id}")
            logger.debug(f"Media type: {media_type}")
            
            if not media_id:
                logger.error("Could not extract media ID from URL")
                return jsonify({'error': 'Could not extract media ID from URL'}), 400
            
            # Add media to download list
            media_to_download[service_name].append(MediaIdentification(
                media_type=media_type,
                media_id=media_id
            ))
            
            # Create output directory if it doesn't exist
            os.makedirs(output_path, exist_ok=True)
            
            # Generate a unique download ID
            import uuid
            download_id = str(uuid.uuid4())
            
            logger.debug(f"Generated download ID: {download_id}")
            
            # Initialize download tracking
            download_progress[download_id] = 0
            download_status[download_id] = "queued"
            download_messages[download_id] = []
            
            # Add to queue
            download_queue.append({
                'download_id': download_id,
                'orpheus_instance': orpheus_instance,
                'media_to_download': media_to_download,
                'tpm': tpm,
                'separate_download_module': 'default' if media_type != DownloadTypeEnum.playlist else None,
                'output_path': output_path,
                'url': url,
                'media_type': media_type.name,
                'timestamp': time.time()
            })
            
            logger.debug(f"Added download to queue. Queue length: {len(download_queue)}")
            
            # Process queue
            process_queue()
            
            logger.debug(f"Download queued successfully. ID: {download_id}")
            
            return jsonify({
                'success': True, 
                'message': 'Download queued', 
                'download_id': download_id,
                'queue_position': len(download_queue)
            })
                
        except Exception as e:
            logger.error(f"Error in download endpoint: {str(e)}", exc_info=True)
            return jsonify({'error': str(e)}), 500
    
    logger.error("Invalid form data")
    return jsonify({'error': 'Invalid form data'}), 400

@app.route('/progress/<download_id>')
def get_progress(download_id):
    """Get the current progress of a download."""
    logger.debug(f"Progress request for download ID: {download_id}")
    
    try:
        # Get all events for this download
        events = event_manager.get_events(download_id)
        logger.debug(f"Found {len(events)} events for download ID: {download_id}")
        
        # Get the latest progress event
        progress_events = [e for e in events if e.event_type == EventType.PROGRESS]
        progress = progress_events[-1].data["progress"] if progress_events else 0
        
        # Get all messages
        messages = [e.data["message"] for e in events if e.event_type == EventType.MESSAGE]
        
        # Get the latest status
        status_events = [e for e in events if e.event_type == EventType.STATUS]
        status = status_events[-1].data["status"] if status_events else "unknown"
        
        logger.debug(f"Progress for download ID {download_id}: {progress}%, Status: {status}, Messages: {len(messages)}")
        
        return jsonify({
            'status': status,
            'progress': progress,
            'messages': messages
        })
    except Exception as e:
        logger.error(f"Error getting progress for download ID {download_id}: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/queue')
def queue():
    return render_template('queue.html')

@app.route('/api/queue')
def get_queue():
    """Get the current status of the download queue."""
    try:
        # Format active downloads
        active = []
        for download_id, download in active_downloads.items():
            active.append({
                'download_id': download_id,
                'filename': download.get('url', 'Unknown'),
                'size': download.get('size', 0),
                'progress': download_progress.get(download_id, 0),
                'status': download_status.get(download_id, 'unknown'),
                'timestamp': download.get('timestamp', time.time())
            })
        
        # Format queued downloads
        queued = []
        for i, download in enumerate(download_queue):
            queued.append({
                'download_id': download.get('download_id', f'queued_{i}'),
                'filename': download.get('url', 'Unknown'),
                'size': download.get('size', 0),
                'progress': 0,
                'status': 'queued',
                'timestamp': download.get('timestamp', time.time()),
                'queue_position': i + 1
            })
        
        # Get completed downloads from the last 10 minutes
        completed = []
        current_time = time.time()
        
        # First, check for downloads that are marked as completed in download_status
        for download_id, status in list(download_status.items()):
            if status == 'completed':
                # Check if this is a recently completed download
                if download_id in active_downloads:
                    download = active_downloads[download_id]
                    # Only include downloads completed in the last 10 minutes
                    if current_time - download.get('timestamp', current_time) < 600:  # 10 minutes
                        completed.append({
                            'download_id': download_id,
                            'filename': download.get('url', 'Unknown'),
                            'size': download.get('size', 0),
                            'progress': 100,
                            'status': 'completed',
                            'timestamp': download.get('timestamp', current_time)
                        })
        
        # Also check for downloads that have 100% progress but might not be marked as completed
        for download_id, progress in list(download_progress.items()):
            if progress == 100 and download_id in active_downloads and download_id not in [c['download_id'] for c in completed]:
                download = active_downloads[download_id]
                # Only include downloads completed in the last 10 minutes
                if current_time - download.get('timestamp', current_time) < 600:  # 10 minutes
                    completed.append({
                        'download_id': download_id,
                        'filename': download.get('url', 'Unknown'),
                        'size': download.get('size', 0),
                        'progress': 100,
                        'status': 'completed',
                        'timestamp': download.get('timestamp', current_time)
                    })
        
        # Log queue status for debugging
        print(f"Queue status: {len(active)} active, {len(queued)} queued, {len(completed)} completed")
        
        return jsonify({
            'active': active,
            'queued': queued,
            'completed': completed
        })
    except Exception as e:
        app.logger.error(f"Error in get_queue: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/queue/<download_id>/cancel', methods=['POST'])
def cancel_download(download_id):
    try:
        # Check if download is active
        if download_id in active_downloads:
            # Mark as cancelled
            download_status[download_id] = 'cancelled'
            # Remove from active downloads
            del active_downloads[download_id]
            return jsonify({'status': 'success'})
        
        # Check if download is in queue
        for i, download in enumerate(download_queue):
            if download.get('download_id') == download_id:
                # Remove from queue
                download_queue.pop(i)
                return jsonify({'status': 'success'})
        
        return jsonify({'error': 'Download ID not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/settings')
def settings():
    if not orpheus_instance or not hasattr(orpheus_instance, 'module_list') or not orpheus_instance.module_list:
        flash('No modules are installed. Please install at least one module to use OrpheusDL.', 'warning')
        return render_template('no_modules.html')
    
    # Ensure settings has all required sections
    if 'global' not in orpheus_instance.settings:
        orpheus_instance.settings['global'] = {}
    
    if 'general' not in orpheus_instance.settings['global']:
        orpheus_instance.settings['global']['general'] = {
            'download_path': DEFAULT_DOWNLOAD_PATH,
            'download_quality': 'hifi',
            'search_limit': 10
        }
    
    if 'formatting' not in orpheus_instance.settings['global']:
        orpheus_instance.settings['global']['formatting'] = {
            'album_format': '{name}{explicit}',
            'track_filename_format': '{track_number}. {name}'
        }
    
    if 'advanced' not in orpheus_instance.settings['global']:
        orpheus_instance.settings['global']['advanced'] = {
            'proprietary_codecs': False,
            'spatial_codecs': True,
            'debug_mode': False,
            'disable_subscription_checks': False
        }
    
    if 'modules' not in orpheus_instance.settings:
        orpheus_instance.settings['modules'] = {}
    
    # Save the updated settings
    with open(orpheus_instance.settings_location, 'w') as f:
        json.dump(orpheus_instance.settings, f, indent=4)
    
    return render_template('settings.html', 
                         settings=orpheus_instance.settings,
                         modules=orpheus_instance.module_list)

@app.route('/error')
def error():
    return render_template('error.html', error="An error occurred")

@app.route('/no_modules')
def no_modules():
    return render_template('no_modules.html')

@app.route('/api/settings', methods=['POST'])
def update_settings():
    try:
        if not orpheus_instance:
            return jsonify({'success': False, 'error': 'Orpheus instance not initialized'}), 500

        new_settings = request.get_json()
        
        # Update the settings in the Orpheus instance
        # We need to do a deep merge instead of a simple update
        def deep_merge(d1, d2):
            for k, v in d2.items():
                if k in d1 and isinstance(d1[k], dict) and isinstance(v, dict):
                    deep_merge(d1[k], v)
                else:
                    d1[k] = v
        
        deep_merge(orpheus_instance.settings, new_settings)
        
        # Save settings to file
        with open(orpheus_instance.settings_location, 'w') as f:
            json.dump(orpheus_instance.settings, f, indent=4)
        
        return jsonify({'success': True})
    except Exception as e:
        app.logger.error(f"Error updating settings: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/restart', methods=['POST'])
def restart_module():
    try:
        if not orpheus_instance:
            return jsonify({'success': False, 'error': 'Orpheus instance not initialized'}), 500

        # Reload all modules
        for module in orpheus_instance.module_list:
            try:
                if module in orpheus_instance.loaded_modules:
                    del orpheus_instance.loaded_modules[module]
                orpheus_instance.load_module(module)
            except Exception as e:
                app.logger.error(f"Error reloading module {module}: {str(e)}")
                # Continue with other modules even if one fails
                continue

        return jsonify({'success': True})
    except Exception as e:
        app.logger.error(f"Error in restart_module: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health')
def health_check():
    """Health check endpoint for Docker/container orchestration."""
    if not orpheus_instance:
        return jsonify({'status': 'error', 'message': 'Orpheus instance not initialized'}), 500
    
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    app.run(debug=True) 
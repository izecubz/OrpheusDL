from flask import Flask, render_template, request, jsonify, send_file, flash, redirect, url_for, session
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, BooleanField
from wtforms.validators import DataRequired, URL
import os
import json
import sys
import traceback
import threading
import time
from queue import Queue

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
app.config['SECRET_KEY'] = os.urandom(24)

# Global variables for tracking download progress
download_progress = {}
download_status = {}
download_messages = {}

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
                    'download_path': './downloads/',
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
                        'download_path': './downloads/',
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
    url = StringField('URL', validators=[DataRequired(), URL()])
    output_path = StringField('Output Path', default='./downloads/')
    lyrics_module = SelectField('Lyrics Module', choices=[('default', 'Default')])
    covers_module = SelectField('Covers Module', choices=[('default', 'Default')])
    credits_module = SelectField('Credits Module', choices=[('default', 'Default')])

class SearchForm(FlaskForm):
    module = SelectField('Module', choices=[])
    query_type = SelectField('Type', choices=[
        ('track', 'Track'),
        ('album', 'Album'),
        ('playlist', 'Playlist'),
        ('artist', 'Artist')
    ])
    query = StringField('Query', validators=[DataRequired()])

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
        self.messages = []
        self.indent_number = 0
        
    def oprint(self, message, indent_level=0, drop_level=None):
        timestamp = time.strftime("%H:%M:%S")
        indent = "  " * indent_level
        formatted_message = f"{timestamp} {indent}{message}"
        self.messages.append(formatted_message)
        download_messages[self.download_id] = self.messages
        print(formatted_message)  # Also print to console for debugging
        
    def set_indent_number(self, number):
        self.indent_number = number

# Function to run download in a separate thread
def run_download(download_id, orpheus_instance, media_to_download, tpm, separate_download_module, output_path):
    try:
        # Create a custom Oprinter for this download
        oprinter = WebOprinter(download_id)
        
        # Override the global oprinter for this download
        import orpheus.core
        original_oprinter = orpheus.core.oprinter
        orpheus.core.oprinter = oprinter
        
        # Update progress status
        download_status[download_id] = "running"
        download_progress[download_id] = 0
        
        # Ensure settings are properly initialized
        if not hasattr(orpheus_instance, 'settings') or not orpheus_instance.settings:
            print("Settings not properly initialized in download thread, creating default settings")
            orpheus_instance.settings = {
                'global': {
                    'general': {
                        'download_path': './downloads/',
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
            print("module_controls not properly initialized in download thread, creating default module_controls")
            orpheus_instance.module_controls = {
                'module_list': orpheus_instance.module_list,
                'module_settings': orpheus_instance.module_settings,
                'loaded_modules': {},
                'module_loader': orpheus_instance.load_module
            }
            
        # Initialize third_party_modules with all module modes
        if not hasattr(orpheus_instance, 'third_party_modules'):
            orpheus_instance.third_party_modules = {}
            
        # Ensure all module modes are initialized with None
        for mode in ModuleModes:
            orpheus_instance.third_party_modules[mode] = None
                
        # Update with provided third-party modules
        if tpm:
            for mode, module_name in tpm.items():
                if isinstance(mode, ModuleModes):
                    orpheus_instance.third_party_modules[mode] = module_name
        
        # Create a copy of the third_party_modules dictionary to pass to the Downloader
        third_party_modules_copy = {}
        for mode in ModuleModes:
            third_party_modules_copy[mode] = orpheus_instance.third_party_modules.get(mode, None)
        
        # Run the download with the copied third_party_modules
        orpheus_core_download(orpheus_instance, media_to_download, third_party_modules_copy, separate_download_module, output_path)
        
        # Update progress status
        download_status[download_id] = "completed"
        download_progress[download_id] = 100
        
        # Restore the original oprinter
        orpheus.core.oprinter = original_oprinter
        
    except Exception as e:
        # Update progress status with error
        download_status[download_id] = "error"
        download_messages[download_id].append(f"Error: {str(e)}")
        print(f"Download error: {str(e)}")
        traceback.print_exc()

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
    if form.validate_on_submit():
        try:
            module = orpheus_instance.load_module(form.module.data)
            items = module.search(form.query_type.data, form.query.data, 
                                limit=orpheus_instance.settings['global']['general']['search_limit'])
            
            results = []
            for item in items:
                result = {
                    'name': item.name,
                    'artists': item.artists if isinstance(item.artists, list) else [item.artists],
                    'duration': beauty_format_seconds(item.duration) if item.duration else None,
                    'year': item.year,
                    'explicit': item.explicit,
                    'additional': item.additional,
                    'result_id': item.result_id,
                    'extra_kwargs': item.extra_kwargs
                }
                results.append(result)
            
            return jsonify(results)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    return render_template('search.html', form=form)

@app.route('/download', methods=['POST'])
def download():
    if not orpheus_instance or not hasattr(orpheus_instance, 'module_list') or not orpheus_instance.module_list:
        return jsonify({'error': 'No modules are installed. Please install at least one module to use OrpheusDL.'}), 500
    
    form = DownloadForm()
    if form.validate_on_submit():
        try:
            url = form.url.data
            output_path = form.output_path.data or orpheus_instance.settings['global']['general']['download_path']
            
            # Prepare third-party modules
            tpm = {}
            if form.lyrics_module.data and form.lyrics_module.data != 'default':
                tpm[ModuleModes.lyrics] = form.lyrics_module.data
            if form.covers_module.data and form.covers_module.data != 'default':
                tpm[ModuleModes.covers] = form.covers_module.data
            if form.credits_module.data and form.credits_module.data != 'default':
                tpm[ModuleModes.credits] = form.credits_module.data
            
            # Parse URL and prepare media_to_download
            from urllib.parse import urlparse
            import re
            
            url_parsed = urlparse(url)
            components = url_parsed.path.split('/')
            
            service_name = None
            for pattern in orpheus_instance.module_netloc_constants:
                if re.findall(pattern, url_parsed.netloc):
                    service_name = orpheus_instance.module_netloc_constants[pattern]
                    break
                    
            if not service_name:
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
            
            if not media_id:
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
            
            # Initialize download tracking
            download_progress[download_id] = 0
            download_status[download_id] = "starting"
            download_messages[download_id] = []
            
            # Start download in a separate thread
            if media_type == DownloadTypeEnum.playlist:
                orpheus_instance.settings['global']['artist_downloading']['separate_tracks_skip_downloaded'] = True
                separate_download_module = None
            else:
                orpheus_instance.settings['global']['artist_downloading']['separate_tracks_skip_downloaded'] = False
                separate_download_module = 'default'
                
            thread = threading.Thread(
                target=run_download,
                args=(download_id, orpheus_instance, media_to_download, tpm, separate_download_module, output_path)
            )
            thread.daemon = True
            thread.start()
            
            return jsonify({
                'success': True, 
                'message': 'Download started', 
                'download_id': download_id
            })
                
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': 'Invalid form data'}), 400

@app.route('/progress/<download_id>')
def get_progress(download_id):
    if download_id not in download_status:
        return jsonify({'error': 'Download ID not found'}), 404
        
    return jsonify({
        'status': download_status[download_id],
        'progress': download_progress[download_id],
        'messages': download_messages.get(download_id, [])
    })

@app.route('/settings')
def settings():
    if not orpheus_instance or not hasattr(orpheus_instance, 'module_list') or not orpheus_instance.module_list:
        flash('No modules are installed. Please install at least one module to use OrpheusDL.', 'warning')
        return render_template('no_modules.html')
    
    return render_template('settings.html', 
                         settings=orpheus_instance.settings,
                         modules=orpheus_instance.module_list)

@app.route('/error')
def error():
    return render_template('error.html', error="An error occurred")

@app.route('/no_modules')
def no_modules():
    return render_template('no_modules.html')

if __name__ == '__main__':
    app.run(debug=True) 
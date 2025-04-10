import importlib, json, logging, os, pickle, requests, urllib3, base64, shutil
from datetime import datetime

from orpheus.music_downloader import Downloader
from utils.models import *
from utils.utils import *
from utils.exceptions import *
from utils.progress import ProgressReporter
from utils.events import EventType, DownloadEvent, event_manager

os.environ['CURL_CA_BUNDLE'] = ''  # Hack to disable SSL errors for requests module for easier debugging
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # Make SSL warnings hidden

# try:
#     time_request = requests.get('https://github.com') # to be replaced with something useful, like an Orpheus updates json
# except:
#     print('Could not reach the internet, quitting')
#     exit()

# timestamp_correction_term = int(datetime.strptime(time_request.headers['Date'], '%a, %d %b %Y %H:%M:%S GMT').timestamp() - datetime.utcnow().timestamp())
# if abs(timestamp_correction_term) > 60*60*24:
#     print('System time is incorrect, using online time to correct it for subscription expiry checks')

timestamp_correction_term = 0
# Use the same Oprinter instance wherever it's needed
oprinter = Oprinter()


def true_current_utc_timestamp():
    return int(datetime.utcnow().timestamp()) + timestamp_correction_term


class Orpheus:
    def __init__(self, private_mode=False):
        self.extensions, self.extension_list, self.module_list, self.module_settings, self.module_netloc_constants, self.loaded_modules = {}, set(), set(), {}, {}, {}

        self.default_global_settings = {
            "general": {
                "download_path": "./downloads/",
                "download_quality": "hifi",
                "search_limit": 10
            },
            "artist_downloading":{
                "return_credited_albums": True,
                "separate_tracks_skip_downloaded": True
            },
            "formatting": {
                "album_format": "{name}{explicit}",
                "playlist_format": "{name}{explicit}",
                "track_filename_format": "{track_number}. {name}",
                "single_full_path_format": "{name}",
                "enable_zfill": True,
                "force_album_format": False
            },
            "codecs": {
                "proprietary_codecs": False,
                "spatial_codecs": True
            },
            "module_defaults": {
                "lyrics": "default",
                "covers": "default",
                "credits": "default"
            },
            "lyrics": {
                "embed_lyrics": True,
                "embed_synced_lyrics": False,
                "save_synced_lyrics": True
            },
            "covers": {
                "embed_cover": True,
                "main_compression": "high",
                "main_resolution": 1400,
                "save_external": False,
                "external_format": 'png',
                "external_compression": "low",
                "external_resolution": 3000,
                "save_animated_cover": True
            },
            "playlist": {
                "save_m3u": True,
                "paths_m3u": "absolute",
                "extended_m3u": True
            },
            "advanced": {
                "advanced_login_system": False,
                "codec_conversions": {
                    "alac": "flac",
                    "wav": "flac"
                },
                "conversion_flags": {
                    "flac": {
                        "compression_level": "5"
                    }
                },
                "conversion_keep_original": False,
                "cover_variance_threshold": 8,
                "debug_mode": False,
                "disable_subscription_checks": False,
                "enable_undesirable_conversions": False,
                "ignore_existing_files": False,
                "ignore_different_artists": True
            }
        }

        self.data_folder_base = 'config'
        self.settings_location = os.path.join(self.data_folder_base, 'settings.json')
        self.session_storage_location = os.path.join(self.data_folder_base, 'loginstorage.bin')

        os.makedirs('config', exist_ok=True)
        
        # Try to load settings, create default if file doesn't exist or is corrupted
        try:
            if os.path.exists(self.settings_location) and os.path.getsize(self.settings_location) > 0:
                self.settings = json.loads(open(self.settings_location, 'r').read())
            else:
                # Create default settings file
                self.settings = {"global": self.default_global_settings, "extensions": {}, "modules": {}}
                with open(self.settings_location, 'w') as f:
                    json.dump(self.settings, f, indent=4)
        except (json.JSONDecodeError, IOError) as e:
            # If there's an error reading the file, create a new one with defaults
            logger.warning(f"Error reading settings file: {e}. Creating new settings file with defaults.")
            self.settings = {"global": self.default_global_settings, "extensions": {}, "modules": {}}
            with open(self.settings_location, 'w') as f:
                json.dump(self.settings, f, indent=4)

        try:
            if self.settings['global']['advanced']['debug_mode']: logging.basicConfig(level=logging.DEBUG)
        except KeyError:
            pass

        os.makedirs('extensions', exist_ok=True)
        for extension in os.listdir('extensions'):  # Loading extensions
            if os.path.isdir(f'extensions/{extension}') and os.path.exists(f'extensions/{extension}/interface.py'):
                class_ = getattr(importlib.import_module(f'extensions.{extension}.interface'), 'OrpheusExtension', None)
                if class_:
                    self.extension_list.add(extension)
                    logging.debug(f'Orpheus: {extension} extension detected')
                else:
                    raise Exception('Error loading extension: "{extension}"')

        # Module preparation (not loaded yet for performance purposes)
        os.makedirs('modules', exist_ok=True)
        module_list = [module.lower() for module in os.listdir('modules') 
                      if os.path.exists(f'modules/{module}/interface.py') 
                      and module.lower() != 'example']  # Explicitly exclude example module
        if not module_list:
            print('No modules are installed, quitting')
            raise Exception('No modules are installed. Please install at least one module.')
        logging.debug('Orpheus: Modules detected: ' + ", ".join(module_list))

        for module in module_list:  # Loading module information into module_settings
            module_information: ModuleInformation = getattr(importlib.import_module(f'modules.{module}.interface'), 'module_information', None)
            if module_information and not ModuleFlags.private in module_information.flags and not private_mode:
                self.module_list.add(module)
                self.module_settings[module] = module_information
                logging.debug(f'Orpheus: {module} added as a module')
            else:
                raise Exception(f'Error loading module information from module: "{module}"') # TODO: replace with InvalidModuleError

        duplicates = set()
        for module in self.module_list: # Detecting duplicate url constants
            module_info: ModuleInformation = self.module_settings[module]
            url_constants = module_info.netlocation_constant
            if not isinstance(url_constants, list): url_constants = [str(url_constants)]
            for constant in url_constants:
                if constant.startswith('setting.'):
                    if self.settings.get('modules') and self.settings['modules'].get(module):
                        constant = self.settings['modules'][module][constant.split('setting.')[1]]
                    else:
                        constant = None

                if constant:
                    if constant not in self.module_netloc_constants:
                        self.module_netloc_constants[constant] = module
                    elif ModuleFlags.private in module_info.flags: # Replacing public modules with private ones
                        if ModuleFlags.private in self.module_settings[constant].flags: duplicates.add(constant)
                    else:
                        duplicates.add(sorted([module, self.module_netloc_constants[constant]]))
        if duplicates: raise Exception('Multiple modules installed that connect to the same service names: ' + ', '.join(' and '.join(duplicates)))

        self.update_module_storage()

        for i in self.extension_list:
            extension_settings: ExtensionInformation = getattr(importlib.import_module(f'extensions.{i}.interface'), 'extension_settings', None)
            settings = self.settings['extensions'][extension_settings.extension_type][extension] \
                if extension_settings.extension_type in self.settings['extensions'] \
                and extension in self.settings['extensions'][extension_settings.extension_type] else extension_settings.settings
            extension_type = extension_settings.extension_type
            self.extensions[extension_type] = self.extensions[extension_type] if extension_type in self.extensions else {}
            self.extensions[extension_type][extension] = class_(settings)

        [self.load_module(module) for module in self.module_list if ModuleFlags.startup_load in self.module_settings[module].flags]

        self.module_controls = {'module_list': self.module_list, 'module_settings': self.module_settings,
            'loaded_modules': self.loaded_modules, 'module_loader': self.load_module}

        self.progress_reporter = None

    def load_module(self, module: str):
        module = module.lower()
        if module not in self.module_list:
            raise Exception(f'"{module}" does not exist in modules.') # TODO: replace with InvalidModuleError
        if module not in self.loaded_modules:
            class_ = getattr(importlib.import_module(f'modules.{module}.interface'), 'ModuleInterface', None)
            if class_:
                class ModuleError(Exception): # TODO: get rid of this, as it is deprecated
                    def __init__(self, message):
                        super().__init__(module + ' --> ' + str(message))

                module_controller = ModuleController(
                    module_settings = self.settings['modules'][module] if module in self.settings['modules'] else {},
                    data_folder = os.path.join(self.data_folder_base, 'modules', module),
                    extensions = self.extensions,
                    temporary_settings_controller = TemporarySettingsController(module, self.session_storage_location),
                    module_error = ModuleError, # DEPRECATED
                    get_current_timestamp = true_current_utc_timestamp,
                    printer_controller = oprinter,
                    orpheus_options = OrpheusOptions(
                        debug_mode = self.settings['global']['advanced']['debug_mode'],
                        quality_tier = QualityEnum[self.settings['global']['general']['download_quality'].upper()],
                        disable_subscription_check = self.settings['global']['advanced']['disable_subscription_checks'],
                        default_cover_options = CoverOptions(
                            file_type = ImageFileTypeEnum[self.settings['global']['covers']['external_format']],
                            resolution = self.settings['global']['covers']['main_resolution'],
                            compression = CoverCompressionEnum[self.settings['global']['covers']['main_compression']]
                        )
                    )
                )

                loaded_module = class_(module_controller)
                self.loaded_modules[module] = loaded_module

                # Check if module has settings
                settings = self.settings['modules'][module] if module in self.settings['modules'] else {}
                temporary_session = read_temporary_setting(self.session_storage_location, module)
                if self.module_settings[module].login_behaviour is ManualEnum.orpheus:
                    # Login if simple mode, username login and requested by update_setting_storage
                    if temporary_session and temporary_session['clear_session'] and not self.settings['global']['advanced']['advanced_login_system']:
                        hashes = {k: hash_string(str(v)) for k, v in settings.items()}
                        if not temporary_session.get('hashes') or \
                            any(k not in hashes or hashes[k] != v for k,v in temporary_session['hashes'].items() if k in self.module_settings[module].session_settings):
                            print('Logging into ' + self.module_settings[module].service_name)
                            try:
                                loaded_module.login(settings['email'] if 'email' in settings else settings['username'], settings['password'])
                            except:
                                set_temporary_setting(self.session_storage_location, module, 'hashes', None, {})
                                raise
                            set_temporary_setting(self.session_storage_location, module, 'hashes', None, hashes)
                    if ModuleFlags.enable_jwt_system in self.module_settings[module].flags and temporary_session and \
                            temporary_session['refresh'] and not temporary_session['bearer']:
                        loaded_module.refresh_login()

                data_folder = os.path.join(self.data_folder_base, 'modules', module)
                if ModuleFlags.uses_data in self.module_settings[module].flags and not os.path.exists(data_folder): os.makedirs(data_folder)

                logging.debug(f'Orpheus: {module} module has been loaded')
                return loaded_module
            else:
                raise Exception(f'Error loading module: "{module}"') # TODO: replace with InvalidModuleError
        else:
            return self.loaded_modules[module]

    def update_module_storage(self): # Should be refactored eventually
        ## Settings
        old_settings, new_settings, global_settings, extension_settings, module_settings, new_setting_detected = {}, {}, {}, {}, {}, False

        for i in ['global', 'extensions', 'modules']:
            old_settings[i] = self.settings[i] if i in self.settings else {}

        for setting_type in self.default_global_settings:
            if setting_type in old_settings['global']:
                global_settings[setting_type] = {}
                for setting in self.default_global_settings[setting_type]:
                    # Also check if the type is identical
                    if (setting in old_settings['global'][setting_type] and
                            isinstance(self.default_global_settings[setting_type][setting],
                                       type(old_settings['global'][setting_type][setting]))):
                        global_settings[setting_type][setting] = old_settings['global'][setting_type][setting]
                    else:
                        global_settings[setting_type][setting] = self.default_global_settings[setting_type][setting]
                        new_setting_detected = True
            else:
                global_settings[setting_type] = self.default_global_settings[setting_type]
                new_setting_detected = True

        for i in self.extension_list:
            extension_information: ExtensionInformation = getattr(importlib.import_module(f'extensions.{i}.interface'), 'extension_settings', None)
            extension_type = extension_information.extension_type
            extension_settings[extension_type] = {} if 'extension_type' not in extension_settings else extension_settings[extension_type]
            old_settings['extensions'][extension_type] = {} if extension_type not in old_settings['extensions'] else old_settings['extensions'][extension_type]
            extension_settings[extension_type][i] = {} # This code regenerates the settings
            for j in extension_information.settings:
                if i in old_settings['extensions'][extension_type] and j in old_settings['extensions'][extension_type][i]:
                    extension_settings[extension_type][i][j] = old_settings['extensions'][extension_type][i][j]
                else:
                    extension_settings[extension_type][i][j] = extension_information.settings[j]
                    new_setting_detected = True

        advanced_login_mode = global_settings['advanced']['advanced_login_system']
        for i in self.module_list:
            module_settings[i] = {} # This code regenerates the settings
            if advanced_login_mode:
                settings_to_parse = self.module_settings[i].global_settings
            else:
                settings_to_parse = {**self.module_settings[i].global_settings, **self.module_settings[i].session_settings}
            if settings_to_parse:
                for j in settings_to_parse:
                    if i in old_settings['modules'] and j in old_settings['modules'][i]:
                        module_settings[i][j] = old_settings['modules'][i][j]
                    else:
                        module_settings[i][j] = settings_to_parse[j]
                        new_setting_detected = True
            else:
                module_settings.pop(i)

        new_settings['global'] = global_settings
        new_settings['extensions'] = extension_settings
        new_settings['modules'] = module_settings

        ## Sessions
        sessions = pickle.load(open(self.session_storage_location, 'rb')) if os.path.exists(self.session_storage_location) else {}

        if not ('advancedmode' in sessions and 'modules' in sessions and sessions['advancedmode'] == advanced_login_mode):
            sessions = {'advancedmode': advanced_login_mode, 'modules':{}}

        # in format {advancedmode, modules: {modulename: {default, type, custom_data, sessions: [sessionname: {##}]}}}
        # where ## is 'custom_session' plus if jwt 'access, refresh' (+ emailhash in simple)
        # in the special case of simple mode, session is always called default
        new_module_sessions = {}
        for i in self.module_list:
            # Clear storage if type changed
            new_module_sessions[i] = sessions['modules'][i] if i in sessions['modules'] else {'selected':'default', 'sessions':{'default':{}}}

            if self.module_settings[i].global_storage_variables: new_module_sessions[i]['custom_data'] = \
                {j:new_module_sessions[i]['custom_data'][j] for j in self.module_settings[i].global_storage_variables \
                    if 'custom_data' in new_module_sessions[i] and j in new_module_sessions[i]['custom_data']}

            for current_session in new_module_sessions[i]['sessions'].values():
                # For simple login type only, as it does not apply to advanced login
                if self.module_settings[i].login_behaviour is ManualEnum.orpheus and not advanced_login_mode:
                    hashes = {k:hash_string(str(v)) for k,v in module_settings[i].items()}
                    if current_session.get('hashes'):
                        clear_session = any(k not in hashes or hashes[k] != v for k,v in current_session['hashes'].items() if k in self.module_settings[i].session_settings)
                    else:
                        clear_session = True
                else:
                    clear_session = False
                current_session['clear_session'] = clear_session

                if ModuleFlags.enable_jwt_system in self.module_settings[i].flags:
                    if 'bearer' in current_session and current_session['bearer'] and not clear_session:
                        # Clears bearer token if it's expired
                        try:
                            time_left_until_refresh = json.loads(base64.b64decode(current_session['bearer'].split('.')[0]))['exp'] - true_current_utc_timestamp()
                            current_session['bearer'] = current_session['bearer'] if time_left_until_refresh > 0 else ''
                        except:
                            pass
                    else:
                        current_session['bearer'] = ''
                        current_session['refresh'] = ''
                else:
                    if 'bearer' in current_session: current_session.pop('bearer')
                    if 'refresh' in current_session: current_session.pop('refresh')

                if self.module_settings[i].session_storage_variables: current_session['custom_data'] = \
                    {j:current_session['custom_data'][j] for j in self.module_settings[i].session_storage_variables \
                        if 'custom_data' in current_session and j in current_session['custom_data'] and not clear_session}
                elif 'custom_data' in current_session: current_session.pop('custom_data')

        pickle.dump({'advancedmode': advanced_login_mode, 'modules': new_module_sessions}, open(self.session_storage_location, 'wb'))
        open(self.settings_location, 'w').write(json.dumps(new_settings, indent = 4, sort_keys = False))

        if new_setting_detected:
            print('New settings detected, or the configuration has been reset. Please update settings.json')
            exit()

    def set_progress_reporter(self, download_id: str):
        """Set the progress reporter for the current download."""
        self.progress_reporter = ProgressReporter(download_id)
        return self.progress_reporter
    
    def report_progress(self, current: int, total: int, message: str = None):
        """Report progress for the current download."""
        if self.progress_reporter:
            self.progress_reporter.report_progress(current, total, message)
    
    def report_message(self, message: str, level: int = 0):
        """Report a message for the current download."""
        if self.progress_reporter:
            self.progress_reporter.report_message(message, level)
    
    def report_status(self, status: str):
        """Report a status change for the current download."""
        if self.progress_reporter:
            self.progress_reporter.report_status(status)
    
    def report_error(self, error: str):
        """Report an error for the current download."""
        if self.progress_reporter:
            self.progress_reporter.report_error(error)
    
    def report_complete(self):
        """Report completion of the current download."""
        if self.progress_reporter:
            self.progress_reporter.report_complete()


# Configure logging
logger = logging.getLogger('orpheus-core')

def orpheus_core_download(orpheus_session: Orpheus, media_to_download, third_party_modules, separate_download_module, output_path):
    """Download media using the Orpheus core."""
    logger.debug("Starting orpheus_core_download")
    logger.debug(f"Media to download: {media_to_download}")
    logger.debug(f"Third-party modules: {third_party_modules}")
    logger.debug(f"Separate download module: {separate_download_module}")
    logger.debug(f"Output path: {output_path}")
    
    try:
        # Initialize download
        logger.debug("Initializing download")
        orpheus_session.report_status("initializing")
        orpheus_session.report_message("Initializing download...")
        
        # Process each service
        total_items = sum(len(items) for items in media_to_download.values())
        current_item = 0
        
        logger.debug(f"Total items to download: {total_items}")
        
        for service_name, items in media_to_download.items():
            logger.debug(f"Processing service: {service_name}")
            logger.debug(f"Items for this service: {items}")
            
            # Load the module if not already loaded
            if service_name not in orpheus_session.loaded_modules:
                logger.debug(f"Loading module: {service_name}")
                orpheus_session.report_message(f"Loading {service_name} module...")
                orpheus_session.load_module(service_name)
            
            # Get the module interface
            module_interface = orpheus_session.loaded_modules[service_name]
            logger.debug(f"Module interface loaded: {module_interface}")
            
            # Process each item
            for item in items:
                current_item += 1
                logger.debug(f"Processing item {current_item} of {total_items}: {item}")
                orpheus_session.report_progress(current_item, total_items, f"Processing item {current_item} of {total_items}")
                
                try:
                    # The item is already a MediaIdentification object, no need to identify it
                    logger.debug(f"Processing media: {item}")
                    orpheus_session.report_message(f"Processing {item}...")
                    media_identification = item
                    
                    if not media_identification:
                        logger.error(f"Failed to process {item}")
                        orpheus_session.report_error(f"Failed to process {item}")
                        continue
                    
                    logger.debug(f"Media to process: {media_identification}")
                    
                    # Download the media
                    logger.debug(f"Downloading media: {media_identification.media_id}")
                    orpheus_session.report_message(f"Downloading {media_identification.media_type.name} with ID {media_identification.media_id}...")
                    module_interface.download(
                        media_identification,
                        third_party_modules,
                        separate_download_module,
                        output_path
                    )
                    
                    logger.debug(f"Successfully downloaded: {media_identification.media_id}")
                    orpheus_session.report_message(f"Successfully downloaded {media_identification.media_type.name} with ID {media_identification.media_id}")
                    
                except Exception as e:
                    logger.error(f"Error processing {item}: {str(e)}", exc_info=True)
                    orpheus_session.report_error(f"Error processing {item}: {str(e)}")
                    continue
        
        # Report completion
        logger.debug("All downloads completed successfully")
        orpheus_session.report_status("completed")
        orpheus_session.report_message("All downloads completed successfully")
        orpheus_session.report_complete()
        
    except Exception as e:
        logger.error(f"Download failed: {str(e)}", exc_info=True)
        orpheus_session.report_error(f"Download failed: {str(e)}")
        raise
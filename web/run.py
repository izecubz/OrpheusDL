import os
import sys

# Change to the parent directory (OrpheusDL root)
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(parent_dir)

# Add the current directory to the Python path
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import and run the Flask app
from web.app import app

if __name__ == '__main__':
    print(f"Starting OrpheusDL web interface from: {os.getcwd()}")
    print(f"Python path: {sys.path}")
    
    # Disable Flask reloader to prevent the restart issue
    app.run(debug=True, host='0.0.0.0', use_reloader=False) 
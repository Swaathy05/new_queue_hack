# app_wrapper.py - Import from app_mongodb
# This file allows Render to find the app when using a different entry point

from app_mongodb import app, socketio

# This makes the app importable by gunicorn
if __name__ == '__main__':
    socketio.run(app) 
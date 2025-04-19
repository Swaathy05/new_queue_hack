# app.py - Simple redirect to app_mongodb
# This file allows Render to find the app when using the default app.py entry point

from app_mongodb import app, socketio

# This makes the app importable by gunicorn
if __name__ == '__main__':
    socketio.run(app)
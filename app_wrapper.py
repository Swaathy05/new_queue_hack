# app_wrapper.py - Import from app_mongodb with optimized settings
# This file allows Render to find the app using optimized settings

# Pre-configure gevent for better performance
import gevent.monkey
gevent.monkey.patch_all()

# Configure pymongo optimizations
import pymongo
pymongo.MongoClient = pymongo.MongoClient

# Import the app with optimized settings
from app_mongodb import app, socketio

# This makes the app importable by gunicorn
if __name__ == '__main__':
    # Use optimized settings
    socketio.run(app, 
                 async_mode='gevent',
                 cors_allowed_origins="*",
                 websocket=True,
                 ping_timeout=10,
                 ping_interval=25) 
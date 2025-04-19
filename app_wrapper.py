# app_wrapper.py - Smart wrapper that tries MongoDB first, falls back to SQLite
# This file allows Render to find the app using optimized settings

# Pre-configure gevent for better performance
import gevent.monkey
gevent.monkey.patch_all()

import os
import sys

# Try to import the MongoDB version, fall back to SQLite if it fails
try:
    print("Attempting to use MongoDB version...")
    # Configure pymongo optimizations
    import pymongo
    pymongo.MongoClient = pymongo.MongoClient
    
    # Import the MongoDB app with optimized settings
    from app_mongodb import app, socketio
    print("Successfully loaded MongoDB version")
except Exception as e:
    print(f"MongoDB version failed to load with error: {str(e)}")
    print("Falling back to SQLite version...")
    try:
        # Import the SQLite fallback
        from app_sqlite import app, socketio
        print("Successfully loaded SQLite fallback version")
    except Exception as e2:
        print(f"SQLite version also failed with error: {str(e2)}")
        sys.exit(1)

# This makes the app importable by gunicorn
if __name__ == '__main__':
    # Use optimized settings
    port = int(os.getenv('PORT', 5000))
    print(f"Starting server on port {port}")
    socketio.run(app, 
                 host='0.0.0.0',
                 port=port,
                 async_mode='gevent',
                 cors_allowed_origins="*",
                 websocket=True,
                 ping_timeout=10,
                 ping_interval=25) 
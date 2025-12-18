"""
WSGI entry point for production deployment with gunicorn + eventlet.

This module provides the WSGI application for gunicorn to run with
Socket.IO support via eventlet.

Usage with gunicorn:
    gunicorn --worker-class eventlet -w 1 wsgi:application

Note: When using eventlet worker, you should only use 1 worker since
eventlet handles concurrency via green threads. Multiple workers would
require sticky sessions or a proper message queue (which we have via Redis).
"""

# IMPORTANT: monkey_patch MUST be called before any other imports
import eventlet
eventlet.monkey_patch()

from app import app, socketio

# For gunicorn with eventlet, we need to use the Flask app directly
# The socketio.init_app() in app.py already wraps it correctly
# gunicorn will use the eventlet worker to handle websocket upgrades
application = app

# Export for `gunicorn wsgi:application`
# Alternative: use `gunicorn --worker-class eventlet -w 1 'wsgi:application'`

if __name__ == "__main__":
    socketio.run(app, debug=False, host='0.0.0.0', port=5000)

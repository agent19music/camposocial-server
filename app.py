from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_socketio import SocketIO, emit, join_room, leave_room
from models import db, TokenBlocklist
from datetime import timedelta
import os
import logging
from views import *
import boto3
import bcrypt
from dotenv import load_dotenv
from api_docs import api_bp as api_doc_bp
from api_explorer import api_explorer_bp
from welcome import welcome_bp
from websocket_handlers import register_socket_handlers
from redis_config import get_redis_url

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def create_app():
    app = Flask(__name__)

    # App Configurations
    # Handle PostgreSQL URL from Fly.io (convert postgres:// to postgresql://)
    database_url = os.getenv('DATABASE_URL', 'sqlite:///test.db')
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    # Add SSL parameters for Railway/cloud PostgreSQL databases if not already present
    if database_url.startswith('postgresql://') and '?' not in database_url:
        # Railway and other cloud providers often require SSL
        # Check if it's a Railway database (metro.proxy.rlwy.net) or other cloud provider
        if 'rlwy.net' in database_url or 'railway' in database_url.lower():
            database_url += '?sslmode=require'
        elif os.getenv('POSTGRES_SSL_MODE'):
            # Allow explicit SSL mode override via environment variable
            database_url += f"?sslmode={os.getenv('POSTGRES_SSL_MODE')}"
    
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'vsgewvwesvsgevafdsag')
    app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'vsgewvwesvsgevafdsag')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=1)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

    # Initialize Extensions
    db.init_app(app)
    migrate = Migrate(app, db)
    
    # Configure CORS with multiple allowed origins
    def _normalize_origin(origin: str | None) -> str | None:
        if not origin:
            return None
        origin = origin.strip()
        if not origin:
            return None
        return origin.rstrip('/')

    allowed_origins = {
        'http://localhost:3000',
        'http://127.0.0.1:3000',
        'http://localhost:8888',
        'http://127.0.0.1:8888',
        'https://camposocial.vercel.app',
        'https://www.camposocial.vercel.app',
        'https://camposocial.app',
        'https://www.camposocial.app',
        'https://seller.camposocial.app',
        'https://www.seller.camposocial.app',
        'http://localhost:3001',
        'http://127.0.0.1:3001',
    }

    # Load additional origins from environment variables
    for env_var in ('FRONTEND_URL', 'SELLER_DASHBOARD_URL', 'CORS_ALLOWED_ORIGINS'):
        value = os.getenv(env_var)
        if not value:
            continue
        if env_var == 'CORS_ALLOWED_ORIGINS':
            candidates = [item for item in value.split(',')]
        else:
            candidates = [value]
        for candidate in candidates:
            normalized = _normalize_origin(candidate)
            if normalized:
                allowed_origins.add(normalized)

                # Add localhost equivalent if 127.0.0.1 is used (and vice versa)
                if '127.0.0.1' in normalized:
                    allowed_origins.add(normalized.replace('127.0.0.1', 'localhost'))
                elif 'localhost' in normalized:
                    allowed_origins.add(normalized.replace('localhost', '127.0.0.1'))

    allowed_origins = sorted(allowed_origins)

    cors_resources = {
        r"/camposocial/api/*": {
            "origins": allowed_origins
        },
        r"/socket.io/*": {
            "origins": allowed_origins
        },
        r"/docs*": {
            "origins": allowed_origins
        },
        r"/api-explorer*": {
            "origins": allowed_origins
        },
        r"/*": {
            "origins": allowed_origins
        },
    }

    allowed_headers = [
        'Content-Type',
        'content-type',
        'Authorization',
        'authorization',
        'X-Requested-With',
        'Accept',
        'accept',
        'Origin',
        'origin',
    ]

    CORS(
        app,
        resources=cors_resources,
        supports_credentials=True,
        allow_headers=allowed_headers,
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
        expose_headers=['Content-Type', 'Authorization']
    )

    @app.after_request
    def apply_cors_headers(response):
        origin = _normalize_origin(request.headers.get('Origin'))
        if origin and origin in allowed_origins:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Vary'] = response.headers.get('Vary', '') + (', ' if response.headers.get('Vary') else '') + 'Origin'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers.setdefault(
                'Access-Control-Allow-Headers',
                ', '.join(sorted(set(allowed_headers)))
            )
            response.headers.setdefault(
                'Access-Control-Allow-Methods',
                'GET, POST, PUT, PATCH, DELETE, OPTIONS'
            )
        return response
    
    # Initialize SocketIO with Redis message queue for multi-worker/multi-container support
    redis_url = get_redis_url()
    
    # Determine async mode based on environment
    # In production with gunicorn+eventlet/gevent, use 'eventlet' or 'gevent'
    # For development with threading, use 'threading'
    async_mode = os.getenv('SOCKETIO_ASYNC_MODE', 'threading')
    
    socketio_kwargs = {
        'cors_allowed_origins': allowed_origins,
        'async_mode': async_mode,
        'logger': True,
        'engineio_logger': os.getenv('FLASK_DEBUG', 'false').lower() == 'true',
    }
    
    # Use Redis as message queue if available (required for multi-worker scaling)
    if redis_url and os.getenv('USE_REDIS_QUEUE', 'true').lower() == 'true':
        socketio_kwargs['message_queue'] = redis_url
        logging.info(f"[SocketIO] Using Redis message queue: {redis_url.split('@')[-1] if '@' in redis_url else redis_url}")
    else:
        logging.warning("[SocketIO] Running WITHOUT Redis message queue - events won't propagate across workers!")
    
    socketio = SocketIO(app, **socketio_kwargs)
    
    # Register enhanced WebSocket handlers
    register_socket_handlers(socketio)
    
    # JWT Setup
    jwt = JWTManager(app)

    # Blocklist for revoked tokens
    @jwt.token_in_blocklist_loader
    def token_in_blocklist_callback(jwt_header, jwt_data):
        jti = jwt_data['jti']
        token = TokenBlocklist.query.filter_by(jti=jti).first()
        return token is not None

    # Register blueprints with url_prefix
    app.register_blueprint(user_bp, url_prefix='/camposocial/api')
    app.register_blueprint(marketplace_bp, url_prefix='/camposocial/api')
    app.register_blueprint(event_bp, url_prefix='/camposocial/api')
    app.register_blueprint(auth_bp, url_prefix='/camposocial/api')
    app.register_blueprint(yap_bp, url_prefix='/camposocial/api')
    app.register_blueprint(friends_bp, url_prefix='/camposocial/api')
    app.register_blueprint(message_bp, url_prefix='/camposocial/api')
    app.register_blueprint(seller_bp, url_prefix='/camposocial/api')
    
    # Register media handling blueprint
    from views.media_view import media_bp
    app.register_blueprint(media_bp, url_prefix='/camposocial/api')
    
    # Advanced messaging functionality is now merged into message_bp
    
    # ========== PHASE 8 BLUEPRINTS ==========
    # Register Groups management blueprint
    from views.groups_view import groups_bp
    app.register_blueprint(groups_bp, url_prefix='/camposocial/api')
    
    # Register Polls and Surveys blueprint
    from views.polls_view import polls_bp
    app.register_blueprint(polls_bp, url_prefix='/camposocial/api')
    
    # Register Gamification blueprint
    from views.gamification_view import gamification_bp
    app.register_blueprint(gamification_bp, url_prefix='/camposocial/api')
    
    # Register Trending and Notifications blueprints
    from views.phase8_combined_view import trending_bp, notifications_bp
    app.register_blueprint(trending_bp, url_prefix='/camposocial/api')
    app.register_blueprint(notifications_bp, url_prefix='/camposocial/api')
    
    # Register Badges blueprint
    from views.badges_view import badges_bp
    app.register_blueprint(badges_bp, url_prefix='/camposocial/api/badges')
    
    # Register Debug/Admin blueprint for monitoring
    from views.debug_view import debug_bp
    app.register_blueprint(debug_bp, url_prefix='/camposocial/api')
    
    # Register API documentation blueprint
    app.register_blueprint(api_doc_bp)
    app.register_blueprint(api_explorer_bp)
    
    # Register welcome blueprint (handles root route)
    app.register_blueprint(welcome_bp)

    # Define the root route with welcome message and documentation links
    @app.route('/camposocial/api/')
    def index():
        """Welcome endpoint with API documentation links"""
        return jsonify({
            'message': 'Welcome to CampoSocial API',
            'version': '1.0',
            'documentation': {
                'swagger_ui': '/docs',
                'api_explorer': '/api-explorer',
                'endpoints': {
                    'authentication': '/camposocial/api/login',
                    'users': '/camposocial/api/users',
                    'events': '/camposocial/api/events',
                    'marketplace': '/camposocial/api/products',
                    'yaps': '/camposocial/api/yaps',
                    'friends': '/camposocial/api/friends'
                }
            },
            'status': 'active',
            'contact': 'support@camposocial.app'
        })
    
    return app, socketio

# Create app instance for Flask CLI
app, socketio = create_app()

if __name__ == '__main__':
    # Run the app
    socketio.run(app, debug=True, host='0.0.0.0', port=5001, allow_unsafe_werkzeug=True)
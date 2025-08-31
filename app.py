from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_socketio import SocketIO, emit, join_room, leave_room
from models import db, TokenBlocklist
from datetime import timedelta
import os
from views import *
import boto3
import bcrypt
from dotenv import load_dotenv
from api_docs import api_bp as api_doc_bp
from api_explorer import api_explorer_bp
from welcome import welcome_bp
from websocket_handlers import register_socket_handlers

load_dotenv()

def create_app():
    app = Flask(__name__)

    # App Configurations
    # Handle PostgreSQL URL from Fly.io (convert postgres:// to postgresql://)
    database_url = os.getenv('DATABASE_URL', 'sqlite:///test.db')
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
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
    allowed_origins = [
        'http://localhost:3000',
        'http://localhost:8888',
        'https://camposocial.vercel.app',
    ]
    
    # Add any additional origins from environment variable
    frontend_url = os.getenv('FRONTEND_URL')
    if frontend_url and frontend_url not in allowed_origins:
        allowed_origins.append(frontend_url)
    
    CORS(app,
         origins=allowed_origins,
         allow_headers=['Content-Type', 'Authorization'],
         supports_credentials=True)
    
    # Initialize SocketIO with proper configuration
    socketio = SocketIO(
        app, 
        cors_allowed_origins=allowed_origins,  # Use the same origins as Flask CORS
        async_mode='threading',  # Use threading mode for better compatibility
        logger=True,  # Enable logging for debugging
        engineio_logger=True  # Enable engine.io logging
    )
    
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
    
    # Register enhanced friends blueprint
    from views.friends_enhanced_view import friends_enhanced_bp
    app.register_blueprint(friends_enhanced_bp, url_prefix='/camposocial/api')
    
    # Register media handling blueprint
    from views.media_view import media_bp
    app.register_blueprint(media_bp, url_prefix='/camposocial/api')
    
    # Register advanced messaging blueprint
    from views.message_advanced_view import message_advanced_bp
    app.register_blueprint(message_advanced_bp, url_prefix='/camposocial/api')
    
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
            'contact': 'support@camposocial.com'
        })
    

    # Socket.IO event handlers
    @socketio.on('connect')
    def handle_connect(auth=None):
        try:
            print(f'Client attempting to connect: {request.sid}')
            # Basic connection allowed - authentication will be verified per-event
            print(f'Client connected: {request.sid}')
            emit('connected', {'status': 'success', 'sid': request.sid})
            return True
        except Exception as e:
            print(f'Connection error: {str(e)}')
            emit('error', {'message': 'Connection failed'})
            return False
        
    @socketio.on('disconnect')
    def handle_disconnect():
        print(f'Client disconnected: {request.sid}')
        
    @socketio.on('join_conversation')
    def handle_join_conversation(data):
        try:
            if not data:
                emit('error', {'message': 'No data provided'})
                return
                
            conversation_id = data.get('conversationId')
            auth_token = data.get('auth_token')
            
            if not auth_token:
                emit('error', {'message': 'Authentication required'})
                return
                
            if conversation_id:
                join_room(conversation_id)
                print(f'Client {request.sid} joined conversation {conversation_id}')
                emit('joined_conversation', {'conversationId': conversation_id})
            else:
                emit('error', {'message': 'No conversation ID provided'})
        except Exception as e:
            print(f'Error joining conversation: {str(e)}')
            emit('error', {'message': 'Failed to join conversation'})
            
    @socketio.on('leave_conversation')
    def handle_leave_conversation(data):
        try:
            conversation_id = data.get('conversationId')
            if conversation_id:
                leave_room(conversation_id)
                print(f'Client {request.sid} left conversation {conversation_id}')
                emit('left_conversation', {'conversationId': conversation_id})
        except Exception as e:
            print(f'Error leaving conversation: {str(e)}')
            emit('error', {'message': 'Failed to leave conversation'})

    return app, socketio

# Create app instance for Flask CLI
app, socketio = create_app()

if __name__ == '__main__':
    # Run the app
    socketio.run(app, debug=True, host='0.0.0.0', port=5001)

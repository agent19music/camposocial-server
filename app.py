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

load_dotenv()

def create_app():
    app = Flask(__name__)

    # App Configurations
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///test.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'vsgewvwesvsgevafdsag')
    app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'vsgewvwesvsgevafdsag')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=1)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

    # Initialize Extensions
    db.init_app(app)
    migrate = Migrate(app, db)
    CORS(app,
         origins=[os.getenv('FRONTEND_URL', 'http://localhost:3000')],
         allow_headers=['Content-Type', 'Authorization'],
         supports_credentials=True)
    
    # Initialize SocketIO with proper configuration
    socketio = SocketIO(
        app, 
        cors_allowed_origins=os.getenv('FRONTEND_URL', 'http://localhost:3000'),
        async_mode='threading',  # Use threading mode for better compatibility
        logger=True,  # Enable logging for debugging
        engineio_logger=True  # Enable engine.io logging
    )
    
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
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)

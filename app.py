from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from models import db
from datetime import timedelta
import os
from views import *
import boto3
import bcrypt
from redis import Redis

def create_app():
    app = Flask(__name__)

    # App Configurations
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///test.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 'vsgewvwesvsgevafdsag'
    app.config['JWT_SECRET_KEY'] = 'vsgewvwesvsgevafdsag'
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=1)  # Set token expiration time
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Max request size 16MB

    redis_host = os.environ.get("REDIS_HOST", "localhost")
    redis_port = int(os.environ.get("REDIS_PORT", 6379))
    redis_db = int(os.environ.get("REDIS_DB", 0))

    redis_client = Redis(host=redis_host, port=redis_port, db=redis_db)


    # Initialize Extensions
    db.init_app(app)
    migrate = Migrate(app, db)
    CORS(app)
    
    # JWT Setup
    jwt = JWTManager(app)

    # Blocklist for revoked tokens
    @jwt.token_in_blocklist_loader
    def token_in_blocklist_callback(jwt_header, jwt_data):
        jti = jwt_data['jti']
        token = TokenBlocklist.query.filter_by(jti=jti).first()
        return token is not None

    # Register blueprints
    app.register_blueprint(user_bp)
    app.register_blueprint(marketplace_bp)
    app.register_blueprint(event_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(yap_bp)

    # Define the root route
    @app.route('/')
    def index():
        return jsonify({'message': 'Welcome to CampoSocial API'})

    return app

if __name__ == '__main__':
    # Create the app and run it
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)

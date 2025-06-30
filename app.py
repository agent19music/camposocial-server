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
from dotenv import load_dotenv

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

    # Define the root route
    @app.route('/camposocial/api/')
    def index():
        return jsonify({'message': 'Welcome to CampoSocial API'})

    return app

if __name__ == '__main__':
    # Create the app and run it
    app = create_app()
    app.run(debug=True)

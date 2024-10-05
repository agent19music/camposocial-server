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

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///test.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'vsgewvwesvsgevafdsag'  
app.config['JWT_SECRET_KEY'] = 'vsgewvwesvsgevafdsag'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=1)  # Set token expiration time
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Set maximum content length for incoming requests to 16 MB



db.init_app(app)
migrate = Migrate(app, db)
CORS(app)

app.register_blueprint(user_bp)
app.register_blueprint(marketplace_bp)
app.register_blueprint(event_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(yap_bp)


jwt = JWTManager(app)

@jwt.token_in_blocklist_loader
def token_in_blocklist_callback(jwt_header, jwt_data):
    jti = jwt_data['jti']
    token = TokenBlocklist.query.filter_by(jti=jti).first()
    if token:
        return token 
    else:
        return None
    


@app.route('/')
def index():
    return jsonify({'message': 'Welcome to camposocial  API'})

if __name__ == '__main__':
    app.run(debug=True)
 

#!/usr/bin/env python3
"""
Test script to verify all imports from media_view.py work correctly
"""

def test_imports():
    """Test all imports used in media_view.py"""
    try:
        # Test PIL imports
        from PIL import Image, ImageOps
        print("✓ PIL imports successful")
        
        # Test OpenCV import
        import cv2
        print("✓ OpenCV import successful")
        
        # Test numpy import
        import numpy as np
        print("✓ NumPy import successful")
        
        # Test boto3 import
        import boto3
        from botocore.exceptions import NoCredentialsError
        print("✓ Boto3 imports successful")
        
        # Test magic import
        import magic
        print("✓ Python-magic import successful")
        
        # Test cryptography imports
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.backends import default_backend
        print("✓ Cryptography imports successful")
        
        # Test other standard imports
        import os
        import io
        import hashlib
        import mimetypes
        import base64
        from datetime import datetime
        print("✓ Standard library imports successful")
        
        # Test Flask imports
        from flask import Blueprint, request, jsonify, send_file, current_app
        from flask_jwt_extended import jwt_required, get_jwt_identity
        from werkzeug.utils import secure_filename
        print("✓ Flask imports successful")
        
        # Test SQLAlchemy imports
        from sqlalchemy import or_, and_
        print("✓ SQLAlchemy imports successful")
        
        print("\n🎉 All imports successful! The media_view.py file should work correctly.")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Please install the missing package using: pip install <package_name>")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    test_imports()

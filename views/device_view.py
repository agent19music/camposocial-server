"""
E2EE Device Management API Endpoints

This module provides endpoints for managing user devices in the E2EE system:
- Device registration with public keys
- Device listing and management
- Device revocation
- Key backup and restore functionality
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Users, UserDevice, EncryptedKeyBackup, MessageRecipientKey
from datetime import datetime
import uuid

device_bp = Blueprint('device_bp', __name__)


# ============================================================================
# Device Management Endpoints
# ============================================================================

@device_bp.route('/devices', methods=['GET'])
@jwt_required()
def list_devices():
    """List all registered devices for the current user."""
    current_user_id = get_jwt_identity()
    
    devices = UserDevice.query.filter_by(
        user_id=current_user_id,
        is_active=True
    ).order_by(UserDevice.last_active.desc()).all()
    
    return jsonify({
        'devices': [device.to_dict() for device in devices],
        'count': len(devices)
    }), 200


@device_bp.route('/devices', methods=['POST'])
@jwt_required()
def register_device():
    """Register a new device with its public key.
    
    Request body:
    {
        "device_id": "uuid-string",
        "device_name": "Chrome on MacBook",
        "device_type": "web",
        "public_key": "base64-encoded-nacl-public-key"
    }
    """
    current_user_id = get_jwt_identity()
    data = request.get_json()
    
    # Validate required fields
    device_id = data.get('device_id')
    public_key = data.get('public_key')
    
    if not device_id:
        # Generate UUID if not provided
        device_id = str(uuid.uuid4())
    
    if not public_key:
        return jsonify({'error': 'public_key is required'}), 400
    
    # Check if device already exists
    existing_device = UserDevice.query.get(device_id)
    if existing_device:
        # Update existing device
        existing_device.public_key = public_key
        existing_device.device_name = data.get('device_name', existing_device.device_name)
        existing_device.device_type = data.get('device_type', existing_device.device_type)
        existing_device.user_agent = request.headers.get('User-Agent', '')[:512]
        existing_device.last_active = datetime.utcnow()
        existing_device.is_active = True
        db.session.commit()
        
        return jsonify({
            'message': 'Device updated',
            'device': existing_device.to_dict()
        }), 200
    
    # Create new device
    device = UserDevice(
        id=device_id,
        user_id=current_user_id,
        device_name=data.get('device_name', 'Unknown Device'),
        device_type=data.get('device_type', 'web'),
        public_key=public_key,
        user_agent=request.headers.get('User-Agent', '')[:512],
        created_at=datetime.utcnow(),
        last_active=datetime.utcnow(),
        is_active=True
    )
    
    db.session.add(device)
    db.session.commit()
    
    return jsonify({
        'message': 'Device registered successfully',
        'device': device.to_dict()
    }), 201


@device_bp.route('/devices/<device_id>', methods=['DELETE'])
@jwt_required()
def revoke_device(device_id):
    """Revoke/deactivate a device.
    
    This doesn't delete the device record but marks it as inactive.
    Old messages encrypted for this device will still be accessible
    until they expire or are deleted.
    """
    current_user_id = get_jwt_identity()
    
    device = UserDevice.query.filter_by(
        id=device_id,
        user_id=current_user_id
    ).first()
    
    if not device:
        return jsonify({'error': 'Device not found'}), 404
    
    device.is_active = False
    db.session.commit()
    
    return jsonify({
        'message': 'Device revoked successfully',
        'device_id': device_id
    }), 200


@device_bp.route('/devices/<device_id>/heartbeat', methods=['POST'])
@jwt_required()
def device_heartbeat(device_id):
    """Update device's last_active timestamp."""
    current_user_id = get_jwt_identity()
    
    device = UserDevice.query.filter_by(
        id=device_id,
        user_id=current_user_id,
        is_active=True
    ).first()
    
    if not device:
        return jsonify({'error': 'Device not found'}), 404
    
    device.last_active = datetime.utcnow()
    db.session.commit()
    
    return jsonify({'success': True}), 200


# ============================================================================
# Key Backup Endpoints
# ============================================================================

@device_bp.route('/keys/backup', methods=['POST'])
@jwt_required()
def upload_key_backup():
    """Upload encrypted private key backup.
    
    The private key is encrypted client-side with the user's recovery
    passphrase. The server never sees the plaintext key.
    
    Request body:
    {
        "encrypted_private_key": "base64-encoded-encrypted-key",
        "key_salt": "base64-encoded-salt",
        "key_iv": "base64-encoded-iv"
    }
    """
    current_user_id = get_jwt_identity()
    data = request.get_json()
    
    encrypted_key = data.get('encrypted_private_key')
    key_salt = data.get('key_salt')
    key_iv = data.get('key_iv')
    
    if not all([encrypted_key, key_salt, key_iv]):
        return jsonify({
            'error': 'encrypted_private_key, key_salt, and key_iv are required'
        }), 400
    
    # Check if backup already exists
    existing_backup = EncryptedKeyBackup.query.filter_by(
        user_id=current_user_id
    ).first()
    
    if existing_backup:
        # Update existing backup
        existing_backup.encrypted_private_key = encrypted_key
        existing_backup.key_salt = key_salt
        existing_backup.key_iv = key_iv
        existing_backup.updated_at = datetime.utcnow()
    else:
        # Create new backup
        backup = EncryptedKeyBackup(
            user_id=current_user_id,
            encrypted_private_key=encrypted_key,
            key_salt=key_salt,
            key_iv=key_iv,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.session.add(backup)
    
    db.session.commit()
    
    return jsonify({
        'message': 'Key backup saved successfully',
        'has_backup': True
    }), 200


@device_bp.route('/keys/backup', methods=['GET'])
@jwt_required()
def get_key_backup():
    """Retrieve encrypted private key backup.
    
    Returns the encrypted key backup that can be decrypted
    client-side with the user's recovery passphrase.
    """
    current_user_id = get_jwt_identity()
    
    backup = EncryptedKeyBackup.query.filter_by(
        user_id=current_user_id
    ).first()
    
    if not backup:
        return jsonify({
            'has_backup': False,
            'message': 'No key backup found'
        }), 404
    
    return jsonify({
        'has_backup': True,
        **backup.to_dict()
    }), 200


@device_bp.route('/keys/backup', methods=['DELETE'])
@jwt_required()
def delete_key_backup():
    """Delete the encrypted key backup.
    
    Warning: This is irreversible. If the user loses their device
    and hasn't backed up their keys elsewhere, they will lose
    access to their encrypted messages.
    """
    current_user_id = get_jwt_identity()
    
    backup = EncryptedKeyBackup.query.filter_by(
        user_id=current_user_id
    ).first()
    
    if not backup:
        return jsonify({'error': 'No key backup found'}), 404
    
    db.session.delete(backup)
    db.session.commit()
    
    return jsonify({
        'message': 'Key backup deleted',
        'has_backup': False
    }), 200


@device_bp.route('/keys/backup/status', methods=['GET'])
@jwt_required()
def check_backup_status():
    """Check if user has a key backup."""
    current_user_id = get_jwt_identity()
    
    backup = EncryptedKeyBackup.query.filter_by(
        user_id=current_user_id
    ).first()
    
    return jsonify({
        'has_backup': backup is not None,
        'created_at': backup.created_at.isoformat() + 'Z' if backup else None,
        'updated_at': backup.updated_at.isoformat() + 'Z' if backup else None
    }), 200


# ============================================================================
# Device Keys Lookup (for encryption)
# ============================================================================

@device_bp.route('/keys/devices/<int:user_id>', methods=['GET'])
@jwt_required()
def get_user_device_keys(user_id):
    """Get all public keys for a user's active devices.
    
    Used when sending a message to encrypt for all recipient devices.
    """
    current_user_id = get_jwt_identity()
    
    # Verify the requesting user has permission (is friends or self)
    # For now, allow any authenticated user to get device keys
    # In production, you might want to restrict this to friends only
    
    devices = UserDevice.query.filter_by(
        user_id=user_id,
        is_active=True
    ).all()
    
    return jsonify({
        'user_id': user_id,
        'devices': [
            {
                'device_id': device.id,
                'public_key': device.public_key,
                'device_type': device.device_type
            }
            for device in devices
        ],
        'count': len(devices)
    }), 200


@device_bp.route('/keys/devices/bulk', methods=['POST'])
@jwt_required()
def get_bulk_device_keys():
    """Get device keys for multiple users at once.
    
    Useful when sending to a group or getting keys for
    both sender and recipient in one request.
    
    Request body:
    {
        "user_ids": [1, 2, 3]
    }
    """
    data = request.get_json()
    user_ids = data.get('user_ids', [])
    
    if not user_ids:
        return jsonify({'error': 'user_ids array is required'}), 400
    
    result = {}
    for user_id in user_ids:
        devices = UserDevice.query.filter_by(
            user_id=user_id,
            is_active=True
        ).all()
        
        result[str(user_id)] = [
            {
                'device_id': device.id,
                'public_key': device.public_key,
                'device_type': device.device_type
            }
            for device in devices
        ]
    
    return jsonify({
        'device_keys': result
    }), 200

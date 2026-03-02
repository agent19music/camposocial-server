"""
Signal Protocol API Endpoints

Handles pre-key bundle upload, fetch, and replenishment for
Signal Protocol E2EE messaging.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import (
    db, Users, SignalIdentityKey, SignalSignedPreKey, SignalOneTimePreKey
)
from datetime import datetime
from sqlalchemy import and_

signal_bp = Blueprint('signal_bp', __name__)


@signal_bp.route('/signal/keys', methods=['POST'])
@jwt_required()
def upload_prekey_bundle():
    """
    Upload a complete pre-key bundle for a device.
    
    This is called when:
    - A new device is registered
    - Keys need to be refreshed
    
    Expected body:
    {
        "registrationId": 12345,
        "deviceId": "uuid-string",
        "identityKey": "base64-public-key",
        "signedPreKey": {
            "keyId": 1,
            "publicKey": "base64",
            "signature": "base64"
        },
        "oneTimePreKeys": [
            {"keyId": 1, "publicKey": "base64"},
            ...
        ]
    }
    """
    current_user_id = get_jwt_identity()
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    required_fields = ['registrationId', 'deviceId', 'identityKey', 'signedPreKey']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400
    
    signed_prekey = data.get('signedPreKey', {})
    if not all(k in signed_prekey for k in ['keyId', 'publicKey', 'signature']):
        return jsonify({'error': 'Invalid signedPreKey structure'}), 400
    
    device_id = data['deviceId']
    
    try:
        # Upsert identity key
        identity_key = SignalIdentityKey.query.filter(
            and_(
                SignalIdentityKey.user_id == current_user_id,
                SignalIdentityKey.device_id == device_id
            )
        ).first()
        
        if identity_key:
            # Update existing
            identity_key.identity_key = data['identityKey']
            identity_key.registration_id = data['registrationId']
            identity_key.updated_at = datetime.utcnow()
        else:
            # Create new
            identity_key = SignalIdentityKey(
                user_id=current_user_id,
                device_id=device_id,
                identity_key=data['identityKey'],
                registration_id=data['registrationId']
            )
            db.session.add(identity_key)
        
        # Upsert signed pre-key
        signed_pk = SignalSignedPreKey.query.filter(
            and_(
                SignalSignedPreKey.user_id == current_user_id,
                SignalSignedPreKey.device_id == device_id,
                SignalSignedPreKey.key_id == signed_prekey['keyId']
            )
        ).first()
        
        if not signed_pk:
            signed_pk = SignalSignedPreKey(
                user_id=current_user_id,
                device_id=device_id,
                key_id=signed_prekey['keyId'],
                public_key=signed_prekey['publicKey'],
                signature=signed_prekey['signature'],
                timestamp=signed_prekey.get('timestamp', int(datetime.utcnow().timestamp() * 1000))
            )
            db.session.add(signed_pk)
        else:
            signed_pk.public_key = signed_prekey['publicKey']
            signed_pk.signature = signed_prekey['signature']
            signed_pk.timestamp = signed_prekey.get('timestamp', int(datetime.utcnow().timestamp() * 1000))
        
        # Store one-time pre-keys
        one_time_keys = data.get('oneTimePreKeys', [])
        for otk in one_time_keys:
            existing = SignalOneTimePreKey.query.filter(
                and_(
                    SignalOneTimePreKey.user_id == current_user_id,
                    SignalOneTimePreKey.device_id == device_id,
                    SignalOneTimePreKey.key_id == otk['keyId']
                )
            ).first()
            
            if not existing:
                new_otk = SignalOneTimePreKey(
                    user_id=current_user_id,
                    device_id=device_id,
                    key_id=otk['keyId'],
                    public_key=otk['publicKey']
                )
                db.session.add(new_otk)
        
        db.session.commit()
        
        # Count remaining one-time pre-keys
        otk_count = SignalOneTimePreKey.query.filter(
            and_(
                SignalOneTimePreKey.user_id == current_user_id,
                SignalOneTimePreKey.device_id == device_id
            )
        ).count()
        
        return jsonify({
            'message': 'Pre-key bundle uploaded successfully',
            'oneTimePreKeyCount': otk_count
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to upload keys: {str(e)}'}), 500


@signal_bp.route('/signal/keys/<int:user_id>/<device_id>', methods=['GET'])
@jwt_required()
def get_prekey_bundle(user_id, device_id):
    """
    Fetch a pre-key bundle for a user/device.
    
    This consumes one one-time pre-key (if available).
    Returns all public keys needed to establish a Signal session.
    """
    current_user_id = get_jwt_identity()
    
    # Don't allow fetching own keys
    if user_id == current_user_id:
        return jsonify({'error': 'Cannot fetch own pre-key bundle'}), 400
    
    # Get identity key
    identity_key = SignalIdentityKey.query.filter(
        and_(
            SignalIdentityKey.user_id == user_id,
            SignalIdentityKey.device_id == device_id
        )
    ).first()
    
    if not identity_key:
        return jsonify({'error': 'No keys found for user/device'}), 404
    
    # Get latest signed pre-key
    signed_prekey = SignalSignedPreKey.query.filter(
        and_(
            SignalSignedPreKey.user_id == user_id,
            SignalSignedPreKey.device_id == device_id
        )
    ).order_by(SignalSignedPreKey.timestamp.desc()).first()
    
    if not signed_prekey:
        return jsonify({'error': 'No signed pre-key found'}), 404
    
    # Get and consume one one-time pre-key
    one_time_prekey = SignalOneTimePreKey.query.filter(
        and_(
            SignalOneTimePreKey.user_id == user_id,
            SignalOneTimePreKey.device_id == device_id
        )
    ).first()
    
    response = {
        'userId': str(user_id),
        'deviceId': device_id,
        'registrationId': identity_key.registration_id,
        'identityKey': identity_key.identity_key,
        'signedPreKeyId': signed_prekey.key_id,
        'signedPreKey': signed_prekey.public_key,
        'signedPreKeySignature': signed_prekey.signature,
    }
    
    if one_time_prekey:
        response['oneTimePreKeyId'] = one_time_prekey.key_id
        response['oneTimePreKey'] = one_time_prekey.public_key
        
        # Consume the one-time pre-key
        db.session.delete(one_time_prekey)
        db.session.commit()
    
    return jsonify(response), 200


@signal_bp.route('/signal/keys/<device_id>/devices', methods=['GET'])
@jwt_required()
def get_user_devices(device_id):
    """
    Get all active devices for a user that have Signal keys.
    Used to encrypt messages for all recipient devices.
    """
    # device_id here is actually user_id (for backward compat with URL structure)
    user_id = device_id
    
    try:
        user_id_int = int(user_id)
    except ValueError:
        return jsonify({'error': 'Invalid user ID'}), 400
    
    # Get all devices with Signal keys
    identity_keys = SignalIdentityKey.query.filter(
        SignalIdentityKey.user_id == user_id_int
    ).all()
    
    devices = []
    for ik in identity_keys:
        devices.append({
            'deviceId': ik.device_id,
            'registrationId': ik.registration_id,
        })
    
    return jsonify({
        'userId': user_id,
        'devices': devices
    }), 200


@signal_bp.route('/signal/keys/replenish', methods=['POST'])
@jwt_required()
def replenish_one_time_prekeys():
    """
    Upload additional one-time pre-keys.
    
    Called when the server's pool of one-time pre-keys is low.
    
    Expected body:
    {
        "deviceId": "uuid-string",
        "oneTimePreKeys": [
            {"keyId": 101, "publicKey": "base64"},
            ...
        ]
    }
    """
    current_user_id = get_jwt_identity()
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    device_id = data.get('deviceId')
    one_time_keys = data.get('oneTimePreKeys', [])
    
    if not device_id:
        return jsonify({'error': 'Missing deviceId'}), 400
    
    if not one_time_keys:
        return jsonify({'error': 'No one-time pre-keys provided'}), 400
    
    try:
        added = 0
        for otk in one_time_keys:
            # Check if key ID already exists
            existing = SignalOneTimePreKey.query.filter(
                and_(
                    SignalOneTimePreKey.user_id == current_user_id,
                    SignalOneTimePreKey.device_id == device_id,
                    SignalOneTimePreKey.key_id == otk['keyId']
                )
            ).first()
            
            if not existing:
                new_otk = SignalOneTimePreKey(
                    user_id=current_user_id,
                    device_id=device_id,
                    key_id=otk['keyId'],
                    public_key=otk['publicKey']
                )
                db.session.add(new_otk)
                added += 1
        
        db.session.commit()
        
        # Get current count
        total_count = SignalOneTimePreKey.query.filter(
            and_(
                SignalOneTimePreKey.user_id == current_user_id,
                SignalOneTimePreKey.device_id == device_id
            )
        ).count()
        
        return jsonify({
            'message': f'Added {added} one-time pre-keys',
            'totalCount': total_count
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to replenish keys: {str(e)}'}), 500


@signal_bp.route('/signal/prekey-count', methods=['GET'])
@jwt_required()
def get_prekey_count():
    """
    Get the count of remaining one-time pre-keys for the current user's devices.
    
    Used by client to determine when to replenish keys.
    
    Query params:
    - deviceId: (optional) Get count for specific device, otherwise all devices
    """
    current_user_id = get_jwt_identity()
    device_id = request.args.get('deviceId')
    
    query = SignalOneTimePreKey.query.filter(
        SignalOneTimePreKey.user_id == current_user_id
    )
    
    if device_id:
        query = query.filter(SignalOneTimePreKey.device_id == device_id)
    
    if device_id:
        count = query.count()
        return jsonify({
            'deviceId': device_id,
            'count': count,
            'needsReplenish': count < 20
        }), 200
    else:
        # Group by device
        from sqlalchemy import func
        counts = db.session.query(
            SignalOneTimePreKey.device_id,
            func.count(SignalOneTimePreKey.id).label('count')
        ).filter(
            SignalOneTimePreKey.user_id == current_user_id
        ).group_by(SignalOneTimePreKey.device_id).all()
        
        devices = []
        for device_id, count in counts:
            devices.append({
                'deviceId': device_id,
                'count': count,
                'needsReplenish': count < 20
            })
        
        return jsonify({
            'devices': devices
        }), 200


@signal_bp.route('/signal/keys/<device_id>', methods=['DELETE'])
@jwt_required()
def delete_device_keys(device_id):
    """
    Delete all Signal keys for a specific device.
    Used when logging out of a device or revoking it.
    """
    current_user_id = get_jwt_identity()
    
    try:
        # Delete identity key
        SignalIdentityKey.query.filter(
            and_(
                SignalIdentityKey.user_id == current_user_id,
                SignalIdentityKey.device_id == device_id
            )
        ).delete()
        
        # Delete signed pre-keys
        SignalSignedPreKey.query.filter(
            and_(
                SignalSignedPreKey.user_id == current_user_id,
                SignalSignedPreKey.device_id == device_id
            )
        ).delete()
        
        # Delete one-time pre-keys
        SignalOneTimePreKey.query.filter(
            and_(
                SignalOneTimePreKey.user_id == current_user_id,
                SignalOneTimePreKey.device_id == device_id
            )
        ).delete()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Device keys deleted successfully'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to delete keys: {str(e)}'}), 500

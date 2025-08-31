from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Badge, UserBadge, BadgeTransaction, Users
from mpesa_service import mpesa_service
from datetime import datetime
import uuid

badges_bp = Blueprint('badges', __name__, url_prefix='/api/badges')

@badges_bp.route('/', methods=['GET'])
@jwt_required()
def get_available_badges():
    """Get all available badges for purchase"""
    try:
        badges = Badge.query.filter_by(is_active=True).all()
        return jsonify({
            'success': True,
            'badges': [{
                'id': badge.id,
                'name': badge.name,
                'description': badge.description,
                'image_url': badge.image_url,
                'price_ksh': badge.price_ksh,
                'is_animated': badge.is_animated
            } for badge in badges]
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@badges_bp.route('/user/<int:user_id>', methods=['GET'])
@jwt_required()
def get_user_badges(user_id):
    """Get badges owned by a user"""
    try:
        user_badges = db.session.query(UserBadge, Badge).join(Badge).filter(
            UserBadge.user_id == user_id
        ).order_by(UserBadge.display_order, UserBadge.purchased_at.desc()).all()
        
        badges_data = []
        displayed_badges = []
        
        for user_badge, badge in user_badges:
            badge_info = {
                'id': badge.id,
                'name': badge.name,
                'description': badge.description,
                'image_url': badge.image_url,
                'is_animated': badge.is_animated,
                'is_displayed': user_badge.is_displayed,
                'display_order': user_badge.display_order,
                'purchased_at': user_badge.purchased_at.isoformat()
            }
            badges_data.append(badge_info)
            
            if user_badge.is_displayed:
                displayed_badges.append(badge_info)
        
        # Limit displayed badges to 3
        displayed_badges = displayed_badges[:3]
        
        return jsonify({
            'success': True,
            'all_badges': badges_data,
            'displayed_badges': displayed_badges
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@badges_bp.route('/purchase', methods=['POST'])
@jwt_required()
def initiate_badge_purchase():
    """Initiate badge purchase with M-Pesa STK Push"""
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json()
        
        badge_id = data.get('badge_id')
        phone_number = data.get('phone_number')
        
        if not badge_id or not phone_number:
            return jsonify({'success': False, 'error': 'Badge ID and phone number required'}), 400
        
        # Check if badge exists and is active
        badge = Badge.query.filter_by(id=badge_id, is_active=True).first()
        if not badge:
            return jsonify({'success': False, 'error': 'Badge not found or inactive'}), 404
        
        # Check if user already owns this badge
        existing_badge = UserBadge.query.filter_by(
            user_id=current_user_id, 
            badge_id=badge_id
        ).first()
        if existing_badge:
            return jsonify({'success': False, 'error': 'You already own this badge'}), 400
        
        # Generate unique account reference
        account_reference = f"BADGE_{badge_id}_{current_user_id}_{int(datetime.now().timestamp())}"
        transaction_desc = f"Badge Purchase: {badge.name}"
        
        # Create transaction record
        transaction = BadgeTransaction(
            user_id=current_user_id,
            badge_id=badge_id,
            phone_number=phone_number,
            amount=badge.price_ksh,
            status='PENDING'
        )
        db.session.add(transaction)
        db.session.flush()  # Get the transaction ID
        
        # Initiate M-Pesa STK Push
        mpesa_response = mpesa_service.stk_push(
            phone_number=phone_number,
            amount=badge.price_ksh,
            account_reference=account_reference,
            transaction_desc=transaction_desc
        )
        
        # Update transaction with checkout request ID
        if mpesa_response.get('CheckoutRequestID'):
            transaction.checkout_request_id = mpesa_response['CheckoutRequestID']
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Payment initiated. Please complete payment on your phone.',
                'transaction_id': transaction.id,
                'checkout_request_id': mpesa_response['CheckoutRequestID']
            }), 200
        else:
            transaction.status = 'FAILED'
            transaction.error_message = mpesa_response.get('errorMessage', 'Failed to initiate payment')
            db.session.commit()
            
            return jsonify({
                'success': False,
                'error': 'Failed to initiate payment. Please try again.'
            }), 400
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@badges_bp.route('/transaction/<int:transaction_id>/status', methods=['GET'])
@jwt_required()
def check_transaction_status(transaction_id):
    """Check the status of a badge purchase transaction"""
    try:
        current_user_id = get_jwt_identity()
        
        transaction = BadgeTransaction.query.filter_by(
            id=transaction_id,
            user_id=current_user_id
        ).first()
        
        if not transaction:
            return jsonify({'success': False, 'error': 'Transaction not found'}), 404
        
        # If transaction is already completed, return status
        if transaction.status == 'COMPLETED':
            return jsonify({
                'success': True,
                'status': 'COMPLETED',
                'transaction': {
                    'id': transaction.id,
                    'status': transaction.status,
                    'amount': transaction.amount,
                    'completed_at': transaction.completed_at.isoformat() if transaction.completed_at else None
                }
            }), 200
        
        # Query M-Pesa for transaction status
        if transaction.checkout_request_id:
            mpesa_response = mpesa_service.query_transaction_status(transaction.checkout_request_id)
            
            if mpesa_response.get('ResultCode') == '0':  # Success
                # Update transaction as completed
                transaction.status = 'COMPLETED'
                transaction.completed_at = datetime.utcnow()
                transaction.mpesa_receipt_number = mpesa_response.get('MpesaReceiptNumber')
                
                # Grant badge to user
                user_badge = UserBadge(
                    user_id=current_user_id,
                    badge_id=transaction.badge_id,
                    is_displayed=True,
                    display_order=0  # New badges get priority display
                )
                
                # Adjust display order of existing badges
                existing_badges = UserBadge.query.filter_by(
                    user_id=current_user_id,
                    is_displayed=True
                ).all()
                
                for i, existing_badge in enumerate(existing_badges):
                    existing_badge.display_order = i + 1
                
                db.session.add(user_badge)
                db.session.commit()
                
                return jsonify({
                    'success': True,
                    'status': 'COMPLETED',
                    'message': 'Badge purchased successfully!'
                }), 200
                
            elif mpesa_response.get('ResultCode') == '1032':  # Cancelled by user
                transaction.status = 'CANCELLED'
                db.session.commit()
                
                return jsonify({
                    'success': False,
                    'status': 'CANCELLED',
                    'message': 'Payment was cancelled'
                }), 200
                
            elif mpesa_response.get('ResultCode'):  # Other error
                transaction.status = 'FAILED'
                transaction.error_message = mpesa_response.get('ResultDesc', 'Payment failed')
                db.session.commit()
                
                return jsonify({
                    'success': False,
                    'status': 'FAILED',
                    'message': mpesa_response.get('ResultDesc', 'Payment failed')
                }), 200
        
        # Still pending
        return jsonify({
            'success': True,
            'status': 'PENDING',
            'message': 'Payment is still being processed'
        }), 200
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@badges_bp.route('/manage', methods=['POST'])
@jwt_required()
def manage_badge_display():
    """Update which badges to display and their order"""
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json()
        
        displayed_badge_ids = data.get('displayed_badge_ids', [])
        
        if len(displayed_badge_ids) > 3:
            return jsonify({'success': False, 'error': 'Cannot display more than 3 badges'}), 400
        
        # Reset all badges to not displayed
        UserBadge.query.filter_by(user_id=current_user_id).update({'is_displayed': False})
        
        # Set selected badges as displayed with proper order
        for i, badge_id in enumerate(displayed_badge_ids):
            user_badge = UserBadge.query.filter_by(
                user_id=current_user_id,
                badge_id=badge_id
            ).first()
            
            if user_badge:
                user_badge.is_displayed = True
                user_badge.display_order = i
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Badge display settings updated'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@badges_bp.route('/callback', methods=['POST'])
def mpesa_callback():
    """Handle M-Pesa payment callbacks"""
    try:
        data = request.get_json()
        
        # Extract callback data
        callback_data = data.get('Body', {}).get('stkCallback', {})
        checkout_request_id = callback_data.get('CheckoutRequestID')
        result_code = callback_data.get('ResultCode')
        result_desc = callback_data.get('ResultDesc')
        
        if not checkout_request_id:
            return jsonify({'success': False, 'error': 'Invalid callback data'}), 400
        
        # Find the transaction
        transaction = BadgeTransaction.query.filter_by(
            checkout_request_id=checkout_request_id
        ).first()
        
        if not transaction:
            return jsonify({'success': False, 'error': 'Transaction not found'}), 404
        
        if result_code == 0:  # Success
            # Extract callback metadata
            callback_metadata = callback_data.get('CallbackMetadata', {}).get('Item', [])
            mpesa_receipt_number = None
            transaction_id = None
            
            for item in callback_metadata:
                if item.get('Name') == 'MpesaReceiptNumber':
                    mpesa_receipt_number = item.get('Value')
                elif item.get('Name') == 'TransactionId':
                    transaction_id = item.get('Value')
            
            # Update transaction
            transaction.status = 'COMPLETED'
            transaction.completed_at = datetime.utcnow()
            transaction.mpesa_receipt_number = mpesa_receipt_number
            transaction.mpesa_transaction_id = transaction_id
            
            # Grant badge to user
            user_badge = UserBadge(
                user_id=transaction.user_id,
                badge_id=transaction.badge_id,
                is_displayed=True,
                display_order=0
            )
            
            # Adjust display order of existing badges
            existing_badges = UserBadge.query.filter_by(
                user_id=transaction.user_id,
                is_displayed=True
            ).all()
            
            for i, existing_badge in enumerate(existing_badges):
                existing_badge.display_order = i + 1
            
            db.session.add(user_badge)
            
        else:  # Failed
            transaction.status = 'FAILED'
            transaction.error_message = result_desc
        
        db.session.commit()
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

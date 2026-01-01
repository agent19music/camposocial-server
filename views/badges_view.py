from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Badge, UserBadge, BadgeTransaction, Users
from badge_payment_service import get_badge_payment_service, get_current_provider_name
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
    """Initiate badge purchase with M-Pesa STK Push (supports IntaSend or native M-Pesa)"""
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
        
        # Get user for payment details
        user = Users.query.get(current_user_id)
        
        # Generate unique order reference
        order_ref = f"BADGE_{badge_id}_{current_user_id}_{int(datetime.now().timestamp())}"
        
        # Get the configured payment provider
        payment_service = get_badge_payment_service()
        provider_name = get_current_provider_name()
        current_app.logger.info(f"Using payment provider: {provider_name}")
        
        # Create transaction record with provider info
        transaction = BadgeTransaction(
            user_id=current_user_id,
            badge_id=badge_id,
            phone_number=phone_number,
            amount=badge.price_ksh,
            status='PENDING',
            payment_provider=provider_name
        )
        db.session.add(transaction)
        db.session.flush()  # Get the transaction ID
        
        # Initiate M-Pesa STK Push via configured provider
        customer_name = f"{user.first_name} {user.last_name}" if user else None
        payment_result = payment_service.initiate_payment(
            phone_number=phone_number,
            amount=badge.price_ksh,
            order_ref=order_ref,
            description=f"Badge: {badge.name}",
            email=user.email if user else None,
            customer_name=customer_name
        )
        
        if payment_result.success and payment_result.invoice_id:
            # Update transaction with checkout info
            transaction.checkout_request_id = payment_result.invoice_id
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Payment initiated. Please complete payment on your phone.',
                'transaction_id': transaction.id,
                'invoice_id': payment_result.invoice_id,
                'state': payment_result.state,
                'provider': provider_name
            }), 200
        else:
            # Payment initiation failed
            transaction.status = 'FAILED'
            transaction.error_message = payment_result.error_message
            db.session.commit()
            
            current_app.logger.error(f"Payment initiation failed: {payment_result.error_message}")
            return jsonify({
                'success': False,
                'error': 'Failed to initiate payment. Please try again.'
            }), 400
            
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Badge purchase error: {str(e)}")
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
        
        # Query payment provider for status
        if transaction.checkout_request_id:
            payment_service = get_badge_payment_service()
            
            try:
                status_result = payment_service.check_payment_status(transaction.checkout_request_id)
                
                if status_result.completed:
                    # Update transaction as completed
                    transaction.status = 'COMPLETED'
                    transaction.completed_at = datetime.utcnow()
                    transaction.mpesa_receipt_number = status_result.receipt_number
                    
                    # Grant badge to user
                    _grant_badge_to_user(transaction.user_id, transaction.badge_id)
                    db.session.commit()
                    
                    return jsonify({
                        'success': True,
                        'status': 'COMPLETED',
                        'message': 'Badge purchased successfully!'
                    }), 200
                    
                elif status_result.failed:
                    transaction.status = 'FAILED'
                    transaction.error_message = status_result.error_message or 'Payment failed'
                    db.session.commit()
                    
                    return jsonify({
                        'success': False,
                        'status': 'FAILED',
                        'message': transaction.error_message
                    }), 200
                    
            except Exception as e:
                current_app.logger.error(f"Error checking payment status: {str(e)}")
                pass  # Continue with pending status
        
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

@badges_bp.route('/webhook/intasend', methods=['POST'])
def intasend_webhook():
    """Handle IntaSend payment webhooks for badge purchases"""
    try:
        from intasend_service import get_intasend_service
        
        payload = request.get_json()
        signature = request.headers.get('X-IntaSend-Signature', '')
        
        # Get IntaSend service for webhook parsing
        intasend = get_intasend_service()
        raw_body = request.get_data(as_text=True)
        
        # Optionally verify signature (skip if webhook secret not configured)
        # if not intasend.verify_webhook_signature(raw_body, signature):
        #     return jsonify({'success': False, 'error': 'Invalid signature'}), 401
        
        # Parse webhook data
        event_data = intasend.parse_webhook_payload(payload)
        invoice_id = event_data.get('invoice_id')
        state = event_data.get('state', '').upper()
        api_ref = event_data.get('api_ref', '')
        
        current_app.logger.info(f"IntaSend webhook received: invoice_id={invoice_id}, state={state}")
        
        if not invoice_id:
            return jsonify({'success': False, 'error': 'Invalid webhook data'}), 400
        
        # Find the transaction by invoice_id
        transaction = BadgeTransaction.query.filter_by(
            checkout_request_id=invoice_id
        ).first()
        
        if not transaction:
            # Try to find by api_ref (order_ref we created)
            # Format: BADGE_{badge_id}_{user_id}_{timestamp}
            if api_ref.startswith('BADGE_'):
                parts = api_ref.split('_')
                if len(parts) >= 3:
                    badge_id = parts[1]
                    user_id = parts[2]
                    transaction = BadgeTransaction.query.filter_by(
                        badge_id=badge_id,
                        user_id=user_id,
                        status='PENDING'
                    ).first()
        
        if not transaction:
            current_app.logger.warning(f"IntaSend webhook: Transaction not found for invoice_id={invoice_id}")
            return jsonify({'success': True, 'message': 'Transaction not found, ignoring'}), 200
        
        if state == 'COMPLETE':
            transaction.status = 'COMPLETED'
            transaction.completed_at = datetime.utcnow()
            transaction.mpesa_receipt_number = event_data.get('raw_response', {}).get('invoice', {}).get('mpesa_reference')
            
            # Grant badge to user
            _grant_badge_to_user(transaction.user_id, transaction.badge_id)
            current_app.logger.info(f"Badge granted to user {transaction.user_id} via IntaSend webhook")
            
        elif state == 'FAILED':
            transaction.status = 'FAILED'
            transaction.error_message = event_data.get('failed_reason', 'Payment failed')
            current_app.logger.info(f"IntaSend payment failed for transaction {transaction.id}")
        
        db.session.commit()
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"IntaSend webhook error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@badges_bp.route('/webhook/mpesa', methods=['POST'])
def mpesa_webhook():
    """Handle native M-Pesa callback for badge purchases"""
    try:
        payload = request.get_json()
        current_app.logger.info(f"M-Pesa callback received: {payload}")
        
        # M-Pesa callback structure
        # {
        #   "Body": {
        #     "stkCallback": {
        #       "MerchantRequestID": "...",
        #       "CheckoutRequestID": "...",
        #       "ResultCode": 0,
        #       "ResultDesc": "...",
        #       "CallbackMetadata": { "Item": [...] }
        #     }
        #   }
        # }
        
        stk_callback = payload.get('Body', {}).get('stkCallback', {})
        checkout_request_id = stk_callback.get('CheckoutRequestID')
        result_code = stk_callback.get('ResultCode')
        result_desc = stk_callback.get('ResultDesc', '')
        
        if not checkout_request_id:
            current_app.logger.warning("M-Pesa callback: Missing CheckoutRequestID")
            return jsonify({'success': False, 'error': 'Invalid callback data'}), 400
        
        # Find the transaction
        transaction = BadgeTransaction.query.filter_by(
            checkout_request_id=checkout_request_id,
            payment_provider='mpesa'
        ).first()
        
        if not transaction:
            current_app.logger.warning(f"M-Pesa callback: Transaction not found for {checkout_request_id}")
            return jsonify({'success': True, 'message': 'Transaction not found, ignoring'}), 200
        
        if result_code == 0:
            # Success - extract receipt number from metadata
            callback_metadata = stk_callback.get('CallbackMetadata', {}).get('Item', [])
            receipt_number = None
            for item in callback_metadata:
                if item.get('Name') == 'MpesaReceiptNumber':
                    receipt_number = item.get('Value')
                    break
            
            transaction.status = 'COMPLETED'
            transaction.completed_at = datetime.utcnow()
            transaction.mpesa_receipt_number = receipt_number
            
            # Grant badge to user
            _grant_badge_to_user(transaction.user_id, transaction.badge_id)
            current_app.logger.info(f"Badge granted to user {transaction.user_id} via M-Pesa callback")
            
        elif result_code == 1032:
            # User cancelled
            transaction.status = 'CANCELLED'
            transaction.error_message = 'Transaction cancelled by user'
            current_app.logger.info(f"M-Pesa payment cancelled for transaction {transaction.id}")
            
        else:
            # Other failure
            transaction.status = 'FAILED'
            transaction.error_message = result_desc or 'Payment failed'
            current_app.logger.info(f"M-Pesa payment failed for transaction {transaction.id}: {result_desc}")
        
        db.session.commit()
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"M-Pesa callback error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


def _grant_badge_to_user(user_id: int, badge_id: int):
    """Helper to grant a badge to a user"""
    # Check if user already has this badge
    existing = UserBadge.query.filter_by(user_id=user_id, badge_id=badge_id).first()
    if existing:
        return
    
    # Grant badge to user
    user_badge = UserBadge(
        user_id=user_id,
        badge_id=badge_id,
        is_displayed=True,
        display_order=0  # New badges get priority display
    )
    
    # Adjust display order of existing badges
    existing_badges = UserBadge.query.filter_by(
        user_id=user_id,
        is_displayed=True
    ).all()
    
    for i, existing_badge in enumerate(existing_badges):
        existing_badge.display_order = i + 1
    
    db.session.add(user_badge)

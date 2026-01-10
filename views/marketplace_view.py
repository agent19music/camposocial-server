from models import db, Products, Wishlists, Reviews, Users, ProductVariation, ProductImages, Order, Seller, Cart, CartItem, OrderItem
from flask import request, jsonify, Blueprint,make_response
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import or_, func
from datetime import datetime
import base64
import os
import boto3
import requests
from dotenv import load_dotenv
load_dotenv()

marketplace_bp = Blueprint('marketplace_bp', __name__)

R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME')
R2_ENDPOINT_URL = os.getenv('R2_ENDPOINT_URL')
IMAGE_PREFIX = os.getenv('IMAGE_PREFIX')
PAYSTACK_SECRET_KEY = os.getenv('PAYSTACK_SECRET_KEY')


def get_s3_client():
    if not all([R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]):
        return None
    return boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY
    )

s3_client = get_s3_client()


def serialize_seller(seller: Seller):
    return {
        "id": seller.id,
        "display_name": seller.display_name,
        "about": seller.about,
        "avatar": seller.avatar,
        "phone_no": seller.phone_no,
        "is_verified": seller.is_verified,
        "created_at": seller.created_at.isoformat() if getattr(seller, "created_at", None) else None,
        "total_products": seller.product_count(),
        "total_sales": seller.total_sales(),
    }

@marketplace_bp.route('/check-seller', methods=['GET'])
@jwt_required()
def check_seller():
    """Check if the current user is a seller"""
    try:
        user_id = get_jwt_identity()
        seller = Seller.query.filter_by(user_id=user_id).first()
        if seller:
            return jsonify({
                "is_seller": True,
                "seller": serialize_seller(seller)
            }), 200
        return jsonify({"is_seller": False}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@marketplace_bp.route('/seller/me', methods=['GET'])
@jwt_required()
def get_current_seller():
    """Return the authenticated user's seller profile if it exists"""
    try:
        user_id = get_jwt_identity()
        seller = Seller.query.filter_by(user_id=user_id).first()
        if not seller:
            return jsonify({"is_seller": False}), 200
        return jsonify({
            "is_seller": True,
            "seller": serialize_seller(seller)
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@marketplace_bp.route('/products', methods=['GET'])
def get_products():
    """
    Get all products.
    """
    try:
        products = Products.query.all()
        result = [
            {
                'id': product.id,
                'slug': product.slug,  # SEO-friendly URL slug
                'title': product.title,
                'description': product.description,
                'contact_info': product.contact_info,
                'brand': product.brand,
                'price': product.price,
                'category': product.category,
                'created_at': product.created_at.isoformat(),
                'updated_at': product.updated_at.isoformat(),
                'average_rating': product.average_rating(), 
                # Include URLs to product images if needed
                'images': [image.image_url for image in product.images],
                # Include variations if needed
                'variations': [
                    {
                        'size': variation.variation_name,
                        'color': variation.variation_value,
                        'stock': variation.stock,
                        'price': variation.price
                    } for variation in product.variations
                ],
               'seller': {
    'name': product.seller.display_name if product.seller else None, 
    'avatar': product.seller.avatar if product.seller else None,
    'verified': product.seller.is_verified if product.seller else None,
    'id': product.seller.id if product.seller else None, 


}
            } for product in products
        ]
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@marketplace_bp.route('/seller', methods=['POST'])
@jwt_required()
def add_seller():
    try:
        user_id = get_jwt_identity()

        is_multipart = request.content_type and 'multipart/form-data' in request.content_type
        data = request.form if is_multipart else (request.get_json() or {})

        display_name = (data.get('display_name') or '').strip()
        about = (data.get('about') or '').strip()
        phone_no = (data.get('phone') or '').strip() if data.get('phone') else None

        if not display_name:
            return jsonify({"error": "Business display name is required"}), 400
        if not about:
            return jsonify({"error": "About section is required"}), 400

        existing_seller = Seller.query.filter_by(user_id=user_id).first()

        avatar_url = (data.get('avatar_url') or '').strip() or (existing_seller.avatar if existing_seller else None)
        avatar_file = request.files.get('avatar_file') if is_multipart else None

        if avatar_file and avatar_file.filename:
            if not s3_client:
                return jsonify({"error": "Image upload service is not configured"}), 500
            filename = secure_filename(avatar_file.filename)
            s3_client.upload_fileobj(
                avatar_file,
                R2_BUCKET_NAME,
                filename,
                ExtraArgs={"ACL": "public-read"}
            )
            avatar_url = f"{IMAGE_PREFIX}/{filename}"

        if existing_seller:
            existing_seller.display_name = display_name
            existing_seller.about = about
            existing_seller.phone_no = phone_no
            existing_seller.avatar = avatar_url
            seller_record = existing_seller
        else:
            seller_record = Seller(
                display_name=display_name,
                about=about,
                phone_no=phone_no,
                user_id=user_id,
                avatar=avatar_url
            )
            db.session.add(seller_record)

        user = Users.query.get(user_id)
        if user:
            user.profile_completed = True

        db.session.commit()

        return jsonify({
            "message": "Seller profile saved successfully",
            "seller": serialize_seller(seller_record)
        }), 200 if existing_seller else 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@marketplace_bp.route('/sellers/<string:seller_id>', methods=['GET'])
def get_seller(seller_id):
    try:
        seller = Seller.query.filter_by(id=seller_id).first()
        if not seller:
            return jsonify({"error": "Seller not found"}), 404

        # Calculate total products and sales
        total_products = seller.product_count()
        total_sales = seller.total_sales()

        # Calculate average rating across all products
        all_reviews = []
        for product in seller.products:
            all_reviews.extend([review.rating for review in product.reviews])

        average_rating = sum(all_reviews) / len(all_reviews) if all_reviews else None

        # Construct seller data with detailed product info
        seller_data = {
            "name": seller.display_name,
            "isVerified": seller.is_verified,
            "about": seller.about,
            "avatar": seller.avatar,
            "total_products": total_products,
            "totalSales": total_sales,
            "rating": average_rating,
            "products": []
        }

        for product in seller.products:
            # Get images and variations for each product
            images = [image.image_url for image in product.images]
            variations = [
                {
                    "id": variation.id,
                    "name": variation.variation_name,
                    "value": variation.variation_value,
                    "price": variation.price,
                    "stock": variation.stock
                }
                for variation in product.variations
            ]

            # Add product with images, variations, and reviews to seller data
            product_data = {
                "id": product.id,
                "title": product.title,
                "description": product.description,
                "price": product.price,
                "category": product.category,
                "created_at": product.created_at,
                "updated_at": product.updated_at,
                "images": images,
                "variations": variations,
                "reviews": [{"rating": review.rating, "content": review.content} for review in product.reviews]
            }

            seller_data["products"].append(product_data)

        return jsonify(seller_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Route to get a specific product by slug or id
@marketplace_bp.route('/products/<string:identifier>', methods=['GET'])
def get_single_product(identifier):
    try:
        # Try to find by slug first (preferred), then fall back to ID
        product = Products.query.filter_by(slug=identifier).first()
        if not product:
            # Fallback to ID for backwards compatibility
            product = Products.query.filter_by(id=identifier).first()
        if not product:
            return jsonify({"error": "Product not found"}), 404

        # Get images associated with the product
        images = [image.image_url for image in product.images]

        # Get variations for the product
        variations = [
            {
                "id": variation.id,
                "name": variation.variation_name,
                "value": variation.variation_value,
                "price": variation.price,
                "stock": variation.stock
            }
            for variation in product.variations
        ]

        # Get reviews for the product
        reviews = [
            {
                "rating": review.rating,
                "text": review.text,
                "username": review.user.username if review.user else None,  # Assumes `reviewer` relation
                "avatar": review.user.avatar if review.user else None  # Assumes `reviewer` relation

            }
            for review in product.reviews
        ]

        # Structure the product data
        product_data = {
            "id": product.id,
            "slug": product.slug,  # SEO-friendly URL slug
            'average_rating': product.average_rating(),
            "title": product.title,
            "description": product.description,
            "price": product.price,
            "category": product.category,
            "contact_info": product.contact_info,
            "brand": product.brand,
            "created_at": product.created_at.isoformat() if product.created_at else None,
            "updated_at": product.updated_at.isoformat() if product.updated_at else None,
            "seller_id": product.seller_id,
            # Flat fields for backwards compatibility
            "sellerName": product.seller.display_name if product.seller else None,
            "sellerAvatar": product.seller.avatar if product.seller else None,
            "sellerIsVerified": product.seller.is_verified if product.seller else False,
            # Nested seller object for frontend
            "seller": {
                "id": product.seller.id if product.seller else None,
                "name": product.seller.display_name if product.seller else None,
                "avatar": product.seller.avatar if product.seller else None,
                "is_verified": product.seller.is_verified if product.seller else False,
                "sales": product.seller.total_sales() if product.seller else 0,
                "rating": 4.5  # TODO: Calculate from reviews
            } if product.seller else None,
            "images": images,
            "variations": variations,
            "reviews": reviews,
        }

        return jsonify(product_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@marketplace_bp.route('/cart/add', methods=['POST'])
@jwt_required()  # Assuming you want to require authentication
def add_to_cart():
    data = request.get_json()
    user_id = get_jwt_identity()  # Get the user ID from the JWT token
    product_id = data.get('product_id')
    variation_id = data.get('product_variation_id')
    quantity = data.get('quantity', 1)
    
    if not product_id:
        return jsonify({'error': 'Product ID is required'}), 400

    # Find or create a cart for the user
    cart = Cart.query.filter_by(user_id=user_id).first()
    if not cart:
        cart = Cart(user_id=user_id)
        db.session.add(cart)
        db.session.commit()

    # Check if the product exists
    product = Products.query.get(product_id)
    if not product:
        return jsonify({'error': 'Product not found'}), 404

    # Check if the product variation exists, if provided
    product_variation = None
    if variation_id:
        product_variation = ProductVariation.query.get(variation_id)
        if not product_variation:
            return jsonify({'error': 'Product variation not found'}), 404

    # Check if the item with the same product and variation already exists in the cart
    existing_cart_item = CartItem.query.filter_by(
        cart_id=cart.id, 
        product_id=product_id, 
        product_variation_id=variation_id
    ).first()

    if existing_cart_item:
        # Update the quantity if it already exists
        existing_cart_item.quantity += quantity
    else:
        # Add a new cart item
        new_cart_item = CartItem(
            cart_id=cart.id,
            product_id=product_id,
            product_variation_id=variation_id,
            quantity=quantity
        )
        db.session.add(new_cart_item)

    db.session.commit()

    return jsonify({'message': 'Product added to cart successfully'}), 201

@marketplace_bp.route('/cart/<user_id>', methods=['GET'])
def get_cart_items(user_id):
    # Find the user's cart based on their user_id
    cart = Cart.query.filter_by(user_id=user_id).first()
    if not cart:
        # Return empty cart instead of 404 error
        return jsonify({'cart_items': []}), 200

    cart_items_details = []

    # Loop through the cart items and fetch necessary details
    for item in cart.cart_items:
        # Product data
        product = item.product
        if not product:
            continue  # Skip if product data is missing
        
        # Product variation data (if available)
        product_variation = item.product_variation
        price = product_variation.price if product_variation else product.price

        # Collect product images (assuming product.images is a relationship or a method that returns a list of images)
        images = [image.image_url for image in product.images] if product.images else []

        cart_items_details.append({
            'product_title': product.title,
            'product_id': product.id,
            'id' : item.id,
            'quantity': item.quantity,
            'price_per_item': price,
            'total_item_price': item.total_item_price(),
            'images': images
        })

    return jsonify({'cart_items': cart_items_details}), 200

@marketplace_bp.route('/cart/update_quantity', methods=['POST'])
def update_cart_quantity():
    data = request.get_json()
    item_id = data.get('itemId')
    quantity = data.get('quantity')

    if not item_id or quantity is None:
        return jsonify({"error": "Invalid data"}), 400

    # Fetch the cart item from the database
    cart_item = CartItem.query.get(item_id)

    if not cart_item:
        return jsonify({"error": "Item not found"}), 404

    if quantity <= 0:
        # If quantity is zero or less, remove the item from the cart
        db.session.delete(cart_item)
        db.session.commit()
        return jsonify({"message": "Item removed from cart"}), 200
    else:
        # Otherwise, update the item's quantity
        cart_item.quantity = quantity
        db.session.commit()
        return jsonify({"message": "Quantity updated", "quantity": cart_item.quantity}), 200

@marketplace_bp.route('/cart/remove_item', methods=['DELETE'])
def remove_item():
    data = request.get_json()
    item_id = data.get('itemId')

    try:
        cart_item = CartItem.query.get(item_id)
        if cart_item:
            db.session.delete(cart_item)
            db.session.commit()
            return jsonify({"message": "Item removed successfully"}), 200
        return jsonify({"error": "Cart item not found"}), 404
    except Exception as e:
        print(f"Error removing cart item: {e}")
        return jsonify({"error": "Failed to remove cart item"}), 500

@marketplace_bp.route('/create_order', methods=['POST'])
@jwt_required()
def create_order():
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json()

        first_name = data.get('first_name')
        last_name = data.get('last_name')
        email = data.get('email')
        phone = data.get('phone')
        address = data.get('address') 
        total_price = data.get('total_price')
        discount_code = data.get('discount_code')
        payment_mode = data.get('payment_mode', 'pay_before')  # pay_before, pay_on_delivery

        if not all([first_name, last_name, email, phone, address]):
            return jsonify({'error': 'Missing customer details'}), 400

        # Fetch the user's cart
        cart = Cart.query.filter_by(user_id=current_user_id).first()
        if not cart or not cart.cart_items:
            return jsonify({'error': 'Cart is empty'}), 400

        # Calculate cart total
        cart_total = 0
        for cart_item in cart.cart_items:
            product = cart_item.product
            if product:
                cart_total += product.price * cart_item.quantity
        
        # Apply discount if provided
        discount_amount = 0
        applied_discount = None
        if discount_code:
            from models import Discount
            discount = Discount.query.filter_by(code=discount_code.upper().strip()).first()
            if discount and discount.is_valid():
                discount_amount = discount.calculate_discount(cart_total)
                applied_discount = discount
        
        final_total = cart_total - discount_amount
        if total_price and abs(float(total_price) - final_total) > 1:
            # Client-side total mismatch - recalculate
            final_total = cart_total - discount_amount

        # Generate ticket number
        from cuid import cuid
        ticket_number = f"CS-{datetime.utcnow().strftime('%Y%m%d')}-{cuid()[-6:].upper()}"

        # Create the order
        order = Order(
            user_id=current_user_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            address=address,
            total_price=final_total,
            payment_mode=payment_mode,
            discount_code=discount_code.upper().strip() if discount_code else None,
            discount_amount=discount_amount,
            ticket_number=ticket_number,
            status='pending',
            paid=False if payment_mode == 'pay_before' else None
        )
        db.session.add(order)
        db.session.commit()  # Commit to get the order ID

        # Copy cart items to order items with seller tracking
        for cart_item in cart.cart_items:
            product = cart_item.product
            if product:
                order_item = OrderItem(
                    order_id=order.id,
                    product_id=cart_item.product_id,
                    quantity=cart_item.quantity,
                    seller_id=product.seller_id,
                    price_at_purchase=product.price,
                    product_variation_id=cart_item.variation_id if hasattr(cart_item, 'variation_id') else None
                )
                db.session.add(order_item)

        # Update discount usage count if applied
        if applied_discount:
            applied_discount.current_uses += 1
        
        # Clear the cart after successful order creation
        for item in cart.cart_items:
            db.session.delete(item)
        
        db.session.commit()

        return jsonify({
            'message': 'Order created successfully', 
            'order_id': order.id,
            'ticket_number': ticket_number,
            'total_price': final_total,
            'discount_applied': discount_amount > 0,
            'discount_amount': discount_amount,
            'payment_mode': payment_mode
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Failed to create order', 'details': str(e)}), 500


@marketplace_bp.route('/validate_discount', methods=['POST'])
@jwt_required()
def validate_discount():
    """Validate a discount code and calculate discount amount"""
    try:
        data = request.get_json()
        code = data.get('code', '').upper().strip()
        cart_total = data.get('cart_total', 0)
        
        if not code:
            return jsonify({'error': 'Discount code required'}), 400
        
        from models import Discount
        discount = Discount.query.filter_by(code=code).first()
        
        if not discount:
            return jsonify({'valid': False, 'error': 'Invalid discount code'}), 400
        
        if not discount.is_valid():
            if discount.max_uses and discount.current_uses >= discount.max_uses:
                return jsonify({'valid': False, 'error': 'Discount code has been fully redeemed'}), 400
            if discount.expires_at and datetime.utcnow() > discount.expires_at:
                return jsonify({'valid': False, 'error': 'Discount code has expired'}), 400
            return jsonify({'valid': False, 'error': 'Discount code is not active'}), 400
        
        if cart_total < discount.min_order_amount:
            return jsonify({
                'valid': False, 
                'error': f'Minimum order amount of KES {discount.min_order_amount} required'
            }), 400
        
        discount_amount = discount.calculate_discount(cart_total)
        
        return jsonify({
            'valid': True,
            'code': discount.code,
            'discount_type': discount.discount_type,
            'value': discount.value,
            'discount_amount': discount_amount,
            'final_total': cart_total - discount_amount
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@marketplace_bp.route('/my_orders', methods=['GET'])
@jwt_required()
def get_user_orders():
    """Get current user's order history"""
    try:
        current_user_id = get_jwt_identity()
        
        orders = Order.query.filter_by(user_id=current_user_id).order_by(
            Order.created_at.desc()
        ).all()
        
        result = [{
            'id': order.id,
            'ticket_number': getattr(order, 'ticket_number', None),
            'status': getattr(order, 'status', 'pending'),
            'paid': order.paid,
            'payment_mode': getattr(order, 'payment_mode', 'pay_before'),
            'total_price': order.total_price,
            'discount_amount': getattr(order, 'discount_amount', 0),
            'tracking_number': getattr(order, 'tracking_number', None),
            'shipping_carrier': getattr(order, 'shipping_carrier', None),
            'items': [{
                'product_id': item.product_id,
                'product_title': item.product.title if item.product else None,
                'product_image': item.product.images[0].image_url if item.product and item.product.images else None,
                'quantity': item.quantity,
                'price': getattr(item, 'price_at_purchase', None) or (item.product.price if item.product else 0)
            } for item in order.order_items],
            'created_at': order.created_at.isoformat()
        } for order in orders]
        
        return jsonify({
            'orders': result,
            'count': len(result)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@marketplace_bp.route('/request_refund', methods=['POST'])
@jwt_required()
def request_refund():
    """Customer refund request"""
    try:
        from models import Refund
        
        current_user_id = get_jwt_identity()
        data = request.get_json()
        
        order_id = data.get('order_id')
        reason = data.get('reason', '').strip()
        amount = data.get('amount')
        
        if not order_id or not reason:
            return jsonify({'error': 'Order ID and reason required'}), 400
        
        order = Order.query.get(order_id)
        if not order:
            return jsonify({'error': 'Order not found'}), 404
        
        if order.user_id != current_user_id:
            return jsonify({'error': 'Not authorized'}), 403
        
        if not order.paid:
            return jsonify({'error': 'Cannot refund unpaid order'}), 400
        
        # Check for existing pending refund
        existing = Refund.query.filter_by(order_id=order_id, status='pending').first()
        if existing:
            return jsonify({'error': 'Refund request already pending'}), 400
        
        # Default to full refund if amount not specified
        refund_amount = amount if amount else order.total_price
        
        refund = Refund(
            order_id=order_id,
            user_id=current_user_id,
            amount=refund_amount,
            reason=reason
        )
        
        db.session.add(refund)
        db.session.commit()
        
        return jsonify({
            'message': 'Refund request submitted',
            'refund_id': refund.id,
            'status': 'pending'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ==================== PAYSTACK PAYMENT (LEGACY) ====================


@marketplace_bp.route('/paystack/initialize_payment', methods=['POST'])
@jwt_required()
def initialize_payment():
    data = request.get_json()
    order_id = data.get('order_id')

    # Fetch the order from the database
    order = Order.query.filter_by(id=order_id).first()
    if not order:
        return jsonify({"error": "Order not found"}), 404

    # Simulate payment request to Paystack
    payload = {
        "email": order.email,
        "amount": int(order.total_price * 100),  # Paystack uses kobo (smallest currency unit)
        "reference": f"PAYSTACK_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    }

    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }

    response = requests.post("https://api.paystack.co/transaction/initialize", json=payload, headers=headers)
    if response.status_code != 200:
        return jsonify({"error": "Failed to initialize payment with Paystack"}), 500

    data = response.json()
    return jsonify({
        "authorization_url": data['data']['authorization_url'],
        "reference": data['data']['reference']
    }), 201


@marketplace_bp.route('/paystack/verify_payment', methods=['POST'])
@jwt_required()
def verify_payment():
    data = request.get_json()
    reference = data.get('reference')
    order_id = data.get('order_id')

    # Verify the payment with Paystack
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"
    }

    response = requests.get(f"https://api.paystack.co/transaction/verify/{reference}", headers=headers)
    if response.status_code != 200:
        return jsonify({"error": "Failed to verify payment with Paystack"}), 500

    payment_data = response.json()
    if payment_data['data']['status'] == 'success':
        # Update the order status
        order = Order.query.filter_by(id=order_id).first()
        if order:
            order.paid = True
            order.payment_reference = reference
            db.session.commit()
            return jsonify({"message": "Payment successful", "order_id": order.id}), 200
        else:
            return jsonify({"error": "Order not found"}), 404

    return jsonify({"error": "Payment not successful"}), 400


# ==================== INTASEND PAYMENT ====================

def generate_ticket_number(order_id: str) -> str:
    """Generate unique ticket number: CS-YYYYMMDD-XXXX"""
    date_part = datetime.utcnow().strftime('%Y%m%d')
    return f"CS-{date_part}-{order_id[-4:].upper()}"


@marketplace_bp.route('/intasend/initialize', methods=['POST'])
@jwt_required()
def intasend_initialize_payment():
    """
    Initialize IntaSend payment (M-Pesa STK Push or Checkout)
    
    Body:
        order_id: Order ID to pay for
        payment_method: 'mpesa' or 'checkout' (default: mpesa)
        redirect_url: Optional redirect URL after payment (for checkout)
    """
    try:
        from intasend_service import get_intasend_service, IntaSendError
        
        data = request.get_json()
        order_id = data.get('order_id')
        payment_method = data.get('payment_method', 'mpesa')
        redirect_url = data.get('redirect_url')
        
        order = Order.query.filter_by(id=order_id).first()
        if not order:
            return jsonify({"error": "Order not found"}), 404
        
        # Check for idempotency - don't reinitialize if already paid
        if order.paid:
            return jsonify({
                "error": "Order already paid",
                "order_id": order.id
            }), 400
        
        # Generate ticket number if not exists
        if not order.ticket_number:
            order.ticket_number = generate_ticket_number(order.id)
            db.session.commit()
        
        intasend = get_intasend_service()
        
        if payment_method == 'mpesa':
            result = intasend.initiate_mpesa_payment(
                phone_number=order.phone,
                amount=order.total_price,
                order_id=order.id,
                narrative=f"Payment for Order {order.ticket_number}",
                email=order.email,
                name=f"{order.first_name} {order.last_name}"
            )
            
            return jsonify({
                "message": "M-Pesa STK Push initiated",
                "invoice_id": result.get("invoice_id"),
                "checkout_id": result.get("checkout_id"),
                "order_id": order.id,
                "ticket_number": order.ticket_number
            }), 201
            
        else:  # checkout
            result = intasend.initiate_checkout(
                amount=order.total_price,
                order_id=order.id,
                email=order.email,
                phone_number=order.phone,
                first_name=order.first_name,
                last_name=order.last_name,
                redirect_url=redirect_url
            )
            
            return jsonify({
                "message": "Checkout session created",
                "checkout_url": result.get("url"),
                "checkout_id": result.get("checkout_id"),
                "order_id": order.id,
                "ticket_number": order.ticket_number
            }), 201
            
    except IntaSendError as e:
        return jsonify({"error": str(e), "details": e.response}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@marketplace_bp.route('/intasend/verify', methods=['POST'])
@jwt_required()
def intasend_verify_payment():
    """
    Verify IntaSend payment status
    
    Body:
        order_id: Order ID to verify
        invoice_id: IntaSend invoice ID (optional if we have payment_reference)
    """
    try:
        from intasend_service import get_intasend_service, IntaSendError
        
        data = request.get_json()
        order_id = data.get('order_id')
        invoice_id = data.get('invoice_id')
        
        order = Order.query.filter_by(id=order_id).first()
        if not order:
            return jsonify({"error": "Order not found"}), 404
        
        # Use stored payment reference if no invoice_id provided
        if not invoice_id and order.payment_reference:
            invoice_id = order.payment_reference
        
        if not invoice_id:
            return jsonify({"error": "Invoice ID required"}), 400
        
        intasend = get_intasend_service()
        result = intasend.get_payment_status(invoice_id)
        
        state = result.get("state", "").upper()
        
        if state == "COMPLETE":
            order.paid = True
            order.payment_reference = invoice_id
            order.status = 'confirmed'
            db.session.commit()
            
            return jsonify({
                "message": "Payment verified successfully",
                "order_id": order.id,
                "status": "paid",
                "ticket_number": order.ticket_number
            }), 200
        
        return jsonify({
            "message": f"Payment status: {state}",
            "order_id": order.id,
            "status": state.lower(),
            "invoice_id": invoice_id
        }), 200
        
    except IntaSendError as e:
        return jsonify({"error": str(e), "details": e.response}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@marketplace_bp.route('/intasend/webhook', methods=['POST'])
def intasend_webhook():
    """
    Handle IntaSend webhook notifications
    
    Called by IntaSend when payment status changes.
    Routes to appropriate handler based on api_ref prefix:
    - BADGE_ -> Badge purchase
    - Other -> Marketplace order
    """
    try:
        from intasend_service import get_intasend_service
        
        # Get raw payload for signature verification
        raw_payload = request.get_data(as_text=True)
        signature = request.headers.get('X-IntaSend-Signature', '')
        
        intasend = get_intasend_service()
        
        # Verify webhook signature (skip in sandbox mode)
        if not intasend.sandbox and signature:
            if not intasend.verify_webhook_signature(raw_payload, signature):
                return jsonify({"error": "Invalid signature"}), 401
        
        payload = request.get_json()
        event_data = intasend.parse_webhook_payload(payload)
        
        api_ref = event_data.get("api_ref", "")
        state = event_data.get("state", "").upper()
        invoice_id = event_data.get("invoice_id")
        
        print(f"[Webhook] Received: api_ref={api_ref}, state={state}, invoice_id={invoice_id}")
        
        # Route based on api_ref prefix
        if api_ref.startswith("BADGE_"):
            return _handle_badge_webhook(event_data)
        else:
            return _handle_order_webhook(event_data)
        
    except Exception as e:
        print(f"[Webhook] Error: {str(e)}")
        return jsonify({"error": str(e)}), 500


def _handle_badge_webhook(event_data):
    """Handle badge purchase webhook events"""
    from models import BadgeTransaction, UserBadge, Badge
    
    api_ref = event_data.get("api_ref", "")
    state = event_data.get("state", "").upper()
    invoice_id = event_data.get("invoice_id")
    
    print(f"[Badge Webhook] Processing: api_ref={api_ref}, state={state}")
    
    # Find the transaction by invoice_id first
    transaction = BadgeTransaction.query.filter_by(
        checkout_request_id=invoice_id
    ).first()
    
    if not transaction:
        # Try to find by parsing api_ref
        # Format: BADGE_{badge_id}_{user_id}_{timestamp} or BADGE_CARD_{badge_id}_{user_id}_{timestamp}
        parts = api_ref.split('_')
        if len(parts) >= 4:
            try:
                if parts[1] == 'CARD':
                    badge_id = int(parts[2])
                    user_id = int(parts[3])
                else:
                    badge_id = int(parts[1])
                    user_id = int(parts[2])
                
                transaction = BadgeTransaction.query.filter_by(
                    badge_id=badge_id,
                    user_id=user_id,
                    status='PENDING'
                ).order_by(BadgeTransaction.created_at.desc()).first()
            except (ValueError, IndexError):
                pass
    
    if not transaction:
        print(f"[Badge Webhook] Transaction not found for invoice_id={invoice_id}, api_ref={api_ref}")
        return jsonify({"success": True, "message": "Transaction not found, ignoring"}), 200
    
    if state == "COMPLETE":
        transaction.status = 'COMPLETED'
        transaction.completed_at = datetime.utcnow()
        transaction.mpesa_receipt_number = event_data.get('raw_response', {}).get('invoice', {}).get('mpesa_reference')
        
        # Grant badge to user
        _grant_badge_for_webhook(transaction.user_id, transaction.badge_id)
        print(f"[Badge Webhook] Badge granted to user {transaction.user_id}")
        
    elif state == "FAILED":
        transaction.status = 'FAILED'
        transaction.error_message = event_data.get('failed_reason', 'Payment failed')
        print(f"[Badge Webhook] Payment failed for transaction {transaction.id}")
    
    db.session.commit()
    return jsonify({"success": True, "message": f"Badge webhook processed: {state}"}), 200


def _grant_badge_for_webhook(user_id: int, badge_id: int):
    """Helper to grant a badge to a user (for webhook handler)"""
    from models import UserBadge
    
    # Check if user already has this badge
    existing = UserBadge.query.filter_by(user_id=user_id, badge_id=badge_id).first()
    if existing:
        return
    
    # Grant badge to user
    user_badge = UserBadge(
        user_id=user_id,
        badge_id=badge_id,
        is_displayed=True,
        display_order=0
    )
    
    # Adjust display order of existing badges
    existing_badges = UserBadge.query.filter_by(
        user_id=user_id,
        is_displayed=True
    ).all()
    
    for i, existing_badge in enumerate(existing_badges):
        existing_badge.display_order = i + 1
    
    db.session.add(user_badge)


def _handle_order_webhook(event_data):
    """Handle marketplace order webhook events"""
    order_id = event_data.get("api_ref")
    state = event_data.get("state", "").upper()
    invoice_id = event_data.get("invoice_id")
    
    if not order_id:
        return jsonify({"error": "No order reference"}), 400
    
    order = Order.query.filter_by(id=order_id).first()
    if not order:
        return jsonify({"error": "Order not found"}), 404
    
    # Update order based on payment state
    if state == "COMPLETE":
        order.paid = True
        order.payment_reference = invoice_id
        order.status = 'confirmed'
        
        # Send confirmation email via Resend API
        try:
            from email_service import get_email_service
            email_service = get_email_service()
            if email_service.is_configured():
                email_service.send_order_confirmation(order)
        except Exception as e:
            print(f"Failed to send email: {e}")
    elif state == "FAILED":
        order.status = 'payment_failed'
    
    db.session.commit()
    
    return jsonify({"message": f"Order webhook processed: {state}"}), 200


# Route to get products created by the logged-in user
@marketplace_bp.route('/my-products', methods=['GET'])
@jwt_required()
def get_my_products():
    current_user = get_jwt_identity()
    products = Products.query.filter_by(user_id=current_user).all()
    output = []
    for product in products:
        # Calculate the average rating for each product
        average_rating = db.session.query(func.avg(Reviews.rating)).filter(Reviews.product_id == product.id).scalar()
        if average_rating is None:
            average_rating = 0  # If there are no reviews, set average rating to 0
        else:
            average_rating = round(average_rating, 1)  # Round the average rating to one decimal place
            
        reviews = []
        for review in product.reviews:
            review_data = {
                'id': review.id,
                'text': review.text,
                'rating': review.rating,
                'username': review.user.username,  # Get the username of the user who posted the review
                'user_image_url': review.user.avatar if review.user.avatar else None  # Get the image data of the user who posted the review
            }
            reviews.append(review_data)
        
        # Include the contact information of the product
        contact_info = product.contact_info if product.contact_info else Users.query.filter_by(id=current_user).first().phone_no
        
        product_data = {
            'id': product.id,
            'title': product.title,
            'description': product.description,
            'price': product.price,
            'image_url': product.image_url if product.image_url else None, 
            'category': product.category,
            'contact_info': contact_info,  # Include the contact information in the response
            'average_rating': average_rating,
            'reviews': reviews
        }
        output.append(product_data)
    return jsonify({'my_products': output})

# Route to create a new product
@marketplace_bp.route('/add-product', methods=['POST'])
def add_product():
    data = request.form  # For handling non-file form data
    files = request.files.getlist('images')  # For handling multiple image files

    # Extract product base data
    title = data.get('title')
    description = data.get('description')
    contact_info = data.get('contact_info')
    price = data.get('price')  # Base price (for non-variation products)
    category = data.get('category')
    brand = data.get('brand')

    seller_id = data.get('seller_id')
    created_at = datetime.utcnow()
    updated_at = datetime.utcnow()

    # Create the base product
    try:
        new_product = Products(
            title=title,
            slug=Products.generate_slug(title),  # Generate SEO-friendly slug
            description=description,
            contact_info=contact_info,
            price=float(price) if price else None,  # Base price is optional if variations exist
            category=category,
            brand = brand,
            seller_id=int(seller_id),
            created_at=created_at,
            updated_at=updated_at
        )
        db.session.add(new_product)
        db.session.commit()  # Commit to get the product ID for variations/images

        # Handle product variations if they exist
        variations_data = request.form.getlist('variations[]')  # Expected format for variations

        if variations_data:
            # Process variations
            for variation_str in variations_data:
                # Each variation could be in the format: "Size:Large:25.00" (name:value:price)
                name, value, var_price = variation_str.split(":")
                product_variation = ProductVariation(
                    product_id=new_product.id,
                    variation_name=name,
                    variation_value=value,
                    price=float(var_price),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.session.add(product_variation)

        # Handle image upload to Cloudflare R2
        image_urls = []
        for file in files:
            if file:
                filename = secure_filename(file.filename)
                file_key = f"products/{new_product.id}/{filename}"  # Store under product folder by ID

                # Upload to R2
                s3_client.upload_fileobj(file, R2_BUCKET_NAME, file_key)

                # Get the public URL for the uploaded image
                image_url = f"{R2_ENDPOINT_URL}/{R2_BUCKET_NAME}/{file_key}"
                image_urls.append(image_url)

                # Store image URL in ProductImages
                product_image = ProductImages(
                    product_id=new_product.id,
                    url=image_url
                )
                db.session.add(product_image)

        db.session.commit()  # Commit images and variations to the database

        return jsonify({
            'message': 'Product added successfully',
            'product': {
                'id': new_product.id,
                'title': new_product.title,
                'description': new_product.description,
                'images': image_urls,
                'variations': variations_data if variations_data else "No variations"
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
# Route to create a product
@marketplace_bp.route('/create-product', methods=['POST'])
@jwt_required()
def create_product():
    current_user = get_jwt_identity()

    if request.is_json:
        data = request.get_json()
    else:
        data = {key: request.form[key] for key in request.form}

    image_file = request.files.get('image_url')

    # Handle R2 image upload
    image_key = None
    if image_file:
        image_key = f'product_images/{current_user}/{image_file.filename}'
        try:
            s3_client.upload_fileobj(image_file, R2_BUCKET_NAME, image_key)
        except Exception as e:
            return jsonify({'error': f"Failed to upload image: {str(e)}"}), 500

    # Use the uploaded image's R2 URL if image is provided
    r2_image_url = f"{IMAGE_PREFIX}/{image_key}" if image_key else None
    
    # Set the contact info
    contact_info = data.get('contact_info') or Users.query.filter_by(id=current_user).first().phone_no

    # Create the new product
    new_product = Products(
        title=data.get('title'),
        slug=Products.generate_slug(data.get('title')),  # Generate SEO-friendly slug
        description=data.get('description'),
        price=data.get('price'),
        image_url=r2_image_url,  # Use the R2 image URL
        category=data.get('category'),
        contact_info=contact_info,
        user_id=current_user
    )
    
    db.session.add(new_product)
    db.session.commit()
    return jsonify({'message': 'Product created successfully', 'slug': new_product.slug})

# Route to update a product
@marketplace_bp.route('/update-product/<int:product_id>', methods=['PUT'])
@jwt_required()
def update_product(product_id):
    current_user = get_jwt_identity()
    product = Products.query.filter_by(id=product_id).first()
    
    # Check if the product exists
    if not product:
        return jsonify({'message': 'Product not found'}), 404
    
    # Check if the current user is the owner of the product
    if product.user_id != current_user:
        return jsonify({'message': 'Unauthorized'}), 401
    
    data = request.form  # Handle form data for file uploads
    image_file = request.files.get('image_url')

    # Handle R2 image upload if a new image is provided
    image_key = None
    if image_file:
        image_key = f'product_images/{current_user}/{image_file.filename}'
        try:
            s3_client.upload_fileobj(image_file, R2_BUCKET_NAME, image_key)
        except Exception as e:
            return jsonify({'error': f"Failed to upload image: {str(e)}"}), 500

    # Use the uploaded image's R2 URL if image is provided
    r2_image_url = f"{IMAGE_PREFIX}/{image_key}" if image_key else product.image_url

    # Update product details
    product.title = data.get('title', product.title)
    product.description = data.get('description', product.description)
    product.price = data.get('price', product.price)
    product.category = data.get('category', product.category)
    product.contact_info = data.get('contact_info', product.contact_info)
    product.image_url = r2_image_url  # Update with the new image URL if applicable
    
    db.session.commit()
    return jsonify({'message': 'Product updated successfully'})
# Route to delete a product
@marketplace_bp.route('/delete-product/<int:product_id>', methods=['DELETE'])
@jwt_required()
def delete_product(product_id):
    current_user = get_jwt_identity()
    product = Products.query.filter_by(id=product_id).first()
    
    # Check if the product exists
    if not product:
        return jsonify({'message': 'Product not found'}), 404
    
    # Check if the current user is the owner of the product
    if product.user_id != current_user:
        return jsonify({'message': 'Unauthorized'}), 401
    
    db.session.delete(product)
    db.session.commit()
    return jsonify({'message': 'Product deleted successfully'})

def get_products_by_category(category):
    products = Products.query.filter_by(category=category).all()
    output = []
    for product in products:
        # Calculate the average rating for each product
        average_rating = db.session.query(func.avg(Reviews.rating)).filter(Reviews.product_id == product.id).scalar()
        if average_rating is None:
            average_rating = 0  # If there are no reviews, set average rating to 0
        else:
            average_rating = round(average_rating, 1)  # Round the average rating to one decimal place

        # Get reviews associated with the product
        reviews = [{
            'id': review.id,
            'text': review.text,
            'rating': review.rating,
            'username': review.user.username,
            'user_image_url':  review.user.avatar if review.user.avatar else None
        } for review in product.reviews]

        # Determine the contact information for the product
        if product.contact_info:
            contact_info = product.contact_info
        else:
            contact_info = product.user.phone_no

        # Include product data along with reviews and contact info
        product_data = {
            'id': product.id,
            'title': product.title,
            'description': product.description,
            'price': product.price,
            'image_url': product.image_url if product.image_url else None, 
            'category': product.category,
            'average_rating': average_rating,
            'reviews': reviews,
            'contact_info': contact_info
        }
        output.append(product_data)
    return output

@marketplace_bp.route('/marketplace/search', methods=['GET'])
def search_products():
    search_term = request.args.get('q', '')
    category_filter = request.args.get('category', None)

    # Perform the search query
    if category_filter:
        products = Products.query.filter(
            Products.category == category_filter,
            or_(
                Products.title.ilike(f'%{search_term}%'),
                Products.description.ilike(f'%{search_term}%')
            )
        ).all()
    else:
        products = Products.query.filter(
            or_(
                Products.title.ilike(f'%{search_term}%'),
                Products.description.ilike(f'%{search_term}%')
            )
        ).all()

    output = []
    for product in products:
        # Calculate the average rating for each product
        average_rating = db.session.query(func.avg(Reviews.rating)).filter(Reviews.product_id == product.id).scalar()
        if average_rating is None:
            average_rating = 0  # If there are no reviews, set average rating to 0
        else:
            average_rating = round(average_rating, 1)  # Round the average rating to one decimal place

        # Get reviews associated with the product
        reviews = [{
            'id': review.id,
            'text': review.text,
            'rating': review.rating,
            'username': review.user.username,
                            'user_image_url': review.user.avatar if review.user.avatar else None
        } for review in product.reviews]

        # Determine the contact information for the product
        if product.contact_info:
            contact_info = product.contact_info
        else:
            contact_info = product.user.phone_no

        # Include product data along with reviews and contact info
        product_data = {
            'id': product.id,
            'title': product.title,
            'description': product.description,
            'price': product.price,
            'image_url': product.image_url if product.image_url else None, 
            'category': product.category,
            'average_rating': average_rating,
            'reviews': reviews,
            'contact_info': contact_info
        }
        output.append(product_data)

    return jsonify({'products': output})

# Route to add a review and rating
@marketplace_bp.route('/product/<string:product_id>/review', methods=['POST'])
@jwt_required()
def add_review(product_id):
    current_user = get_jwt_identity()
    product = Products.query.get(product_id)
    
    if not product:
        return jsonify({'message': 'Product not found'}), 404
    
    data = request.get_json()
    review_text = data.get('text')
    rating = int(data.get('rating'))
    
    if not review_text:
        return jsonify({'message': 'Review text is required'}), 400
    if not rating:
        return jsonify({'message': 'Rating is required'}), 400
    # If rating is not between 0-5 return error: rating should be between 0 and 5
    if rating < 0 or rating > 5:
        return jsonify({'message': 'Rating should be between 0 and 5'}), 400

  
    new_review = Reviews(
        text=review_text,
        rating=rating,
        user_id=current_user,
        product_id=product_id
    )
    
    db.session.add(new_review)
    db.session.commit()
    
   
    
    return jsonify({'message': 'Review added successfully'}), 201


# Route to update a review
@marketplace_bp.route('/review/<int:review_id>', methods=['PUT'])
@jwt_required()
def update_review(review_id):
    current_user = get_jwt_identity()
    review = Reviews.query.get(review_id)

    if not review:
        return jsonify({'message': 'Review not found'}), 404

    if review.user_id != current_user:
        return jsonify({'message': 'Unauthorized to update this review'}), 403

    data = request.get_json()
    text = data.get('text')
    rating = data.get('rating')

    if not text:
        return jsonify({'message': 'Review text is required'}), 400
    if not rating:
        return jsonify({'message': 'Rating is required'}), 400

    review.text = text
    review.rating = rating
    db.session.commit()

    return jsonify({'message': 'Review updated successfully'}), 200


# Route to delete a review
@marketplace_bp.route('/review/<int:review_id>', methods=['DELETE'])
@jwt_required()
def delete_review(review_id):
    current_user = get_jwt_identity()
    review = Reviews.query.get(review_id)

    if not review:
        return jsonify({'message': 'Review not found'}), 404

    if review.user_id != current_user:
        return jsonify({'message': 'Unauthorized to delete this review'}), 403

    db.session.delete(review)
    db.session.commit()
    return jsonify({'message': 'Review deleted successfully'}), 200

@marketplace_bp.route('/product/<int:product_id>/reviews', methods=['GET'])
def get_reviews(product_id):
    product = Products.query.get(product_id)
    if not product:
        return jsonify({'message': 'Product not found'}), 404

    reviews = []
    for review in product.reviews:
        user = Users.query.get(review.user_id)
        if user:
            review_data = {
                'id': review.id,
                'text': review.text,
                'rating': review.rating,
                'username': user.username,
                'avatar':  user.avatar if user.avatar else None
            }
            reviews.append(review_data)

    return jsonify({'reviews': reviews})


# ==================== WISHLIST ENDPOINTS ====================

@marketplace_bp.route('/wishlist/toggle', methods=['POST'])
@jwt_required()
def toggle_wishlist():
    """Add or remove a product from user's wishlist"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        product_id = data.get('product_id')

        if not product_id:
            return jsonify({'error': 'Product ID is required'}), 400

        # Check if product exists
        product = Products.query.get(product_id)
        if not product:
            return jsonify({'error': 'Product not found'}), 404

        # Check if already in wishlist
        existing = Wishlists.query.filter_by(user_id=user_id, product_id=product_id).first()

        if existing:
            # Remove from wishlist
            db.session.delete(existing)
            db.session.commit()
            return jsonify({
                'message': 'Product removed from wishlist',
                'in_wishlist': False,
                'product_id': product_id
            }), 200
        else:
            # Add to wishlist
            wishlist_item = Wishlists(user_id=user_id, product_id=product_id)
            db.session.add(wishlist_item)
            db.session.commit()
            return jsonify({
                'message': 'Product added to wishlist',
                'in_wishlist': True,
                'product_id': product_id
            }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@marketplace_bp.route('/wishlist', methods=['GET'])
@jwt_required()
def get_wishlist():
    """Get all products in user's wishlist"""
    try:
        user_id = get_jwt_identity()
        
        wishlist_items = Wishlists.query.filter_by(user_id=user_id).all()
        
        product_ids = [item.product_id for item in wishlist_items]
        
        # Get full product details
        products_data = []
        for item in wishlist_items:
            product = item.product
            if product:
                products_data.append({
                    'id': product.id,
                    'slug': product.slug,
                    'title': product.title,
                    'price': product.price,
                    'images': [img.image_url for img in product.images],
                    'brand': product.brand,
                    'category': product.category,
                    'added_at': item.created_at.isoformat()
                })
        
        return jsonify({
            'wishlist': products_data,
            'product_ids': product_ids,
            'count': len(product_ids)
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@marketplace_bp.route('/wishlist/check/<string:product_id>', methods=['GET'])
@jwt_required()
def check_wishlist(product_id):
    """Check if a specific product is in user's wishlist"""
    try:
        user_id = get_jwt_identity()
        
        existing = Wishlists.query.filter_by(user_id=user_id, product_id=product_id).first()
        
        return jsonify({
            'in_wishlist': existing is not None,
            'product_id': product_id
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

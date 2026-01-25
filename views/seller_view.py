"""
Seller Dashboard API Endpoints
Provides seller-specific endpoints for managing products, orders, and analytics.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import (
    db, Seller, Products, Order, OrderItem, OrderStatusHistory,
    Reviews, Users, ProductVariation, ProductImages
)
from datetime import datetime
from sqlalchemy import func, or_
from functools import wraps
import os
import boto3
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import uuid

# Load environment variables
load_dotenv()

# R2 Configuration (same as yap_view.py)
R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID') or os.getenv('AWS_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY') or os.getenv('AWS_SECRET_ACCESS_KEY')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME')
R2_ENDPOINT_URL = os.getenv('R2_ENDPOINT_URL')
IMAGE_PREFIX = os.getenv('IMAGE_PREFIX')

# Initialize S3 client for R2
s3_client = None
if R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY:
    s3_client = boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY
    )

seller_bp = Blueprint('seller_bp', __name__)


def get_seller_or_403():
    """Helper to get current user's seller profile or raise 403"""
    user_id = get_jwt_identity()
    seller = Seller.query.filter_by(user_id=user_id).first()
    if not seller:
        return None
    return seller


def seller_required(f):
    """Decorator to require seller authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        seller = get_seller_or_403()
        if not seller:
            return jsonify({"error": "Seller account required"}), 403
        return f(seller, *args, **kwargs)
    return decorated_function


# ==================== PRODUCTS ====================

@seller_bp.route('/seller/products', methods=['GET'])
@jwt_required()
@seller_required
def get_seller_products(seller):
    """Get all products belonging to the authenticated seller"""
    try:
        products = Products.query.filter_by(seller_id=seller.id).all()
        
        result = []
        for product in products:
            result.append({
                'id': product.id,
                'title': product.title,
                'description': product.description,
                'price': product.price,
                'category': product.category,
                'brand': product.brand,
                'is_active': getattr(product, 'is_active', True),
                'status': getattr(product, 'status', 'active'),
                'total_sales': product.total_sales,
                'average_rating': product.average_rating(),
                'created_at': product.created_at.isoformat(),
                'updated_at': product.updated_at.isoformat(),
                'images': [{'id': img.id, 'url': img.image_url} for img in product.images],
                'variations': [
                    {
                        'id': v.id,
                        'name': v.variation_name,
                        'value': v.variation_value,
                        'price': v.price,
                        'stock': v.stock
                    } for v in product.variations
                ],
                'review_count': len(product.reviews)
            })
        
        return jsonify({
            'products': result,
            'count': len(result)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/seller/products/<product_id>', methods=['GET'])
@jwt_required()
@seller_required
def get_seller_product(seller, product_id):
    """Get a single product belonging to the seller"""
    try:
        product = Products.query.filter_by(id=product_id, seller_id=seller.id).first()
        if not product:
            return jsonify({"error": "Product not found"}), 404
        
        return jsonify({
            'id': product.id,
            'title': product.title,
            'slug': product.slug,
            'description': product.description,
            'price': product.price,
            'category': product.category,
            'brand': product.brand,
            'is_active': getattr(product, 'is_active', True),
            'total_sales': product.total_sales,
            'average_rating': product.average_rating(),
            'created_at': product.created_at.isoformat(),
            'updated_at': product.updated_at.isoformat(),
            'images': [{'id': img.id, 'url': img.image_url, 'variant_id': getattr(img, 'variant_id', None)} for img in product.images],
            'variations': [
                {
                    'id': v.id,
                    'name': v.variation_name,
                    'value': v.variation_value,
                    'price': v.price,
                    'stock': v.stock
                } for v in product.variations
            ],
            'review_count': len(product.reviews)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/seller/products', methods=['POST'])
@jwt_required()
@seller_required
def create_seller_product(seller):
    """
    Create a new product for the seller
    
    Body (JSON or FormData):
        title: Product title (required)
        description: Product description
        price: Base price
        category: Product category
        brand: Brand name
        variations: Array of {name, value, price, stock}
        images: Array of image files (if FormData)
    """
    try:
        # Handle both JSON and FormData
        if request.is_json:
            data = request.get_json()
            files = []
        else:
            data = {key: request.form.get(key) for key in request.form}
            files = request.files.getlist('images')
            # Parse JSON fields from FormData
            if 'variations' in data and isinstance(data['variations'], str):
                import json
                data['variations'] = json.loads(data['variations'])
        
        title = data.get('title')
        if not title:
            return jsonify({"error": "Product title required"}), 400
        
        # Create product
        product = Products(
            title=title,
            slug=Products.generate_slug(title),
            description=data.get('description', ''),
            price=float(data.get('price', 0)) if data.get('price') else None,
            category=data.get('category', ''),
            brand=data.get('brand', ''),
            seller_id=seller.id
        )
        db.session.add(product)
        db.session.flush()  # Get product ID
        
        # Handle variations
        variations = data.get('variations', [])
        for var in variations:
            variation = ProductVariation(
                product_id=product.id,
                variation_name=var.get('name', 'Size'),
                variation_value=var.get('value', ''),
                price=float(var.get('price', 0)) if var.get('price') else product.price,
                stock=int(var.get('stock', 0)) if var.get('stock') else 0
            )
            db.session.add(variation)
        
        # Handle image uploads to R2 using global s3_client
        print(f"[DEBUG] Files received: {len(files)} files")
        print(f"[DEBUG] s3_client initialized: {s3_client is not None}")
        print(f"[DEBUG] R2_BUCKET_NAME: {R2_BUCKET_NAME}")
        print(f"[DEBUG] IMAGE_PREFIX: {IMAGE_PREFIX}")
        
        image_urls = []
        if files and s3_client:
            try:
                for file in files:
                    if file and file.filename:
                        # Generate unique filename to avoid collisions
                        original_filename = secure_filename(file.filename)
                        unique_id = str(uuid.uuid4())[:8]
                        filename = f"{unique_id}_{original_filename}"
                        file_key = f"products/{product.id}/{filename}"
                        
                        print(f"[DEBUG] Uploading file: {file.filename} -> {file_key}")
                        
                        s3_client.upload_fileobj(file, R2_BUCKET_NAME, file_key)
                        image_url = f"{IMAGE_PREFIX}/{file_key}"
                        image_urls.append(image_url)
                        
                        print(f"[DEBUG] Uploaded successfully: {image_url}")
                        
                        product_image = ProductImages(
                            product_id=product.id,
                            image_url=image_url
                        )
                        db.session.add(product_image)
            except Exception as upload_error:
                print(f"[ERROR] R2 upload failed: {str(upload_error)}")
                # Continue without images rather than failing completely
        else:
            if not files:
                print("[DEBUG] No files received in request")
            if not s3_client:
                print("[DEBUG] s3_client not initialized - R2 credentials missing")
        
        db.session.commit()
        
        print(f"[DEBUG] Product created with {len(image_urls)} images")
        
        return jsonify({
            "message": "Product created successfully",
            "product": {
                "id": product.id,
                "title": product.title,
                "slug": product.slug,
                "images": image_urls,
                "variations_count": len(variations)
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"[ERROR] Product creation failed: {str(e)}")
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/seller/products/<product_id>', methods=['PATCH'])
@jwt_required()
@seller_required
def update_seller_product(seller, product_id):
    """
    Update an existing product
    
    Body:
        title, description, price, category, brand: Basic fields
        variations: Array of variations to update/add
        remove_variations: Array of variation IDs to remove
        remove_images: Array of image IDs to remove
    """
    try:
        product = Products.query.filter_by(id=product_id, seller_id=seller.id).first()
        if not product:
            return jsonify({"error": "Product not found"}), 404
        
        # Handle both JSON and FormData
        if request.is_json:
            data = request.get_json()
            files = []
        else:
            data = {key: request.form.get(key) for key in request.form}
            files = request.files.getlist('images')
            # Parse JSON fields
            for field in ['variations', 'remove_variations', 'remove_images']:
                if field in data and isinstance(data[field], str):
                    import json
                    data[field] = json.loads(data[field])
        
        # Update basic fields
        if 'title' in data:
            product.title = data['title']
        if 'description' in data:
            product.description = data['description']
        if 'price' in data:
            product.price = float(data['price']) if data['price'] else None
        if 'category' in data:
            product.category = data['category']
        if 'brand' in data:
            product.brand = data['brand']
        
        product.updated_at = datetime.utcnow()
        
        # Remove specified variations
        remove_var_ids = data.get('remove_variations', [])
        if remove_var_ids:
            ProductVariation.query.filter(
                ProductVariation.id.in_(remove_var_ids),
                ProductVariation.product_id == product.id
            ).delete(synchronize_session=False)
        
        # Update/add variations
        variations = data.get('variations', [])
        for var in variations:
            if var.get('id'):
                # Update existing
                existing = ProductVariation.query.filter_by(
                    id=var['id'], 
                    product_id=product.id
                ).first()
                if existing:
                    existing.variation_name = var.get('name', existing.variation_name)
                    existing.variation_value = var.get('value', existing.variation_value)
                    existing.price = float(var.get('price', existing.price)) if var.get('price') else existing.price
                    existing.stock = int(var.get('stock', existing.stock)) if var.get('stock') is not None else existing.stock
            else:
                # Add new
                new_var = ProductVariation(
                    product_id=product.id,
                    variation_name=var.get('name', 'Size'),
                    variation_value=var.get('value', ''),
                    price=float(var.get('price', 0)) if var.get('price') else product.price,
                    stock=int(var.get('stock', 0)) if var.get('stock') else 0
                )
                db.session.add(new_var)
        
        # Remove specified images
        remove_img_ids = data.get('remove_images', [])
        if remove_img_ids:
            ProductImages.query.filter(
                ProductImages.id.in_(remove_img_ids),
                ProductImages.product_id == product.id
            ).delete(synchronize_session=False)
        
        # Handle new image uploads
        if files:
            import os
            from werkzeug.utils import secure_filename
            import boto3
            
            R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID') or os.getenv('AWS_ACCESS_KEY_ID')
            R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY') or os.getenv('AWS_SECRET_ACCESS_KEY')
            R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME')
            R2_ENDPOINT_URL = os.getenv('R2_ENDPOINT_URL')
            IMAGE_PREFIX = os.getenv('IMAGE_PREFIX')
            
            if R2_ACCESS_KEY_ID:
                s3_client = boto3.client(
                    's3',
                    endpoint_url=R2_ENDPOINT_URL,
                    aws_access_key_id=R2_ACCESS_KEY_ID,
                    aws_secret_access_key=R2_SECRET_ACCESS_KEY
                )
                
                for file in files:
                    if file and file.filename:
                        filename = secure_filename(file.filename)
                        file_key = f"products/{product.id}/{filename}"
                        s3_client.upload_fileobj(file, R2_BUCKET_NAME, file_key)
                        image_url = f"{IMAGE_PREFIX}/{file_key}"
                        
                        product_image = ProductImages(
                            product_id=product.id,
                            image_url=image_url
                        )
                        db.session.add(product_image)
        
        db.session.commit()
        
        return jsonify({
            "message": "Product updated successfully",
            "product_id": product.id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/seller/products/<product_id>', methods=['DELETE'])
@jwt_required()
@seller_required
def delete_seller_product(seller, product_id):
    """Delete a product (hard delete)"""
    try:
        product = Products.query.filter_by(id=product_id, seller_id=seller.id).first()
        if not product:
            return jsonify({"error": "Product not found"}), 404
        
        # Delete associated data
        ProductVariation.query.filter_by(product_id=product.id).delete()
        ProductImages.query.filter_by(product_id=product.id).delete()
        Reviews.query.filter_by(product_id=product.id).delete()
        
        db.session.delete(product)
        db.session.commit()
        
        return jsonify({
            "message": "Product deleted successfully",
            "product_id": product_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/seller/products/<product_id>/stock', methods=['PATCH'])
@jwt_required()
@seller_required
def update_product_stock(seller, product_id):
    """
    Update stock for product variations
    
    Body:
        variations: Array of {id, stock}
    """
    try:
        product = Products.query.filter_by(id=product_id, seller_id=seller.id).first()
        if not product:
            return jsonify({"error": "Product not found"}), 404
        
        data = request.get_json()
        variations = data.get('variations', [])
        
        updated = 0
        for var in variations:
            if var.get('id') and var.get('stock') is not None:
                existing = ProductVariation.query.filter_by(
                    id=var['id'],
                    product_id=product.id
                ).first()
                if existing:
                    existing.stock = int(var['stock'])
                    updated += 1
        
        db.session.commit()
        
        return jsonify({
            "message": f"Updated stock for {updated} variations",
            "product_id": product.id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/seller/products/<product_id>/toggle', methods=['PATCH'])
@jwt_required()
@seller_required
def toggle_product_status(seller, product_id):
    """Toggle product active/inactive status"""
    try:
        product = Products.query.filter_by(id=product_id, seller_id=seller.id).first()
        if not product:
            return jsonify({"error": "Product not found"}), 404
        
        data = request.get_json() or {}
        
        # Update is_active flag
        if 'is_active' in data:
            product.is_active = data['is_active']
        else:
            # Toggle if no value provided
            product.is_active = not product.is_active
        
        db.session.commit()
        
        return jsonify({
            "message": f"Product {'activated' if product.is_active else 'deactivated'}",
            "product_id": product.id,
            "is_active": product.is_active,
            "status": product.status
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/seller/products/<product_id>/status', methods=['PATCH'])
@jwt_required()
@seller_required
def update_product_status(seller, product_id):
    """
    Update product status
    
    Body:
        status: One of 'draft', 'active', 'archived', 'sold_out'
    """
    try:
        product = Products.query.filter_by(id=product_id, seller_id=seller.id).first()
        if not product:
            return jsonify({"error": "Product not found"}), 404
        
        data = request.get_json() or {}
        new_status = data.get('status')
        
        valid_statuses = ['draft', 'active', 'archived', 'sold_out']
        if new_status not in valid_statuses:
            return jsonify({
                "error": f"Invalid status. Must be one of: {valid_statuses}"
            }), 400
        
        old_status = product.status
        product.status = new_status
        
        # Auto-update is_active based on status
        product.is_active = new_status == 'active'
        
        product.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            "message": f"Product status changed from '{old_status}' to '{new_status}'",
            "product_id": product.id,
            "status": product.status,
            "is_active": product.is_active
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== ORDERS ====================

@seller_bp.route('/seller/orders', methods=['GET'])
@jwt_required()
@seller_required
def get_seller_orders(seller):
    """Get all orders containing the seller's products"""
    try:
        # Query orders that have items from this seller
        orders_query = db.session.query(Order).join(OrderItem).filter(
            OrderItem.seller_id == seller.id
        ).distinct()
        
        # Optional status filter
        status = request.args.get('status')
        if status:
            orders_query = orders_query.filter(Order.status == status)
        
        # Pagination
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        orders = orders_query.order_by(Order.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        result = []
        for order in orders.items:
            # Filter order items to only show seller's products
            seller_items = [item for item in order.order_items if item.seller_id == seller.id]
            
            result.append({
                'id': order.id,
                'ticket_number': order.ticket_number,
                'customer': {
                    'first_name': order.first_name,
                    'last_name': order.last_name,
                    'email': order.email,
                    'phone': order.phone,
                    'address': order.address
                },
                'status': order.status,
                'payment_mode': order.payment_mode,
                'paid': order.paid,
                'tracking_number': order.tracking_number,
                'shipping_carrier': order.shipping_carrier,
                'items': [
                    {
                        'id': item.id,
                        'product_id': item.product_id,
                        'product_title': item.product.title if item.product else None,
                        'quantity': item.quantity,
                        'price': item.price_at_purchase or (item.product.price if item.product else 0),
                        'total': item.total_item_price()
                    } for item in seller_items
                ],
                'seller_total': sum(item.total_item_price() for item in seller_items),
                'created_at': order.created_at.isoformat(),
                'updated_at': order.updated_at.isoformat() if order.updated_at else None
            })
        
        return jsonify({
            'orders': result,
            'pagination': {
                'page': orders.page,
                'per_page': orders.per_page,
                'total_pages': orders.pages,
                'total_items': orders.total
            }
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/seller/orders/<order_id>', methods=['GET'])
@jwt_required()
@seller_required
def get_seller_order_detail(seller, order_id):
    """Get detailed order information for seller"""
    try:
        order = Order.query.get(order_id)
        if not order:
            return jsonify({"error": "Order not found"}), 404
        
        # Check if seller has items in this order
        seller_items = [item for item in order.order_items if item.seller_id == seller.id]
        if not seller_items:
            return jsonify({"error": "No items from your store in this order"}), 403
        
        # Get status history
        history = [{
            'status': h.status,
            'changed_by': h.user.username if h.user else None,
            'notes': h.notes,
            'created_at': h.created_at.isoformat()
        } for h in order.status_history]
        
        return jsonify({
            'id': order.id,
            'ticket_number': order.ticket_number,
            'customer': {
                'first_name': order.first_name,
                'last_name': order.last_name,
                'email': order.email,
                'phone': order.phone,
                'address': order.address
            },
            'status': order.status,
            'payment_mode': order.payment_mode,
            'paid': order.paid,
            'payment_reference': order.payment_reference,
            'tracking_number': order.tracking_number,
            'shipping_carrier': order.shipping_carrier,
            'items': [
                {
                    'id': item.id,
                    'product_id': item.product_id,
                    'product_title': item.product.title if item.product else None,
                    'product_image': item.product.images[0].image_url if item.product and item.product.images else None,
                    'variation': {
                        'name': item.product_variation.variation_name,
                        'value': item.product_variation.variation_value
                    } if item.product_variation else None,
                    'quantity': item.quantity,
                    'price': item.price_at_purchase or (item.product.price if item.product else 0),
                    'total': item.total_item_price()
                } for item in seller_items
            ],
            'seller_total': sum(item.total_item_price() for item in seller_items),
            'status_history': history,
            'created_at': order.created_at.isoformat(),
            'updated_at': order.updated_at.isoformat() if order.updated_at else None
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/seller/orders/<order_id>/status', methods=['PATCH'])
@jwt_required()
@seller_required
def update_order_status(seller, order_id):
    """
    Update order status with idempotency protection.
    Headers:
        X-Idempotency-Key: Unique key to prevent duplicate updates
    Body:
        status: New status (processing, shipped, delivered)
        tracking_number: Optional tracking number
        shipping_carrier: Optional shipping carrier
        notes: Optional notes about the status change
    """
    try:
        # Check idempotency key
        idempotency_key = request.headers.get('X-Idempotency-Key')
        if idempotency_key:
            # Check if this update was already processed
            existing = OrderStatusHistory.query.filter(
                OrderStatusHistory.order_id == order_id,
                OrderStatusHistory.notes.contains(f"[idempotency:{idempotency_key}]")
            ).first()
            if existing:
                return jsonify({
                    "message": "Status update already processed",
                    "status": existing.status,
                    "idempotent": True
                }), 200
        
        order = Order.query.get(order_id)
        if not order:
            return jsonify({"error": "Order not found"}), 404
        
        # Verify seller has items in this order
        seller_items = [item for item in order.order_items if item.seller_id == seller.id]
        if not seller_items:
            return jsonify({"error": "No items from your store in this order"}), 403
        
        data = request.get_json()
        new_status = data.get('status')
        
        # Valid status transitions
        valid_statuses = ['pending', 'confirmed', 'processing', 'shipped', 'delivered', 'cancelled']
        if new_status not in valid_statuses:
            return jsonify({"error": f"Invalid status. Must be one of: {valid_statuses}"}), 400
        
        old_status = order.status
        
        # Update order
        order.status = new_status
        
        if data.get('tracking_number'):
            order.tracking_number = data['tracking_number']
        if data.get('shipping_carrier'):
            order.shipping_carrier = data['shipping_carrier']
        
        # Create status history entry
        notes = data.get('notes', '')
        if idempotency_key:
            notes = f"{notes} [idempotency:{idempotency_key}]"
        
        user_id = get_jwt_identity()
        history_entry = OrderStatusHistory(
            order_id=order.id,
            status=new_status,
            changed_by=user_id,
            notes=notes
        )
        db.session.add(history_entry)
        
        db.session.commit()
        
        return jsonify({
            "message": f"Order status updated from {old_status} to {new_status}",
            "order_id": order.id,
            "old_status": old_status,
            "new_status": new_status,
            "tracking_number": order.tracking_number,
            "shipping_carrier": order.shipping_carrier
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== REVIEWS ====================

@seller_bp.route('/seller/reviews', methods=['GET'])
@jwt_required()
@seller_required
def get_seller_reviews(seller):
    """Get all reviews for seller's products"""
    try:
        # Get all product IDs for this seller
        product_ids = [p.id for p in seller.products]
        
        reviews = Reviews.query.filter(Reviews.product_id.in_(product_ids)).order_by(
            Reviews.created_at.desc()
        ).all()
        
        result = [{
            'id': r.id,
            'product_id': r.product_id,
            'product_title': r.product.title if r.product else None,
            'rating': r.rating,
            'text': r.text,
            'user': {
                'username': r.user.username if r.user else None,
                'avatar': r.user.avatar if r.user else None
            },
            'created_at': r.created_at.isoformat()
        } for r in reviews]
        
        # Calculate rating distribution
        rating_dist = {}
        for r in reviews:
            rating_dist[int(r.rating)] = rating_dist.get(int(r.rating), 0) + 1
        
        avg_rating = sum(r.rating for r in reviews) / len(reviews) if reviews else 0
        
        return jsonify({
            'reviews': result,
            'count': len(result),
            'average_rating': round(avg_rating, 2),
            'rating_distribution': rating_dist
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== ANALYTICS ====================

@seller_bp.route('/seller/analytics', methods=['GET'])
@jwt_required()
@seller_required
def get_seller_analytics(seller):
    """Get sales analytics for the seller"""
    try:
        # Total revenue from seller's items
        revenue_query = db.session.query(
            func.sum(OrderItem.price_at_purchase * OrderItem.quantity)
        ).filter(
            OrderItem.seller_id == seller.id
        ).join(Order).filter(
            Order.paid == True
        ).scalar() or 0
        
        # Total orders containing seller's products
        total_orders = db.session.query(func.count(Order.id.distinct())).join(
            OrderItem
        ).filter(
            OrderItem.seller_id == seller.id
        ).scalar() or 0
        
        # Total products
        total_products = len(seller.products)
        
        # Average rating
        product_ids = [p.id for p in seller.products]
        avg_rating = db.session.query(func.avg(Reviews.rating)).filter(
            Reviews.product_id.in_(product_ids)
        ).scalar() or 0
        
        # Top selling products
        top_products = db.session.query(
            Products.id,
            Products.title,
            func.sum(OrderItem.quantity).label('units_sold')
        ).join(OrderItem).filter(
            Products.seller_id == seller.id
        ).group_by(Products.id).order_by(
            func.sum(OrderItem.quantity).desc()
        ).limit(5).all()
        
        return jsonify({
            'total_revenue': float(revenue_query),
            'total_orders': total_orders,
            'total_products': total_products,
            'average_rating': round(float(avg_rating), 2),
            'top_products': [
                {'id': p.id, 'title': p.title, 'units_sold': int(p.units_sold)}
                for p in top_products
            ]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/seller/sales-over-time', methods=['GET'])
@jwt_required()
@seller_required
def get_sales_over_time(seller):
    """Get daily sales data for charts"""
    from datetime import timedelta
    
    try:
        period = request.args.get('period', '30d')  # 7d, 30d, 90d
        
        # Parse period
        days = int(period.replace('d', ''))
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get daily sales grouped by date
        daily_sales = db.session.query(
            func.date(Order.created_at).label('date'),
            func.sum(OrderItem.price_at_purchase * OrderItem.quantity).label('revenue'),
            func.count(Order.id.distinct()).label('order_count')
        ).join(OrderItem).filter(
            OrderItem.seller_id == seller.id,
            Order.paid == True,
            Order.created_at >= start_date
        ).group_by(
            func.date(Order.created_at)
        ).order_by(
            func.date(Order.created_at)
        ).all()
        
        # Fill in missing dates with zero values
        sales_by_date = {str(s.date): {'revenue': float(s.revenue), 'orders': s.order_count} for s in daily_sales}
        
        result = []
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            data = sales_by_date.get(date_str, {'revenue': 0, 'orders': 0})
            result.append({
                'date': date_str,
                'revenue': data['revenue'],
                'orders': data['orders']
            })
            current_date += timedelta(days=1)
        
        return jsonify({
            'period': period,
            'data': result,
            'total_revenue': sum(d['revenue'] for d in result),
            'total_orders': sum(d['orders'] for d in result)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/seller/dashboard-summary', methods=['GET'])
@jwt_required()
@seller_required
def get_dashboard_summary(seller):
    """Consolidated dashboard data in single API call"""
    from datetime import timedelta
    
    try:
        # Get analytics
        revenue = db.session.query(
            func.sum(OrderItem.price_at_purchase * OrderItem.quantity)
        ).filter(
            OrderItem.seller_id == seller.id
        ).join(Order).filter(
            Order.paid == True
        ).scalar() or 0
        
        total_orders = db.session.query(func.count(Order.id.distinct())).join(
            OrderItem
        ).filter(
            OrderItem.seller_id == seller.id
        ).scalar() or 0
        
        total_products = len(seller.products)
        
        # Average rating
        product_ids = [p.id for p in seller.products]
        avg_rating = 0
        if product_ids:
            avg_rating = db.session.query(func.avg(Reviews.rating)).filter(
                Reviews.product_id.in_(product_ids)
            ).scalar() or 0
        
        # Recent orders (last 5)
        recent_orders = db.session.query(Order).join(OrderItem).filter(
            OrderItem.seller_id == seller.id
        ).order_by(Order.created_at.desc()).limit(5).all()
        
        # Top products by sales
        top_products = db.session.query(
            Products.id,
            Products.title,
            func.sum(OrderItem.quantity).label('units_sold'),
            func.sum(OrderItem.price_at_purchase * OrderItem.quantity).label('revenue')
        ).join(OrderItem).filter(
            Products.seller_id == seller.id
        ).group_by(Products.id).order_by(
            func.sum(OrderItem.quantity).desc()
        ).limit(5).all()
        
        # 7-day sales for mini chart
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        weekly_sales = db.session.query(
            func.date(Order.created_at).label('date'),
            func.sum(OrderItem.price_at_purchase * OrderItem.quantity).label('revenue')
        ).join(OrderItem).filter(
            OrderItem.seller_id == seller.id,
            Order.paid == True,
            Order.created_at >= seven_days_ago
        ).group_by(func.date(Order.created_at)).all()
        
        return jsonify({
            'stats': {
                'total_revenue': float(revenue),
                'total_orders': total_orders,
                'total_products': total_products,
                'average_rating': round(float(avg_rating), 2)
            },
            'recent_orders': [
                {
                    'id': o.id,
                    'customer': o.user.display_name or o.user.username if o.user else 'Guest',
                    'total': float(o.total_amount),
                    'status': o.status,
                    'created_at': o.created_at.isoformat()
                }
                for o in recent_orders
            ],
            'top_products': [
                {
                    'id': p.id,
                    'title': p.title,
                    'units_sold': int(p.units_sold),
                    'revenue': float(p.revenue)
                }
                for p in top_products
            ],
            'weekly_sales': [
                {'date': str(s.date), 'revenue': float(s.revenue)}
                for s in weekly_sales
            ],
            'has_data': total_products > 0 or total_orders > 0
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== PAYOUTS ====================


@seller_bp.route('/seller/earnings', methods=['GET'])
@jwt_required()
@seller_required
def get_seller_earnings(seller):
    """Get seller earnings summary and payout history"""
    try:
        from models import SellerPayout
        
        # Get pending earnings
        pending_earnings = seller.pending_earnings()
        
        # Get payout history
        payouts = SellerPayout.query.filter_by(seller_id=seller.id).order_by(
            SellerPayout.created_at.desc()
        ).limit(20).all()
        
        payout_history = [{
            'id': p.id,
            'amount': p.amount,
            'status': p.status,
            'phone_number': p.phone_number,
            'created_at': p.created_at.isoformat(),
            'processed_at': p.processed_at.isoformat() if p.processed_at else None,
            'failed_reason': p.failed_reason
        } for p in payouts]
        
        # Total paid out
        total_paid = sum(p.amount for p in payouts if p.status == 'completed')
        
        return jsonify({
            'pending_earnings': pending_earnings,
            'total_paid_out': total_paid,
            'payout_history': payout_history
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/seller/payouts/request', methods=['POST'])
@jwt_required()
@seller_required  
def request_payout(seller):
    """
    Request a payout of pending earnings
    
    Body:
        amount: Amount to withdraw (must be <= pending earnings)
        phone_number: M-Pesa phone number (optional, uses seller.phone_no if not provided)
    """
    try:
        from models import SellerPayout
        
        data = request.get_json()
        amount = data.get('amount')
        phone_number = data.get('phone_number') or seller.phone_no
        
        if not amount or amount <= 0:
            return jsonify({"error": "Valid amount required"}), 400
        
        if not phone_number:
            return jsonify({"error": "Phone number required for payout"}), 400
        
        # Check pending earnings
        pending = seller.pending_earnings()
        if amount > pending:
            return jsonify({
                "error": f"Insufficient balance. Available: KES {pending:,.2f}"
            }), 400
        
        # Create payout request
        payout = SellerPayout(
            seller_id=seller.id,
            amount=amount,
            phone_number=phone_number,
            status='pending'
        )
        db.session.add(payout)
        db.session.commit()
        
        return jsonify({
            "message": "Payout request submitted",
            "payout_id": payout.id,
            "amount": amount,
            "status": "pending"
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== ADMIN VERIFICATION ====================

def admin_required(f):
    """Decorator to require super admin authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = get_jwt_identity()
        user = Users.query.get(user_id)
        if not user or not getattr(user, 'is_superadmin', False):
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated_function


@seller_bp.route('/admin/verifications', methods=['GET'])
@jwt_required()
@admin_required
def get_verification_requests():
    """Get all pending seller verification requests"""
    try:
        # Get unverified sellers
        pending_sellers = Seller.query.filter_by(is_verified=False).all()
        
        result = [{
            'seller_id': s.id,
            'display_name': s.display_name,
            'user_id': s.user_id,
            'about': s.about,
            'phone_no': s.phone_no,
            'product_count': s.product_count(),
            'created_at': s.created_at.isoformat()
        } for s in pending_sellers]
        
        return jsonify({
            'pending_verifications': result,
            'count': len(result)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/admin/verifications/<seller_id>/approve', methods=['POST'])
@jwt_required()
@admin_required
def approve_verification(seller_id):
    """Approve a seller verification request"""
    try:
        seller = Seller.query.get(seller_id)
        if not seller:
            return jsonify({"error": "Seller not found"}), 404
        
        seller.is_verified = True
        db.session.commit()
        
        return jsonify({
            "message": f"Seller {seller.display_name} has been verified",
            "seller_id": seller.id,
            "is_verified": True
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/admin/verifications/<seller_id>/reject', methods=['POST'])
@jwt_required()
@admin_required
def reject_verification(seller_id):
    """Reject a seller verification request"""
    try:
        data = request.get_json() or {}
        reason = data.get('reason', 'Verification rejected')
        
        seller = Seller.query.get(seller_id)
        if not seller:
            return jsonify({"error": "Seller not found"}), 404
        
        # Keep is_verified as False, optionally store rejection reason
        # For now, just return the rejection status
        
        return jsonify({
            "message": f"Verification rejected for {seller.display_name}",
            "seller_id": seller.id,
            "reason": reason
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/admin/payouts/pending', methods=['GET'])
@jwt_required()
@admin_required
def get_pending_payouts():
    """Get all pending payout requests for admin approval"""
    try:
        from models import SellerPayout
        
        pending = SellerPayout.query.filter_by(status='pending').order_by(
            SellerPayout.created_at.asc()
        ).all()
        
        result = [{
            'id': p.id,
            'seller_id': p.seller_id,
            'seller_name': p.seller.display_name if p.seller else None,
            'amount': p.amount,
            'phone_number': p.phone_number,
            'created_at': p.created_at.isoformat()
        } for p in pending]
        
        return jsonify({
            'pending_payouts': result,
            'count': len(result),
            'total_amount': sum(p.amount for p in pending)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/admin/payouts/<payout_id>/process', methods=['POST'])
@jwt_required()
@admin_required
def process_payout(payout_id):
    """Process a pending payout request via IntaSend"""
    try:
        from models import SellerPayout
        from intasend_service import get_intasend_service, IntaSendError
        
        payout = SellerPayout.query.get(payout_id)
        if not payout:
            return jsonify({"error": "Payout not found"}), 404
        
        if payout.status != 'pending':
            return jsonify({"error": f"Payout already {payout.status}"}), 400
        
        # Mark as processing
        payout.status = 'processing'
        db.session.commit()
        
        try:
            intasend = get_intasend_service()
            result = intasend.send_money([{
                'account': payout.phone_number,
                'amount': payout.amount,
                'narrative': f'CampoSocial seller payout - {payout.seller.display_name}',
                'name': payout.seller.display_name
            }])
            
            payout.intasend_tracking_id = result.get('tracking_id')
            payout.status = 'completed'
            payout.processed_at = datetime.utcnow()
            db.session.commit()
            
            return jsonify({
                "message": "Payout processed successfully",
                "payout_id": payout.id,
                "tracking_id": result.get('tracking_id'),
                "status": "completed"
            }), 200
            
        except IntaSendError as e:
            payout.status = 'failed'
            payout.failed_reason = str(e)
            db.session.commit()
            return jsonify({"error": f"Payment failed: {str(e)}"}), 500
            
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== DISCOUNTS ====================

@seller_bp.route('/seller/discounts', methods=['GET'])
@jwt_required()
@seller_required
def get_seller_discounts(seller):
    """Get all discount codes for the seller"""
    try:
        from models import Discount
        
        discounts = Discount.query.filter_by(seller_id=seller.id).order_by(
            Discount.created_at.desc()
        ).all()
        
        result = [{
            'id': d.id,
            'code': d.code,
            'discount_type': d.discount_type,
            'value': d.value,
            'max_uses': d.max_uses,
            'current_uses': d.current_uses,
            'min_order_amount': d.min_order_amount,
            'max_discount_amount': d.max_discount_amount,
            'starts_at': d.starts_at.isoformat() if d.starts_at else None,
            'expires_at': d.expires_at.isoformat() if d.expires_at else None,
            'is_active': d.is_active,
            'is_valid': d.is_valid(),
            'created_at': d.created_at.isoformat()
        } for d in discounts]
        
        return jsonify({
            'discounts': result,
            'count': len(result)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/seller/discounts', methods=['POST'])
@jwt_required()
@seller_required
def create_discount(seller):
    """Create a new discount code"""
    try:
        from models import Discount
        
        data = request.get_json()
        
        # Validate required fields
        code = data.get('code', '').upper().strip()
        if not code:
            return jsonify({"error": "Discount code required"}), 400
        
        # Check if code already exists
        existing = Discount.query.filter_by(code=code).first()
        if existing:
            return jsonify({"error": "Discount code already exists"}), 400
        
        discount = Discount(
            seller_id=seller.id,
            code=code,
            discount_type=data.get('discount_type', 'percentage'),
            value=data.get('value', 10),
            max_uses=data.get('max_uses'),
            max_uses_per_user=data.get('max_uses_per_user', 1),
            min_order_amount=data.get('min_order_amount', 0),
            max_discount_amount=data.get('max_discount_amount'),
            starts_at=datetime.fromisoformat(data['starts_at']) if data.get('starts_at') else None,
            expires_at=datetime.fromisoformat(data['expires_at']) if data.get('expires_at') else None,
            is_active=data.get('is_active', True)
        )
        
        db.session.add(discount)
        db.session.commit()
        
        return jsonify({
            "message": "Discount created successfully",
            "discount_id": discount.id,
            "code": discount.code
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/seller/discounts/<discount_id>', methods=['PATCH'])
@jwt_required()
@seller_required
def update_discount(seller, discount_id):
    """Update a discount code"""
    try:
        from models import Discount
        
        discount = Discount.query.filter_by(id=discount_id, seller_id=seller.id).first()
        if not discount:
            return jsonify({"error": "Discount not found"}), 404
        
        data = request.get_json()
        
        if 'value' in data:
            discount.value = data['value']
        if 'max_uses' in data:
            discount.max_uses = data['max_uses']
        if 'min_order_amount' in data:
            discount.min_order_amount = data['min_order_amount']
        if 'max_discount_amount' in data:
            discount.max_discount_amount = data['max_discount_amount']
        if 'is_active' in data:
            discount.is_active = data['is_active']
        if 'expires_at' in data:
            discount.expires_at = datetime.fromisoformat(data['expires_at']) if data['expires_at'] else None
        
        db.session.commit()
        
        return jsonify({
            "message": "Discount updated successfully",
            "discount_id": discount.id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/seller/discounts/<discount_id>', methods=['DELETE'])
@jwt_required()
@seller_required
def delete_discount(seller, discount_id):
    """Delete a discount code"""
    try:
        from models import Discount
        
        discount = Discount.query.filter_by(id=discount_id, seller_id=seller.id).first()
        if not discount:
            return jsonify({"error": "Discount not found"}), 404
        
        db.session.delete(discount)
        db.session.commit()
        
        return jsonify({"message": "Discount deleted successfully"}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== REVIEW REPLIES ====================

@seller_bp.route('/seller/reviews/<review_id>/reply', methods=['POST'])
@jwt_required()
@seller_required
def reply_to_review(seller, review_id):
    """Reply to a review"""
    try:
        from models import ReviewReply
        
        review = Reviews.query.get(review_id)
        if not review:
            return jsonify({"error": "Review not found"}), 404
        
        # Verify review is for seller's product
        product = Products.query.get(review.product_id)
        if not product or product.seller_id != seller.id:
            return jsonify({"error": "Cannot reply to reviews for other sellers' products"}), 403
        
        data = request.get_json()
        text = data.get('text', '').strip()
        
        if not text:
            return jsonify({"error": "Reply text required"}), 400
        
        # Check if reply already exists
        existing = ReviewReply.query.filter_by(review_id=review_id, seller_id=seller.id).first()
        if existing:
            # Update existing reply
            existing.text = text
            existing.updated_at = datetime.utcnow()
            db.session.commit()
            return jsonify({
                "message": "Reply updated",
                "reply_id": existing.id
            }), 200
        
        # Create new reply
        reply = ReviewReply(
            review_id=review_id,
            seller_id=seller.id,
            text=text
        )
        db.session.add(reply)
        db.session.commit()
        
        return jsonify({
            "message": "Reply added successfully",
            "reply_id": reply.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== REFUNDS ====================

@seller_bp.route('/seller/refunds', methods=['GET'])
@jwt_required()
@seller_required
def get_seller_refunds(seller):
    """Get refund requests for seller's orders"""
    try:
        from models import Refund
        
        # Get orders containing seller's products
        seller_order_ids = db.session.query(Order.id).join(OrderItem).filter(
            OrderItem.seller_id == seller.id
        ).distinct().all()
        seller_order_ids = [o.id for o in seller_order_ids]
        
        refunds = Refund.query.filter(Refund.order_id.in_(seller_order_ids)).order_by(
            Refund.created_at.desc()
        ).all()
        
        result = [{
            'id': r.id,
            'order_id': r.order_id,
            'amount': r.amount,
            'reason': r.reason,
            'status': r.status,
            'created_at': r.created_at.isoformat(),
            'reviewed_at': r.reviewed_at.isoformat() if r.reviewed_at else None
        } for r in refunds]
        
        return jsonify({
            'refunds': result,
            'count': len(result)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/admin/refunds/pending', methods=['GET'])
@jwt_required()
@admin_required
def get_pending_refunds():
    """Get all pending refund requests"""
    try:
        from models import Refund
        
        pending = Refund.query.filter_by(status='pending').order_by(
            Refund.created_at.asc()
        ).all()
        
        result = [{
            'id': r.id,
            'order_id': r.order_id,
            'user_id': r.user_id,
            'amount': r.amount,
            'reason': r.reason,
            'created_at': r.created_at.isoformat()
        } for r in pending]
        
        return jsonify({
            'pending_refunds': result,
            'count': len(result)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/admin/refunds/<refund_id>/approve', methods=['POST'])
@jwt_required()
@admin_required
def approve_refund(refund_id):
    """Approve a refund request"""
    try:
        from models import Refund
        from intasend_service import get_intasend_service
        
        refund = Refund.query.get(refund_id)
        if not refund:
            return jsonify({"error": "Refund not found"}), 404
        
        if refund.status != 'pending':
            return jsonify({"error": f"Refund already {refund.status}"}), 400
        
        user_id = get_jwt_identity()
        refund.status = 'approved'
        refund.reviewed_by = user_id
        refund.reviewed_at = datetime.utcnow()
        
        # Process refund via IntaSend if order was paid
        order = refund.order
        if order.paid and order.payment_reference:
            try:
                intasend = get_intasend_service()
                result = intasend.initiate_refund(
                    invoice_id=order.payment_reference,
                    amount=refund.amount,
                    reason=refund.reason
                )
                refund.intasend_refund_id = result.get('refund_id')
                refund.status = 'processed'
                refund.processed_at = datetime.utcnow()
            except Exception as e:
                # Log but don't fail - manual refund may be needed
                refund.status = 'approved'  # Keep as approved for manual processing
        
        db.session.commit()
        
        return jsonify({
            "message": "Refund approved",
            "refund_id": refund.id,
            "status": refund.status
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/admin/refunds/<refund_id>/reject', methods=['POST'])
@jwt_required()
@admin_required
def reject_refund(refund_id):
    """Reject a refund request"""
    try:
        from models import Refund
        
        refund = Refund.query.get(refund_id)
        if not refund:
            return jsonify({"error": "Refund not found"}), 404
        
        data = request.get_json() or {}
        
        user_id = get_jwt_identity()
        refund.status = 'rejected'
        refund.reviewed_by = user_id
        refund.reviewed_at = datetime.utcnow()
        refund.rejection_reason = data.get('reason', 'Request rejected')
        
        db.session.commit()
        
        return jsonify({
            "message": "Refund rejected",
            "refund_id": refund.id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== SELLER VERIFICATION ====================

@seller_bp.route('/seller/verification/request', methods=['POST'])
@jwt_required()
@seller_required
def request_verification(seller):
    """Submit a verification request"""
    try:
        from models import SellerVerificationRequest
        
        # Check for existing pending request
        existing = SellerVerificationRequest.query.filter_by(
            seller_id=seller.id,
            status='pending'
        ).first()
        
        if existing:
            return jsonify({"error": "You already have a pending verification request"}), 400
        
        if seller.is_verified:
            return jsonify({"error": "Already verified"}), 400
        
        data = request.get_json()
        
        verification = SellerVerificationRequest(
            seller_id=seller.id,
            id_document_url=data.get('id_document_url'),
            business_document_url=data.get('business_document_url'),
            additional_notes=data.get('additional_notes')
        )
        
        db.session.add(verification)
        db.session.commit()
        
        return jsonify({
            "message": "Verification request submitted",
            "request_id": verification.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@seller_bp.route('/seller/verification/status', methods=['GET'])
@jwt_required()
@seller_required
def get_verification_status(seller):
    """Get seller's verification status"""
    try:
        from models import SellerVerificationRequest
        
        latest = SellerVerificationRequest.query.filter_by(
            seller_id=seller.id
        ).order_by(SellerVerificationRequest.created_at.desc()).first()
        
        return jsonify({
            'is_verified': seller.is_verified,
            'latest_request': {
                'id': latest.id,
                'status': latest.status,
                'rejection_reason': latest.rejection_reason,
                'created_at': latest.created_at.isoformat(),
                'reviewed_at': latest.reviewed_at.isoformat() if latest.reviewed_at else None
            } if latest else None
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

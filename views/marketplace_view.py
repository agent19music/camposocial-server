from models import db, Products, Wishlists, Reviews, Users, ProductVariation, ProductImages, Order,Seller,Cart, CartItem, OrderItem
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


s3_client = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT_URL,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY
)   

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
@jwt_required()  # Requires JWT authentication
def add_seller():
    try:
        data = request.form  # Form data
        user_id = get_jwt_identity()  # Get the current user
        about=data['about'],
        phone_no=data['phone'],
        avatar=data['avatar_url', None] 

        print(about+phone_no+avatar)


        # Check if the user is already a seller
        existing_seller = Seller.query.filter_by(user_id=user_id).first()
        if existing_seller:
            return jsonify({"error": "User is already a seller"}), 400


        # Handle avatar file upload to R2 if provided
        if 'avatar_file' in request.files:
            file = request.files['avatar_file']
            if file:
                # Generate a unique file name using UUID and secure it
                filename = secure_filename(file.filename)
                
                # Upload file to Cloudflare R2 bucket
                s3_client.upload_fileobj(
                    file,
                    R2_BUCKET_NAME,
                    filename,
                    ExtraArgs={"ACL": "public-read"}  # Public read access
                )
                
                # Construct the public URL for the avatar
                avatar_url = f"{IMAGE_PREFIX}/{filename}"

        # If a custom avatar URL is provided instead of a file
        if 'avatar_url' in data :
            avatar_url = data['avatar_url', None]

        print(avatar_url)    

        # Create the seller profile in the database
        new_seller = Seller(
            display_name=data['display_name'],
            about=data['about'],
            phone_no=data['phone'],
            user_id=user_id,
            avatar=avatar_url  # Save the avatar URL (either from R2 or provided URL)
        )

        db.session.add(new_seller)
        db.session.commit()

        return jsonify({"message": "Seller profile created successfully"}), 201

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

# Route to get a specific product by id
@marketplace_bp.route('/products/<string:product_id>', methods=['GET'])
def get_single_product(product_id):
    try:
        # Fetch the product by ID
        product = Products.query.filter_by(id=product_id).first()
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
            'average_rating': product.average_rating(),
            "title": product.title,
            "description": product.description,
            "price": product.price,
            "category": product.category,
            "contact_info": product.contact_info,
            "brand": product.brand,
            "created_at": product.created_at,
            "updated_at": product.updated_at,
            "seller_id": product.seller_id,
            "sellerName": product.seller.display_name,
            "sellerAvatar" : product.seller.avatar,
            "sellerIsVerified": product.seller.is_verified,
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
        return jsonify({'message': 'Cart not found'}), 404

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

        if not all([first_name, last_name, email, phone, address]):
            return jsonify({'error': 'Missing customer details'}), 400

        # Fetch the user's cart
        cart = Cart.query.filter_by(user_id=current_user_id).first()
        if not cart or not cart.cart_items:
            return jsonify({'error': 'Cart is empty'}), 400

        # Create the order
        order = Order(
            user_id=current_user_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            address=address,
            total_price=total_price  # Calculate total price from cart
        )
        db.session.add(order)
        db.session.commit()  # Commit to get the order ID

        # Copy cart items to order items
        for cart_item in cart.cart_items:
            order_item = OrderItem(
                order_id=order.id,
                product_id=cart_item.product_id,
                quantity=cart_item.quantity 
            )
            db.session.add(order_item)

        # Clear the cart after successful order creation
        cart.cart_items.clear()
        db.session.commit()

        return jsonify({'message': 'Order created successfully', 'order_id': order.id}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Failed to create order', 'details': str(e)}), 500

    
@marketplace_bp.route('/get_latest_order_id', methods=['GET'])
@jwt_required()
def get_latest_order_id():
    # Extract user identity (user_id) from the JWT
    user_id = get_jwt_identity()

    # Get the latest order (the most recent one) for the logged-in user
    latest_order = Order.query.filter_by(user_id=user_id).order_by(Order.created_at.desc()).first()

    if latest_order:
        return jsonify({'order_id': latest_order.id}), 200
    else:
        return jsonify({'message': 'No orders found for this user'}), 404

@marketplace_bp.route('/paystack/initialize_payment', methods=['POST'])
@jwt_required()
def initialize_payment():
    data = request.get_json()
    print(data)
    order_id = data['order_id']
    # Fetch the order from the database
    order =Order.query.filter_by(id=order_id).first()
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
                'user_image_url': review.user.image_url if review.user.image_url else None  # Get the image data of the user who posted the review
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
        description=data.get('description'),
        price=data.get('price'),
        image_url=r2_image_url,  # Use the R2 image URL
        category=data.get('category'),
        contact_info=contact_info,
        user_id=current_user
    )
    
    db.session.add(new_product)
    db.session.commit()
    return jsonify({'message': 'Product created successfully'})

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
            'user_image_url':  review.user.image_url if review.user.image_url else None
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
            'user_image_url': review.user.image_url if review.user.image_url else None
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
                'avatar':  review.avatar if review.avatar else None
            }
            reviews.append(review_data)

    return jsonify({'reviews': reviews})



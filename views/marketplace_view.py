from models import db, Products, Wishlists, Reviews, Users, ProductVariation, ProductImages, Order,Seller
from flask import request, jsonify, Blueprint,make_response
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import or_, func
from datetime import datetime
import base64
import os
import boto3
from dotenv import load_dotenv
load_dotenv()

marketplace_bp = Blueprint('marketplace_bp', __name__)

R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME')
R2_ENDPOINT_URL = os.getenv('R2_ENDPOINT_URL')
IMAGE_PREFIX = os.getenv('IMAGE_PREFIX')


s3_client = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT_URL,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY
)    

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
@marketplace_bp.route('/seller/<string:seller_id>', methods=['GET'])
def get_seller(seller_id):
    try:
        seller = Seller.query.filter_by(id=seller_id).first()
        if not seller:
            return jsonify({"error": "Seller not found"}), 404

        # Calculating total products
        total_products = seller.product_count()

        # Calculating total sales
        total_sales = seller.total_sales()

        # Calculate average rating across all products
        all_reviews = []
        for product in seller.products:
            all_reviews.extend([review.rating for review in product.reviews])

        average_rating = sum(all_reviews) / len(all_reviews) if all_reviews else None

        seller_data = {
            "display_name": seller.display_name,
            "is_verified": seller.is_verified,
            "about": seller.about,
            "avatar": seller.avatar,
            "total_products": total_products,
            "total_sales": total_sales,
            "average_rating": average_rating,
        }

        return jsonify(seller_data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500    
# Route to get a specific product by id
@marketplace_bp.route('/product/<int:product_id>', methods=['GET'])
def get_product(product_id):
    product = Products.query.filter_by(id=product_id).first()
    if not product:
        return jsonify({'message': 'Product not found'}), 404
    
    # Calculate the average rating for the product
    average_rating = db.session.query(func.avg(Reviews.rating)).filter(Reviews.product_id == product.id).scalar()
    if average_rating is None:
        average_rating = 0  # If there are no reviews, set average rating to 0
    else:
        average_rating = round(average_rating, 1)
                
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
    contact_info = product.contact_info if product.contact_info else product.user.phone_no
    
    return jsonify({'product': {
        'id': product.id, 
        'username': product.user.last_name,
        'contact_info': contact_info,  # Include the contact information in the response
        'title': product.title, 
        'description': product.description, 
        'price': product.price,
        'image_url':product.image_url if product.image_url else None, 
        'category': product.category,
        'average_rating': average_rating,  # Include the average rating in the response
        'reviews': reviews
    }})

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
@marketplace_bp.route('/product/<int:product_id>/review', methods=['POST'])
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
    
    # Return the details of the newly added review in the response
    review_details = {
        'id': new_review.id,
        'text': new_review.text,
        'rating': new_review.rating,
        'user_id': new_review.user_id,
        'product_id': new_review.product_id
    }
    
    return jsonify({'message': 'Review added successfully', 'review': review_details}), 201


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
                'userImage':  review.user.image_url if review.user.image_url else None
            }
            reviews.append(review_data)

    return jsonify({'reviews': reviews})



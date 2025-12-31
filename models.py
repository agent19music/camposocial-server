from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData, CheckConstraint
from datetime import datetime
# from sqlalchemy_serializer import SerializerMixin  # Temporarily disabled
from sqlalchemy.orm import validates
from cuid import cuid
import re

# Placeholder class to avoid errors
class SerializerMixin:
    pass

# Define metadata with a naming convention for foreign keys
metadata = MetaData(naming_convention={
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
})

db = SQLAlchemy(metadata=metadata)

class Users(db.Model, SerializerMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(255), nullable=True)  # Made nullable for OAuth
    last_name = db.Column(db.String(255), nullable=True)   # Made nullable for OAuth
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=True)     # Made nullable for OAuth-only users
    phone_no = db.Column(db.String(20), nullable=True)
    category = db.Column(db.String(100), nullable=True)     # Made nullable for OAuth completion
    avatar = db.Column(db.String(255))  # Store the URL of the image
    display_name = db.Column(db.String(100))
    bio = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    public_key = db.Column(db.Text, nullable=True)
    yap_header_img = db.Column(db.String(255), nullable=True)

    # OAuth-specific fields
    oauth_provider = db.Column(db.String(50), nullable=True)  # 'google', 'github', 'twitter'
    oauth_id = db.Column(db.String(255), nullable=True)       # Provider-specific user ID
    is_oauth_user = db.Column(db.Boolean, default=False)      # Flag for OAuth users
    profile_completed = db.Column(db.Boolean, default=False)  # Track profile completion
    
    # Email verification fields (for manual signup)
    email_verified = db.Column(db.Boolean, default=False)     # True if email is verified
    verification_code = db.Column(db.String(6), nullable=True)  # 6-digit OTP
    verification_code_expires = db.Column(db.DateTime, nullable=True)  # OTP expiry time
    
    # Admin role
    is_superadmin = db.Column(db.Boolean, default=False)      # Super admin access
    
    # Notification settings
    notify_push = db.Column(db.Boolean, default=True)          # Push notifications enabled
    notify_email = db.Column(db.Boolean, default=True)         # Email notifications enabled
    notify_messages = db.Column(db.Boolean, default=True)      # Message notifications enabled
    
    # Privacy settings
    who_can_tag = db.Column(db.String(20), default='everyone') # 'everyone', 'followers', 'nobody'
    is_private = db.Column(db.Boolean, default=False)          # Private account
    
    events = db.relationship('Events', backref='user', lazy=True)
    comments_on_events = db.relationship('Comment_events', backref='user', lazy=True)
    reviews = db.relationship('Reviews', backref='user', lazy=True)

    yaps = db.relationship('Yap', backref='user', lazy=True)
    replies = db.relationship('Reply', backref='user', lazy=True)
    likes = db.relationship('Like', backref='user', lazy=True)
    following = db.relationship('Follow', foreign_keys='Follow.follower_id', backref='follower', lazy=True)
    followers = db.relationship('Follow', foreign_keys='Follow.following_id', backref='following', lazy=True)

    messages = db.relationship('Message', backref='author', lazy=True)
    reactions = db.relationship('Reaction', backref='user', lazy=True)
    user_badges = db.relationship('UserBadge', backref='user', lazy=True)
    badge_transactions = db.relationship('BadgeTransaction', backref='user', lazy=True)

    # Method to get all reviews belonging to a user
    def get_reviews(self):
        return self.reviews

    # Method to calculate the average rating given by the user across all reviews
    def average_review_rating(self):
        if len(self.reviews) == 0:
            return None
        return sum([review.rating for review in self.reviews]) / len(self.reviews)
    
    @validates('username')
    def validate_username(self, key, username):
        if not re.match(r'^[A-Za-z0-9_]+$', username or ''):
            raise AssertionError('The username can only contain letters, numbers, or underscores')
        return username

    @validates('email')
    def validate_email(self, key, email):
        # For OAuth users, we allow any valid email format
        if '@' not in email or '.' not in email.split('@')[1]:
            raise AssertionError('Invalid email format')
        return email
    
    @staticmethod
    def get_suggested_users_for_follow(current_user_id, limit=10):
        """Get suggested users to follow based on various criteria"""
        from sqlalchemy import func, or_
        from datetime import datetime, timedelta
        
        # Get users that the current user already follows
        following_ids = [f.following_id for f in Follow.query.filter_by(follower_id=current_user_id).all()]
        following_ids.append(current_user_id)  # Exclude self
        
        # Get mutual connections (users followed by people the current user follows)
        mutual_connections = db.session.query(
            Follow.following_id,
            func.count(Follow.follower_id).label('mutual_count')
        ).filter(
            Follow.follower_id.in_(following_ids),
            ~Follow.following_id.in_(following_ids)
        ).group_by(Follow.following_id).order_by(
            func.count(Follow.follower_id).desc()
        ).limit(limit * 2).all()
        
        # Get popular users (users with most followers who aren't already followed)
        popular_users = db.session.query(
            Users.id,
            func.count(Follow.follower_id).label('follower_count')
        ).outerjoin(Follow, Follow.following_id == Users.id
        ).filter(
            ~Users.id.in_(following_ids)
        ).group_by(Users.id).order_by(
            func.count(Follow.follower_id).desc()
        ).limit(limit * 2).all()
        
        # Get active users (users who posted recently)
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        active_users = db.session.query(
            Users.id,
            func.count(Yap.id).label('recent_yaps')
        ).outerjoin(Yap, Yap.user_id == Users.id
        ).filter(
            ~Users.id.in_(following_ids),
            or_(Yap.created_at >= seven_days_ago, Yap.id.is_(None))
        ).group_by(Users.id).order_by(
            func.count(Yap.id).desc()
        ).limit(limit * 2).all()
        
        # Combine and score the suggestions
        suggestions = {}
        
        # Add mutual connections with high weight
        for user_id, mutual_count in mutual_connections:
            suggestions[user_id] = {
                'user_id': user_id,
                'score': mutual_count * 3,  # High weight for mutual connections
                'reason': 'mutual_connections'
            }
        
        # Add popular users with medium weight
        for user_id, follower_count in popular_users:
            if user_id in suggestions:
                suggestions[user_id]['score'] += follower_count * 2
                suggestions[user_id]['reason'] = 'popular_and_mutual'
            else:
                suggestions[user_id] = {
                    'user_id': user_id,
                    'score': follower_count * 2,
                    'reason': 'popular'
                }
        
        # Add active users with medium weight
        for user_id, recent_yaps in active_users:
            if user_id in suggestions:
                suggestions[user_id]['score'] += recent_yaps * 1
            else:
                suggestions[user_id] = {
                    'user_id': user_id,
                    'score': recent_yaps * 1,
                    'reason': 'active'
                }
        
        # Sort by score and return user IDs
        sorted_suggestions = sorted(suggestions.values(), key=lambda x: x['score'], reverse=True)[:limit]
        return [s['user_id'] for s in sorted_suggestions]

class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    encrypted_content = db.Column(db.Text, nullable=False)  # Store the encrypted message (ciphertext)
    nonce = db.Column(db.String(64), nullable=True)  # Base64-encoded nonce for NaCl box decryption
    is_deleted = db.Column(db.Boolean, default=False)
    is_encrypted = db.Column(db.Boolean, default=True)  # Track if message is encrypted
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign Keys
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    conversation_id = db.Column(db.String, db.ForeignKey('conversations.id'), nullable=False)
    reply_to_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=True)
    
    # Relationships
    conversation = db.relationship('Conversation', backref='messages')
    reactions = db.relationship('Reaction', backref='message', lazy=True)
    media_items = db.relationship('MessageMedia', backref='message', lazy=True, cascade='all, delete-orphan')


class OfflineNotification(db.Model):
    __tablename__ = 'offline_notifications'

    id = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    payload = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    delivered_at = db.Column(db.DateTime, nullable=True)
    type = db.Column(db.String(50), nullable=False)

    recipient = db.relationship('Users', backref='offline_notifications')


class MessageMedia(db.Model):
    __tablename__ = 'message_media'

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=False)
    file_id = db.Column(db.String(64), nullable=False)
    url = db.Column(db.String(512), nullable=False)
    media_type = db.Column(db.String(20), nullable=False)  # image, video, document, audio
    file_metadata = db.Column(db.JSON, nullable=True)  # Renamed from 'metadata' (reserved by SQLAlchemy)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class Reaction(db.Model):
    __tablename__ = 'reactions'
    id = db.Column(db.Integer, primary_key=True)
    reaction_type = db.Column(db.String(20), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign Keys
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Unique constraint on (user_id, message_id)
    __table_args__ = (
        db.UniqueConstraint('user_id', 'message_id', name='unique_user_reaction'),
    )



class Events(db.Model, SerializerMixin):
    __tablename__ = 'events'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    title = db.Column(db.String(255))
    description = db.Column(db.String(255))
    image_url = db.Column(db.String(255))  # Store the URL of the image
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    date_of_event = db.Column(db.DateTime)
    entry_fee = db.Column(db.String)
    category = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    comments = db.relationship('Comment_events', backref='event', lazy=True, cascade='all, delete-orphan')
    ticket_groups = db.relationship('EventTicketGroup', backref='event', lazy=True, cascade='all, delete-orphan')


class EventTicketGroup(db.Model, SerializerMixin):
    __tablename__ = 'event_ticket_groups'

    id = db.Column(db.String, primary_key=True, default=cuid)
    event_id = db.Column(db.String, db.ForeignKey('events.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    tickets_per_group = db.Column(db.Integer, nullable=False, default=1)
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
class Products(db.Model, SerializerMixin):
    __tablename__ = 'products'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    title = db.Column(db.String(255))
    slug = db.Column(db.String(300), unique=True, nullable=True, index=True)  # SEO-friendly URL slug
    description = db.Column(db.String(255))
    contact_info = db.Column(db.String(20), nullable=True)
    brand = db.Column(db.String(155), nullable=True)
    price = db.Column(db.Float)
    category = db.Column(db.String(50))
    
    # Product status: draft, active, archived, sold_out
    status = db.Column(db.String(20), default='active', index=True)
    is_active = db.Column(db.Boolean, default=True, index=True)  # Quick toggle for visibility
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    seller_id = db.Column(db.String, db.ForeignKey('sellers.id'))
    
    @staticmethod
    def generate_slug(title: str) -> str:
        """
        Generate a unique, SEO-friendly slug from product title.
        Format: slugified-title-{6-char-random-suffix}
        Example: "Floral Cupcakes (6 Pack)" -> "floral-cupcakes-6-pack-a3x9k2"
        
        The random suffix ensures uniqueness without database lookups.
        """
        import re
        import secrets
        
        # Slugify the title
        slug_base = title.lower().strip()
        # Remove special characters except spaces and hyphens
        slug_base = re.sub(r'[^\w\s-]', '', slug_base)
        # Replace spaces with hyphens
        slug_base = re.sub(r'[\s_]+', '-', slug_base)
        # Remove consecutive hyphens
        slug_base = re.sub(r'-+', '-', slug_base)
        # Trim hyphens from ends
        slug_base = slug_base.strip('-')
        # Limit base length to keep URLs reasonable
        slug_base = slug_base[:80]
        
        # Add random suffix for uniqueness (6 chars = 36^6 = 2.1 billion combinations)
        suffix = secrets.token_urlsafe(4)[:6].lower()
        
        return f"{slug_base}-{suffix}"

    # Other relationships
    reviews = db.relationship('Reviews', backref='product', lazy=True)
    images = db.relationship('ProductImages', backref='product', lazy=True)
    variations = db.relationship('ProductVariation', back_populates='product', lazy=True)  # Adding relationship for variations
    
    # Relationships for cart and order integration
    cart_items = db.relationship('CartItem', back_populates='product', lazy=True, cascade='all, delete-orphan')
    order_items = db.relationship('OrderItem', backref='product', lazy=True, cascade='all, delete-orphan')

    total_sales = db.Column(db.Integer, default=0)  
    # Method to get the average rating of the product
    def average_rating(self):
        if len(self.reviews) == 0:
            return None
        return sum([review.rating for review in self.reviews]) / len(self.reviews)
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'contact_info': self.contact_info,
            'brand': self.brand,
            'price': self.price,
            'category': self.category,
            'created_at': self.created_at.isoformat(),  # Format datetime
            'updated_at': self.updated_at.isoformat(),  # Format datetime
            'seller_id': self.seller_id
        }

class ProductImages(db.Model):
    __tablename__ = 'product_images'
    
    id = db.Column(db.Integer, primary_key=True)
    image_url = db.Column(db.String(255), nullable=False)
    product_id = db.Column(db.String, db.ForeignKey('products.id'))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class ProductVariation(db.Model, SerializerMixin):
    __tablename__ = 'product_variations'

    id = db.Column(db.String, primary_key=True, default=cuid)
    product_id = db.Column(db.String, db.ForeignKey('products.id'), nullable=False)
    variation_name = db.Column(db.String(100))  # Example: Size, Color, etc.
    variation_value = db.Column(db.String(100))  # Example: "Large", "Red", etc.
    price = db.Column(db.Float)  # Price specific to this variation
    stock = db.Column(db.Integer, default=0)  # Stock count for the variation

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship back to the product
    product = db.relationship('Products', back_populates='variations')  # Ensure bidirectional relationship

class Seller(db.Model):
    __tablename__ = 'sellers'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    display_name = db.Column(db.String(255), nullable=False)
    is_verified = db.Column(db.Boolean, default=False)
    about = db.Column(db.Text, nullable=True)
    avatar = db.Column(db.String(255), nullable=True)  # URL for the avatar
    phone_no = db.Column(db.String(15), nullable=True)  # Phone number for payouts
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True)  # Each seller corresponds to a user

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)  
    products = db.relationship('Products', backref='seller', lazy=True)
    payouts = db.relationship('SellerPayout', backref='seller', lazy=True)


    # Method to get total sales across seller's products
    def total_sales(self):
        return sum([product.total_sales for product in self.products])

    # Method to count the number of products the seller has
    def product_count(self):
        return len(self.products)
    
    # Method to get total earnings (not yet paid out)
    def pending_earnings(self):
        from sqlalchemy import func
        paid_out = db.session.query(func.sum(SellerPayout.amount)).filter(
            SellerPayout.seller_id == self.id,
            SellerPayout.status == 'completed'
        ).scalar() or 0
        
        total_earned = db.session.query(func.sum(OrderItem.price_at_purchase * OrderItem.quantity)).filter(
            OrderItem.seller_id == self.id
        ).join(Order).filter(Order.paid == True).scalar() or 0
        
        return float(total_earned) - float(paid_out)


class SellerPayout(db.Model):
    """Track seller payout requests and IntaSend disbursements"""
    __tablename__ = 'seller_payouts'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    seller_id = db.Column(db.String, db.ForeignKey('sellers.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    
    # Payout status: pending, processing, completed, failed
    status = db.Column(db.String(20), default='pending')
    
    # IntaSend tracking
    intasend_tracking_id = db.Column(db.String(100), nullable=True)
    intasend_transaction_id = db.Column(db.String(100), nullable=True)
    
    # Payout destination
    phone_number = db.Column(db.String(15), nullable=True)  # M-Pesa number
    
    # Metadata
    notes = db.Column(db.Text, nullable=True)
    failed_reason = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)


# Discount codes for sellers
class Discount(db.Model):
    __tablename__ = 'discounts'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    seller_id = db.Column(db.String, db.ForeignKey('sellers.id'), nullable=True)  # Null = global discount
    code = db.Column(db.String(50), unique=True, nullable=False)
    
    # Discount type: percentage or fixed
    discount_type = db.Column(db.String(20), default='percentage')  # percentage, fixed
    value = db.Column(db.Float, nullable=False)  # Percentage (0-100) or fixed amount
    
    # Usage limits
    max_uses = db.Column(db.Integer, nullable=True)  # Null = unlimited
    current_uses = db.Column(db.Integer, default=0)
    max_uses_per_user = db.Column(db.Integer, default=1)
    
    # Minimum order amount
    min_order_amount = db.Column(db.Float, default=0)
    max_discount_amount = db.Column(db.Float, nullable=True)  # Cap for percentage discounts
    
    # Validity period
    starts_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    seller = db.relationship('Seller', backref='discounts', lazy=True)
    
    def is_valid(self):
        """Check if discount code is currently valid"""
        now = datetime.utcnow()
        if not self.is_active:
            return False
        if self.max_uses and self.current_uses >= self.max_uses:
            return False
        if self.starts_at and now < self.starts_at:
            return False
        if self.expires_at and now > self.expires_at:
            return False
        return True
    
    def calculate_discount(self, order_total):
        """Calculate discount amount for given order total"""
        if order_total < self.min_order_amount:
            return 0
        
        if self.discount_type == 'percentage':
            discount = order_total * (self.value / 100)
            if self.max_discount_amount:
                discount = min(discount, self.max_discount_amount)
        else:  # fixed
            discount = min(self.value, order_total)
        
        return discount


# Refund requests
class Refund(db.Model):
    __tablename__ = 'refunds'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    order_id = db.Column(db.String, db.ForeignKey('orders.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Refund details
    amount = db.Column(db.Float, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    
    # Status: pending, approved, rejected, processed
    status = db.Column(db.String(20), default='pending')
    
    # Processing
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    
    # IntaSend refund tracking
    intasend_refund_id = db.Column(db.String(100), nullable=True)
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    order = db.relationship('Order', backref='refunds', lazy=True)
    user = db.relationship('Users', foreign_keys=[user_id], backref='refund_requests', lazy=True)
    reviewer = db.relationship('Users', foreign_keys=[reviewed_by], backref='reviewed_refunds', lazy=True)


# Review replies from sellers
class ReviewReply(db.Model):
    __tablename__ = 'review_replies'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    review_id = db.Column(db.String, db.ForeignKey('reviews.id'), nullable=False)
    seller_id = db.Column(db.String, db.ForeignKey('sellers.id'), nullable=False)
    
    text = db.Column(db.Text, nullable=False)
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    review = db.relationship('Reviews', backref='replies', lazy=True)
    seller = db.relationship('Seller', backref='review_replies', lazy=True)


# Seller verification requests
class SellerVerificationRequest(db.Model):
    __tablename__ = 'seller_verification_requests'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    seller_id = db.Column(db.String, db.ForeignKey('sellers.id'), nullable=False)
    
    # Verification documents
    id_document_url = db.Column(db.String(500), nullable=True)
    business_document_url = db.Column(db.String(500), nullable=True)
    additional_notes = db.Column(db.Text, nullable=True)
    
    # Status: pending, approved, rejected
    status = db.Column(db.String(20), default='pending')
    
    # Review
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    seller = db.relationship('Seller', backref='verification_requests', lazy=True)
    reviewer = db.relationship('Users', backref='reviewed_verifications', lazy=True)


class Cart(db.Model):
    __tablename__ = 'cart'
    
    id = db.Column(db.String, primary_key=True, default=cuid)  # Unique ID for the cart
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Link to the user
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationship to store the items in the cart
    cart_items = db.relationship('CartItem', backref='cart', lazy=True, cascade='all, delete-orphan')

    # Method to calculate total cart price
    def total_price(self):
        return sum([item.total_item_price() for item in self.cart_items])

# Intermediate CartItem model to store product and quantity details for each cart entry
class CartItem(db.Model):
    __tablename__ = 'cart_items'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    cart_id = db.Column(db.String, db.ForeignKey('cart.id'), nullable=False)
    product_id = db.Column(db.String, db.ForeignKey('products.id'), nullable=False)  # Links to Product table
    product_variation_id = db.Column(db.String, db.ForeignKey('product_variations.id'), nullable=True)  # Links to ProductVariation table
    quantity = db.Column(db.Integer, default=1)  # Number of products to purchase

    # Relationships
    product = db.relationship('Products', back_populates='cart_items', lazy=True)
    product_variation = db.relationship('ProductVariation', backref='cart_items', lazy=True)

    # Method to calculate the total price for this CartItem
    def total_item_price(self):
        if self.product_variation:  # Use variation price if it exists
            return self.quantity * self.product_variation.price
        return self.quantity * self.product.price


# Order model to handle confirmed purchases
class Order(db.Model):
    __tablename__ = 'orders'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Link to the user
    paid = db.Column(db.Boolean, default=False)  # Payment status
    payment_reference = db.Column(db.String(255), nullable=True)  # IntaSend payment reference
    
    # Payment mode: pay_before, pay_on_delivery, user_choice (pending selection)
    payment_mode = db.Column(db.String(20), default='user_choice')
    
    # Idempotency key to prevent duplicate order creation
    idempotency_key = db.Column(db.String(64), unique=True, nullable=True)
    
    # Order status: pending, confirmed, processing, shipped, delivered, cancelled
    status = db.Column(db.String(30), default='pending')
    
    # Shipping/tracking information
    tracking_number = db.Column(db.String(100), nullable=True)
    shipping_carrier = db.Column(db.String(50), nullable=True)
    
    # Unique ticket/receipt number
    ticket_number = db.Column(db.String(50), unique=True, nullable=True)
    
    # Customer details
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(15), nullable=False)
    address = db.Column(db.String(255), nullable=False)
    
    # Total price paid
    total_price = db.Column(db.Float, nullable=False, default=0.0)
    
    # Discount applied
    discount_code = db.Column(db.String(50), nullable=True)
    discount_amount = db.Column(db.Float, default=0.0)
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    order_items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')
    status_history = db.relationship('OrderStatusHistory', backref='order', lazy=True, cascade='all, delete-orphan')

    # Method to calculate the total order price from its items
    def calculate_total(self):
        return sum([item.total_item_price() for item in self.order_items])


# OrderItem model to track the products and quantities in a confirmed order
class OrderItem(db.Model):
    __tablename__ = 'order_items'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    order_id = db.Column(db.String, db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.String, db.ForeignKey('products.id'), nullable=False)
    product_variation_id = db.Column(db.String, db.ForeignKey('product_variations.id'), nullable=True)
    seller_id = db.Column(db.String, db.ForeignKey('sellers.id'), nullable=True)  # Track which seller owns this item
    quantity = db.Column(db.Integer, default=1)
    price_at_purchase = db.Column(db.Float, nullable=True)  # Lock in price at order time
    
    # Relationships
    product_variation = db.relationship('ProductVariation', backref='order_items', lazy=True)
    seller = db.relationship('Seller', backref='order_items', lazy=True)

    # Method to calculate total price for this OrderItem
    def total_item_price(self):
        if self.price_at_purchase:
            return self.quantity * self.price_at_purchase
        return self.quantity * self.product.price


# Order status history for audit trail
class OrderStatusHistory(db.Model):
    __tablename__ = 'order_status_history'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    order_id = db.Column(db.String, db.ForeignKey('orders.id'), nullable=False)
    status = db.Column(db.String(30), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationship
    user = db.relationship('Users', backref='status_changes', lazy=True)


# Yap model (tweets)
class Yap(db.Model):
    __tablename__ = 'yaps'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    content = db.Column(db.Text, nullable=False)  # Yap content (text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    location = db.Column(db.String, nullable=True)
    
    # Foreign key to user
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Retweet reference
    original_yap_id = db.Column(db.String, db.ForeignKey('yaps.id'))
    retweets = db.relationship('Yap', backref=db.backref('original_yap', remote_side=[id]), lazy=True)
    
    # Relationships
    replies = db.relationship('Reply', backref='yap', lazy=True, cascade="all, delete-orphan")
    likes = db.relationship('Like', backref='yap', lazy=True, cascade="all, delete-orphan")
    hashtags = db.relationship('YapHashtag', backref='yap', lazy=True)
    media = db.relationship('YapMedia', backref='yap', lazy=True)  # Relationship to multiple media files

    def __repr__(self):
        return f"<Yap {self.id} by {self.user.username}>"


# Reply model with self-referential relationship for threaded replies
class Reply(db.Model):
    __tablename__ = 'replies'
    
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign key to the user who made the reply
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Foreign key to the yap being replied to
    yap_id = db.Column(db.String, db.ForeignKey('yaps.id'), nullable=True)

    # Self-referential foreign key for threaded replies
    parent_reply_id = db.Column(db.Integer, db.ForeignKey('replies.id'), nullable=True)

    # Relationship to parent reply
    parent_reply = db.relationship('Reply', remote_side=[id], backref=db.backref('child_replies', lazy=True, cascade="all, delete-orphan"))

    media = db.relationship('YapReplyMedia', backref='reply', lazy=True)  # Relationship to multiple media files


    def __repr__(self):
        return f"<Reply {self.id} by {self.user.username}>"

# Media model (multiple images and videos per Yap)
class YapReplyMedia(db.Model):
    __tablename__ = 'yapreplymedia'

    id = db.Column(db.Integer, primary_key=True)
    yap_reply_id = db.Column(db.Integer, db.ForeignKey('replies.id'), nullable=False)
    
    # URL for image or video
    media_url = db.Column(db.String(255), nullable=False)
    
    # Media type (can be 'image' or 'video')
    media_type = db.Column(db.String(10), nullable=False)  # e.g., 'image' or 'video'

    def __repr__(self):
        return f"<Media {self.media_type} for Yap {self.yap_id}>"            
# Follow model (following relationships)
class Follow(db.Model):
    __tablename__ = 'follows'
    
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    following_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('follower_id', 'following_id', name='uq_follower_following'),
    )

    def __repr__(self):
        return f"<Follow {self.follower.username} -> {self.following.username}>"
    
    @staticmethod
    def get_following_ids(user_id):
        """Get list of user IDs that the given user follows"""
        from sqlalchemy import func
        return [f.following_id for f in Follow.query.filter_by(follower_id=user_id).all()]
    
    @staticmethod
    def get_follower_ids(user_id):
        """Get list of user IDs that follow the given user"""
        from sqlalchemy import func
        return [f.follower_id for f in Follow.query.filter_by(following_id=user_id).all()]
    
    @staticmethod
    def get_mutual_connections(user_id, limit=10):
        """Get users who are followed by people the current user follows"""
        from sqlalchemy import func
        # Get users that the current user follows
        following_ids = Follow.get_following_ids(user_id)
        following_ids.append(user_id)  # Exclude self
        
        return db.session.query(
            Follow.following_id,
            func.count(Follow.follower_id).label('mutual_count')
        ).filter(
            Follow.follower_id.in_(following_ids),
            ~Follow.following_id.in_(following_ids)
        ).group_by(Follow.following_id).order_by(
            func.count(Follow.follower_id).desc()
        ).limit(limit).all()
    
    @staticmethod
    def get_popular_users(exclude_ids=None, limit=10):
        """Get users with most followers"""
        from sqlalchemy import func
        query = db.session.query(
            Users.id,
            func.count(Follow.follower_id).label('follower_count')
        ).outerjoin(Follow, Follow.following_id == Users.id)
        
        if exclude_ids:
            query = query.filter(~Users.id.in_(exclude_ids))
            
        return query.group_by(Users.id).order_by(
            func.count(Follow.follower_id).desc()
        ).limit(limit).all()
    
    @staticmethod
    def get_active_users(exclude_ids=None, days=7, limit=10):
        """Get users who have been active recently"""
        from sqlalchemy import func
        from datetime import datetime, timedelta
        
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        query = db.session.query(
            Users.id,
            func.count(Yap.id).label('recent_yaps')
        ).outerjoin(Yap, Yap.user_id == Users.id).filter(
            or_(Yap.created_at >= cutoff_date, Yap.id.is_(None))
        )
        
        if exclude_ids:
            query = query.filter(~Users.id.in_(exclude_ids))
            
        return query.group_by(Users.id).order_by(
            func.count(Yap.id).desc()
        ).limit(limit).all()

# UserHashtag model (many-to-many relationship between users and hashtags they follow)
class UserHashtag(db.Model):
    __tablename__ = 'user_hashtags'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    hashtag_id = db.Column(db.Integer, db.ForeignKey('hashtags.id'), nullable=False)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'hashtag_id', name='uq_user_hashtag'),
    )

    def __repr__(self):
        return f"<UserHashtag User {self.user.username} Hashtag {self.hashtag.name}>" 

# Hashtag model
class Hashtag(db.Model):
    __tablename__ = 'hashtags'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    # Relationships
    yaps = db.relationship('YapHashtag', backref='hashtag', lazy=True)
    users = db.relationship('UserHashtag', backref='hashtag', lazy=True)

    def __repr__(self):
        return f"<Hashtag {self.name}>"        

# YapHashtag model (many-to-many relationship between yaps and hashtags)
class YapHashtag(db.Model):
    __tablename__ = 'yap_hashtags'
    
    id = db.Column(db.Integer, primary_key=True)
    yap_id = db.Column(db.String, db.ForeignKey('yaps.id'), nullable=False)
    hashtag_id = db.Column(db.Integer, db.ForeignKey('hashtags.id'), nullable=False)

    __table_args__ = (
        db.UniqueConstraint('yap_id', 'hashtag_id', name='uq_yap_hashtag'),
    )

    def __repr__(self):
        return f"<YapHashtag Yap {self.yap_id} Hashtag {self.hashtag.name}>"   


# YapMention model (track @username mentions in yaps)
class YapMention(db.Model):
    __tablename__ = 'yap_mentions'
    
    id = db.Column(db.Integer, primary_key=True)
    yap_id = db.Column(db.String, db.ForeignKey('yaps.id'), nullable=False)
    mentioned_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    yap = db.relationship('Yap', backref='mentions', lazy=True)
    mentioned_user = db.relationship('Users', backref='mentions_received', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('yap_id', 'mentioned_user_id', name='uq_yap_mention'),
    )

    def __repr__(self):
        return f"<YapMention Yap {self.yap_id} User {self.mentioned_user_id}>"


class Notification(db.Model):
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False)  # Can be: LIKE, RETWEET, FOLLOW, MENTION, REPLY, etc.
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    yap_id = db.Column(db.String, db.ForeignKey('yaps.id'), nullable=True)
    reply_id = db.Column(db.Integer, db.ForeignKey('replies.id'), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Notification to {self.recipient.username} - {self.type}>"  

# Media model (multiple images and videos per Yap)
class YapMedia(db.Model):
    __tablename__ = 'yapmedia'

    id = db.Column(db.Integer, primary_key=True)
    yap_id = db.Column(db.String, db.ForeignKey('yaps.id'), nullable=False)
    
    # URL for image or video
    media_url = db.Column(db.String(255), nullable=False)
    
    # Media type (can be 'image' or 'video')
    media_type = db.Column(db.String(10), nullable=False)  # e.g., 'image' or 'video'

    def __repr__(self):
        return f"<Media {self.media_type} for Yap {self.yap_id}>"          


# Like model (likes for yaps and replies)
class Like(db.Model):
    __tablename__ = 'likes'
    
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    yap_id = db.Column(db.String, db.ForeignKey('yaps.id'), nullable=True)
    reply_id = db.Column(db.Integer, db.ForeignKey('replies.id'), nullable=True)

    def __repr__(self):
        return f"<Like by {self.user.username}>"

class Comment_events(db.Model, SerializerMixin):
    __tablename__ = 'comment_events'
    
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    event_id = db.Column(db.String, db.ForeignKey('events.id'))
    parent_comment_id = db.Column(db.Integer, db.ForeignKey('comment_events.id'))

    replies = db.relationship(
        'Comment_events',
        backref=db.backref('parent_comment', remote_side=[id]),
        lazy=True,
        cascade='all, delete-orphan'
    )
    likes = db.relationship('CommentEventLike', backref='comment', lazy=True, cascade='all, delete-orphan')


class CommentEventLike(db.Model, SerializerMixin):
    __tablename__ = 'comment_event_likes'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    comment_id = db.Column(db.Integer, db.ForeignKey('comment_events.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'comment_id', name='uq_comment_like_user'),
    )


class Reviews(db.Model, SerializerMixin):
    __tablename__ = 'reviews'
    
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(255))
    rating = db.Column(db.Float)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    product_id = db.Column(db.String, db.ForeignKey('products.id'))


class Wishlists(db.Model, SerializerMixin):
    __tablename__ = 'wishlists'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.String, db.ForeignKey('products.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('Users', backref='wishlists_items', lazy=True)
    product = db.relationship('Products', backref='wishlists_items', lazy=True)

    def __repr__(self):
        return f"<Wishlist {self.id}>"


class Friendship(db.Model):
    __tablename__ = 'friendships'
    
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    addressee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')  # 'pending', 'accepted', 'declined', 'blocked'
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_close_friend = db.Column(db.Boolean, nullable=False, default=False)
    
    # Relationships to Users
    requester = db.relationship('Users', foreign_keys=[requester_id], backref='sent_friend_requests')
    addressee = db.relationship('Users', foreign_keys=[addressee_id], backref='received_friend_requests')
    
    # Ensure unique friendship requests
    __table_args__ = (
        db.UniqueConstraint('requester_id', 'addressee_id', name='unique_friendship_request'),
        db.CheckConstraint('requester_id != addressee_id', name='no_self_friendship'),
    )
    
    def __repr__(self):
        return f"<Friendship {self.requester_id} -> {self.addressee_id}: {self.status}>"


class Conversation(db.Model):
    __tablename__ = 'conversations'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    user1_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user2_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # New metadata fields for better UX
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_pinned_by_user1 = db.Column(db.Boolean, default=False, nullable=False)
    is_pinned_by_user2 = db.Column(db.Boolean, default=False, nullable=False)
    last_message_id = db.Column(db.Integer, nullable=True)
    last_message_preview = db.Column(db.String(200), nullable=True)
    
    # Relationships
    user1 = db.relationship('Users', foreign_keys=[user1_id])
    user2 = db.relationship('Users', foreign_keys=[user2_id])
    
    # Ensure unique conversations between two users
    __table_args__ = (
        db.UniqueConstraint('user1_id', 'user2_id', name='unique_conversation'),
        db.CheckConstraint('user1_id != user2_id', name='no_self_conversation'),
    )
    
    def __repr__(self):
        return f"<Conversation {self.user1_id} <-> {self.user2_id}>"
    
    def get_other_user(self, current_user_id):
        """Get the other user in the conversation"""
        return self.user2 if self.user1_id == current_user_id else self.user1


class TokenBlocklist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    jti =  db.Column(db.String(100),nullable=True)
    created_at = db.Column(db.DateTime(), default=datetime.utcnow)

# ==================== PHASE 8 MODELS ====================

# Groups/Communities
class Group(db.Model, SerializerMixin):
    __tablename__ = 'groups'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(100))  # 'study', 'hobby', 'professional', 'event_planning', 'other'
    privacy_type = db.Column(db.String(20), default='public')  # 'public', 'private', 'secret'
    cover_image = db.Column(db.String(255))
    icon_image = db.Column(db.String(255))
    rules = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    member_count = db.Column(db.Integer, default=0)
    is_verified = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    creator = db.relationship('Users', backref='created_groups')
    members = db.relationship('GroupMember', backref='group', lazy=True, cascade='all, delete-orphan')
    posts = db.relationship('GroupPost', backref='group', lazy=True, cascade='all, delete-orphan')
    polls = db.relationship('Poll', backref='group', lazy=True)
    
    def __repr__(self):
        return f"<Group {self.name}>"    

class GroupMember(db.Model, SerializerMixin):
    __tablename__ = 'group_members'
    
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.String, db.ForeignKey('groups.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(20), default='member')  # 'admin', 'moderator', 'member'
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    user = db.relationship('Users', backref='group_memberships')
    
    __table_args__ = (
        db.UniqueConstraint('group_id', 'user_id', name='unique_group_member'),
    )
    
    def __repr__(self):
        return f"<GroupMember {self.user_id} in {self.group_id}>"        

class GroupPost(db.Model, SerializerMixin):
    __tablename__ = 'group_posts'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    group_id = db.Column(db.String, db.ForeignKey('groups.id'), nullable=False)
    yap_id = db.Column(db.String, db.ForeignKey('yaps.id'), nullable=False)
    is_pinned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    yap = db.relationship('Yap', backref='group_posts')
    
    def __repr__(self):
        return f"<GroupPost {self.yap_id} in {self.group_id}>"

# Polls and Surveys
class Poll(db.Model, SerializerMixin):
    __tablename__ = 'polls'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    creator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    group_id = db.Column(db.String, db.ForeignKey('groups.id'), nullable=True)  # NULL for campus-wide
    poll_type = db.Column(db.String(20), default='single')  # 'single', 'multiple'
    category = db.Column(db.String(50))  # 'campus', 'event', 'course', 'general'
    is_anonymous = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    ends_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    total_votes = db.Column(db.Integer, default=0)
    
    # Relationships
    creator = db.relationship('Users', backref='created_polls')
    options = db.relationship('PollOption', backref='poll', lazy=True, cascade='all, delete-orphan')
    votes = db.relationship('PollVote', backref='poll', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"<Poll {self.title}>"

class PollOption(db.Model, SerializerMixin):
    __tablename__ = 'poll_options'
    
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.String, db.ForeignKey('polls.id'), nullable=False)
    option_text = db.Column(db.String(255), nullable=False)
    vote_count = db.Column(db.Integer, default=0)
    order_index = db.Column(db.Integer, default=0)
    
    def __repr__(self):
        return f"<PollOption {self.option_text}>"

class PollVote(db.Model, SerializerMixin):
    __tablename__ = 'poll_votes'
    
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.String, db.ForeignKey('polls.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    option_id = db.Column(db.Integer, db.ForeignKey('poll_options.id'), nullable=False)
    voted_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('Users', backref='poll_votes')
    option = db.relationship('PollOption', backref='votes')
    
    __table_args__ = (
        db.UniqueConstraint('poll_id', 'user_id', name='unique_poll_vote'),
    )
    
    def __repr__(self):
        return f"<PollVote user:{self.user_id} poll:{self.poll_id}>"

# Gamification and Achievements
class UserPoints(db.Model, SerializerMixin):
    __tablename__ = 'user_points'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    points_total = db.Column(db.Integer, default=0)
    points_this_week = db.Column(db.Integer, default=0)
    points_this_month = db.Column(db.Integer, default=0)
    level = db.Column(db.Integer, default=1)
    streak_days = db.Column(db.Integer, default=0)
    last_activity_date = db.Column(db.Date)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Reputation scores
    seller_reputation = db.Column(db.Float, default=0.0)
    event_organizer_rating = db.Column(db.Float, default=0.0)
    study_contributor_score = db.Column(db.Integer, default=0)
    community_helper_rating = db.Column(db.Float, default=0.0)
    
    # Relationships
    user = db.relationship('Users', backref=db.backref('points', uselist=False))
    
    def __repr__(self):
        return f"<UserPoints user:{self.user_id} total:{self.points_total}>"

class Achievement(db.Model, SerializerMixin):
    __tablename__ = 'achievements'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    icon_url = db.Column(db.String(255))
    points_required = db.Column(db.Integer)
    category = db.Column(db.String(50))  # 'social', 'marketplace', 'events', 'academic', 'community'
    badge_type = db.Column(db.String(20))  # 'bronze', 'silver', 'gold', 'platinum'
    criteria = db.Column(db.Text)  # JSON string with achievement criteria
    is_active = db.Column(db.Boolean, default=True)
    
    def __repr__(self):
        return f"<Achievement {self.name}>"

class UserAchievement(db.Model, SerializerMixin):
    __tablename__ = 'user_achievements'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    achievement_id = db.Column(db.Integer, db.ForeignKey('achievements.id'), nullable=False)
    earned_at = db.Column(db.DateTime, default=datetime.utcnow)
    progress = db.Column(db.Integer, default=100)  # Percentage of achievement completion
    
    # Relationships
    user = db.relationship('Users', backref='achievements')
    achievement = db.relationship('Achievement', backref='users_earned')
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'achievement_id', name='unique_user_achievement'),
    )
    
    def __repr__(self):
        return f"<UserAchievement user:{self.user_id} achievement:{self.achievement_id}>"

class PointTransaction(db.Model, SerializerMixin):
    __tablename__ = 'point_transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    points = db.Column(db.Integer, nullable=False)  # Positive for earned, negative for spent
    transaction_type = db.Column(db.String(50))  # 'post_yap', 'like_received', 'event_attended', etc.
    description = db.Column(db.String(255))
    reference_id = db.Column(db.String)  # ID of related object (yap_id, event_id, etc.)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('Users', backref='point_transactions')
    
    def __repr__(self):
        return f"<PointTransaction user:{self.user_id} points:{self.points}>"

# Trending and Discovery
class TrendingTopic(db.Model, SerializerMixin):
    __tablename__ = 'trending_topics'
    
    id = db.Column(db.Integer, primary_key=True)
    topic_type = db.Column(db.String(20))  # 'hashtag', 'event', 'product', 'group', 'yap'
    topic_id = db.Column(db.String)  # ID of the trending item
    topic_name = db.Column(db.String(255))
    score = db.Column(db.Float, default=0.0)  # Trending score
    engagement_count = db.Column(db.Integer, default=0)  # Number of interactions
    trending_since = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    def __repr__(self):
        return f"<TrendingTopic {self.topic_type}:{self.topic_name}>"

# Enhanced Notifications
class NotificationPreference(db.Model, SerializerMixin):
    __tablename__ = 'notification_preferences'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    
    # Notification types
    group_invites = db.Column(db.Boolean, default=True)
    group_activity = db.Column(db.Boolean, default=True)
    trending_content = db.Column(db.Boolean, default=True)
    friend_milestones = db.Column(db.Boolean, default=True)
    event_reminders = db.Column(db.Boolean, default=True)
    marketplace_alerts = db.Column(db.Boolean, default=True)
    poll_results = db.Column(db.Boolean, default=True)
    achievement_unlocked = db.Column(db.Boolean, default=True)
    
    # Delivery preferences
    email_enabled = db.Column(db.Boolean, default=False)
    push_enabled = db.Column(db.Boolean, default=True)
    sms_enabled = db.Column(db.Boolean, default=False)
    
    # Quiet hours
    quiet_hours_enabled = db.Column(db.Boolean, default=False)
    quiet_hours_start = db.Column(db.Time)  # e.g., 22:00
    quiet_hours_end = db.Column(db.Time)    # e.g., 08:00
    
    # Priority settings
    min_priority_level = db.Column(db.String(10), default='low')  # 'low', 'medium', 'high'
    
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('Users', backref=db.backref('notification_preferences', uselist=False))
    
    def __repr__(self):
        return f"<NotificationPreference user:{self.user_id}>"

class EnhancedNotification(db.Model, SerializerMixin):
    __tablename__ = 'enhanced_notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False)  # Same as before, plus new types
    priority = db.Column(db.String(10), default='medium')  # 'low', 'medium', 'high'
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Reference fields for different types
    group_id = db.Column(db.String, db.ForeignKey('groups.id'), nullable=True)
    poll_id = db.Column(db.String, db.ForeignKey('polls.id'), nullable=True)
    achievement_id = db.Column(db.Integer, db.ForeignKey('achievements.id'), nullable=True)
    yap_id = db.Column(db.String, db.ForeignKey('yaps.id'), nullable=True)
    event_id = db.Column(db.String, db.ForeignKey('events.id'), nullable=True)
    
    title = db.Column(db.String(255))
    message = db.Column(db.Text)
    action_url = db.Column(db.String(255))  # URL to navigate when clicked
    
    is_read = db.Column(db.Boolean, default=False)
    is_delivered = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime)
    
    # Relationships
    recipient = db.relationship('Users', foreign_keys=[recipient_id], backref='enhanced_notifications_received')
    sender = db.relationship('Users', foreign_keys=[sender_id], backref='enhanced_notifications_sent')
    
    def __repr__(self):
        return f"<EnhancedNotification {self.type} to:{self.recipient_id}>"



# Serialization rules
Users.serialize_rules = (
    '-events.user',
    '-fun_times.user',
    '-comments_on_events.user',
    '-comments_on_fun_times.user',
    '-products.user',
    '-reviews.user',
)

Events.serialize_rules = (
    '-users.events',
    '-comments.event',
    '-ticket_groups.event',
)

Products.serialize_rules = (
    '-users.products',
    '-reviews.product',
)

Yap.serialize_rules = (
    '-users.yaps',
    '-replies.yaps',
    '-likes.yap',
)


EventTicketGroup.serialize_rules = (
    '-event.ticket_groups',
)


Comment_events.serialize_rules = (
    '-users.comment_events',
    '-events.comment_events',
    '-replies.parent_comment',
    '-parent_comment.replies',
    '-likes.comment',
)


CommentEventLike.serialize_rules = (
    '-comment.likes',
    '-user.likes',
)


Reviews.serialize_rules = (
    '-users.reviews',
    '-products.reviews',
)

Wishlists.serialize_rules = (
    'user.id',
    'user.first_name',
    'user.last_name', 
    'user.email',
    'user.phone_no',
    'user.image_url',
    'product.id',
    'product.title',      
    'product.description',
    'product.price'
)

# Badge System Models
class Badge(db.Model):
    __tablename__ = 'badges'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    image_url = db.Column(db.String(500), nullable=False)  # URL to badge image/gif
    price_ksh = db.Column(db.Integer, nullable=False)  # Price in Kenyan Shillings
    is_animated = db.Column(db.Boolean, default=False)  # Whether it's a GIF
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user_badges = db.relationship('UserBadge', backref='badge', lazy=True)
    transactions = db.relationship('BadgeTransaction', backref='badge', lazy=True)

class UserBadge(db.Model):
    __tablename__ = 'user_badges'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    badge_id = db.Column(db.Integer, db.ForeignKey('badges.id'), nullable=False)
    is_displayed = db.Column(db.Boolean, default=True)  # Whether to show on profile
    display_order = db.Column(db.Integer, default=0)  # Order to display badges
    purchased_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('user_id', 'badge_id', name='unique_user_badge'),)

class BadgeTransaction(db.Model):
    __tablename__ = 'badge_transactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    badge_id = db.Column(db.Integer, db.ForeignKey('badges.id'), nullable=False)
    
    # M-Pesa transaction details
    phone_number = db.Column(db.String(15), nullable=False)
    amount = db.Column(db.Integer, nullable=False)  # Amount in KES
    mpesa_receipt_number = db.Column(db.String(50), unique=True)
    mpesa_transaction_id = db.Column(db.String(50), unique=True)
    checkout_request_id = db.Column(db.String(100))  # For tracking STK push
    
    # Transaction status
    status = db.Column(db.String(20), default='PENDING')  # PENDING, COMPLETED, FAILED, CANCELLED
    payment_method = db.Column(db.String(20), default='MPESA')
    payment_provider = db.Column(db.String(20), default='intasend')  # 'intasend' or 'mpesa'
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # Error tracking
    error_message = db.Column(db.Text, nullable=True)


# ============================================================================
# Database Indexes for Performance Optimization
# ============================================================================

# Index for message queries (fetching messages by conversation, ordered by time)
db.Index('idx_messages_conversation_timestamp', Message.conversation_id, Message.timestamp.desc())

# Index for friendship queries (finding friends and requests)
db.Index('idx_friendship_users_status', Friendship.requester_id, Friendship.addressee_id, Friendship.status)

# Index for conversation lookups (finding conversations between two users)
db.Index('idx_conversation_users', Conversation.user1_id, Conversation.user2_id)

# Index for user activity queries (checking online status)
# Note: UserActivity is in models_blocking.py but we reference it here for completeness
# This index should be added to models_blocking.py if needed

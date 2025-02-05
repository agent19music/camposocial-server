from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData, CheckConstraint
from datetime import datetime
from sqlalchemy_serializer import SerializerMixin
from sqlalchemy.orm import validates
from cuid import cuid

# Define metadata with a naming convention for foreign keys
metadata = MetaData(naming_convention={
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
})

db = SQLAlchemy(metadata=metadata)

class Users(db.Model, SerializerMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(255), nullable=False)
    last_name = db.Column(db.String(255), nullable=False)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    phone_no = db.Column(db.String(20), nullable=True)
    category = db.Column(db.String(100), nullable=False)
    avatar = db.Column(db.String(255))  # Store the URL of the image
    display_name = db.Column(db.String(100))
    bio = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    public_key = db.Column(db.Text, nullable=True) 
    
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

    # Method to get all reviews belonging to a user
    def get_reviews(self):
        return self.reviews

    # Method to calculate the average rating given by the user across all reviews
    def average_review_rating(self):
        if len(self.reviews) == 0:
            return None
        return sum([review.rating for review in self.reviews]) / len(self.reviews)
    
    def send_friend_request(self, friend_id):
        friendship = Friendship(user_id=self.id, friend_id=friend_id, status='pending')
        db.session.add(friendship)
        db.session.commit()

    # Method to accept a friend request
    def accept_friend_request(self, friend_id):
        friendship = Friendship.query.filter_by(user_id=friend_id, friend_id=self.id, status='pending').first()
        if friendship:
            friendship.status = 'accepted'
            db.session.commit()

    # Method to get all friends
    def get_friends(self):
        friendships = Friendship.query.filter(
            ((Friendship.user_id == self.id) | (Friendship.friend_id == self.id)) & 
            (Friendship.status == 'accepted')
        ).all()
        friends = [f.friend if f.user_id == self.id else f.user for f in friendships]
        return friends
    
    def get_friend_ids(self):
        friendships = Friendship.query.filter(
            ((Friendship.user_id == self.id) | (Friendship.friend_id == self.id)) & 
            (Friendship.status == 'accepted')
        ).all()
        friend_ids = [f.friend_id if f.user_id == self.id else f.user_id for f in friendships]
        return set(friend_ids)

    # Method to calculate the number of mutual friends with each user
    def mutual_friends_with_users(self):
        my_friends = self.get_friend_ids()
        users = Users.query.filter(Users.id != self.id).all()  # Get all users except the current user
        mutual_friends_count = {}

        for user in users:
            user_friends = user.get_friend_ids()
            mutual_count = len(my_friends & user_friends)  # Intersection of two friend sets
            mutual_friends_count[user] = mutual_count

        return mutual_friends_count

    # Method to recommend mutual friends
    def recommend_mutual_friends(self):
        friends = self.get_friends()
        mutual_friends = {}
        for friend in friends:
            for mutual_friend in friend.get_friends():
                if mutual_friend != self and mutual_friend not in friends:
                    mutual_friends[mutual_friend] = mutual_friends.get(mutual_friend, 0) + 1

        # Sort mutual friends by the number of mutual connections
        return sorted(mutual_friends.items(), key=lambda x: x[1], reverse=True)
    
    @validates('username')
    def validate_username(self, key, username):
        if not username.isalnum():
            raise AssertionError('The username can only contain numbers or letters')
        return username

    # @validates('email')
    # def validate_email(self, key, email):
    #     if not email.endswith('@student.com'):
    #         raise AssertionError('Wrong email format')
    #     return email

class Friendship(db.Model):
    __tablename__ = 'friendships'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(50), default='pending')  # 'pending', 'accepted', or 'blocked'
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Unique constraint to prevent duplicate friendship entries
    __table_args__ = (
        db.UniqueConstraint('user_id', 'friend_id', name='unique_friendship'),
    )

    # Backref for accessing both directions of a friendship
    user = db.relationship('Users', foreign_keys=[user_id], backref='friendships')
    friend = db.relationship('Users', foreign_keys=[friend_id])


class ChatMedia(db.Model):
    __tablename__ = 'chat_media'
    id = db.Column(db.Integer, primary_key=True)
    media_url = db.Column(db.String(500), nullable=False)
    media_type = db.Column(db.String(50), nullable=False)  # 'image', 'video', 'gif'
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    encrypted_content = db.Column(db.Text, nullable=False)  # Store the encrypted message
    is_deleted = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign Keys
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reply_to_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=True)
    
    reactions = db.relationship('Reaction', backref='message', lazy=True)
    media = db.relationship('ChatMedia', backref='message', lazy=True)

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
    comments = db.relationship('Comment_events', backref='event', lazy=True)
    
class Products(db.Model, SerializerMixin):
    __tablename__ = 'products'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    title = db.Column(db.String(255))
    description = db.Column(db.String(255))
    contact_info = db.Column(db.String(20), nullable=True)
    brand = db.Column(db.String(155), nullable=True)
    price = db.Column(db.Float)
    category = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    seller_id = db.Column(db.Integer, db.ForeignKey('sellers.id'))

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
    phone_no = db.Column(db.String(10), nullable=True)  # URL for the avatar
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True)  # Each seller corresponds to a user

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)  
    products = db.relationship('Products', backref='seller', lazy=True)


    # Method to get total sales across seller's products
    def total_sales(self):
        return sum([product.total_sales for product in self.products])

    # Method to count the number of products the seller has
    def product_count(self):
        return len(self.products)   

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
    payment_reference = db.Column(db.String(255), nullable=True)  # Paystack payment reference
    
    # Customer details
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(15), nullable=False)
    address = db.Column(db.String(255), nullable=False)
    
    # Total price paid
    total_price = db.Column(db.Float, nullable=False, default=0.0)
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationship to store the items in the order (copied from the cart)
    order_items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')

    # Method to calculate the total order price from its items
    def calculate_total(self):
        return sum([item.total_item_price() for item in self.order_items])


# OrderItem model to track the products and quantities in a confirmed order
class OrderItem(db.Model):
    __tablename__ = 'order_items'
    
    id = db.Column(db.String, primary_key=True, default=cuid)
    order_id = db.Column(db.String, db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.String, db.ForeignKey('products.id'), nullable=False)  # Link to Product table
    quantity = db.Column(db.Integer, default=1)  # Number of products purchased

    # Method to calculate total price for this OrderItem
    def total_item_price(self):
        return self.quantity * self.product.price
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
    original_yap_id = db.Column(db.Integer, db.ForeignKey('yaps.id'))
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
    
    yap_id = db.Column(db.Integer, db.ForeignKey('yaps.id'), nullable=True)
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

class TokenBlocklist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    jti =  db.Column(db.String(100),nullable=True)
    created_at = db.Column(db.DateTime(), default=datetime.utcnow)



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


Comment_events.serialize_rules = (
    '-users.comment_events',
    '-events.comment_events',
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

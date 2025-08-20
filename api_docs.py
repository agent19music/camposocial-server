from flask_restx import Api, Resource, fields, Namespace
from flask import Blueprint
from functools import wraps
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity

# Create API documentation blueprint
api_bp = Blueprint('api_doc', __name__)

# Initialize Flask-RESTX API with Swagger documentation
api = Api(
    api_bp,
    version='1.0',
    title='CampoSocial API',
    description='Complete API documentation for CampoSocial platform',
    doc='/docs',  # This is where Swagger UI will be available
    ordered=True,
    contact='CampoSocial Team',
    contact_email='support@camposocial.com'
)

# Define namespaces for different API sections
auth_ns = Namespace('auth', description='Authentication operations', path='/camposocial/api')
users_ns = Namespace('users', description='User management operations', path='/camposocial/api')
events_ns = Namespace('events', description='Event management operations', path='/camposocial/api')
marketplace_ns = Namespace('marketplace', description='Marketplace operations', path='/camposocial/api')
yaps_ns = Namespace('yaps', description='Yap (posts) operations', path='/camposocial/api')
friends_ns = Namespace('friends', description='Friends and messaging operations', path='/camposocial/api')

# Add namespaces to API
api.add_namespace(auth_ns)
api.add_namespace(users_ns)
api.add_namespace(events_ns)
api.add_namespace(marketplace_ns)
api.add_namespace(yaps_ns)
api.add_namespace(friends_ns)

# JWT decorator for documentation
def jwt_required_doc(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        verify_jwt_in_request()
        return f(*args, **kwargs)
    return decorated

# ============= API Models for Request/Response Documentation =============

# User Models
user_model = api.model('User', {
    'id': fields.Integer(description='User ID'),
    'username': fields.String(required=True, description='Username'),
    'email': fields.String(required=True, description='Email address'),
    'first_name': fields.String(description='First name'),
    'last_name': fields.String(description='Last name'),
    'phone_no': fields.String(description='Phone number'),
    'category': fields.String(description='User category/course'),
    'avatar': fields.String(description='Avatar URL'),
    'gender': fields.String(description='Gender'),
    'display_name': fields.String(description='Display name')
})

login_model = api.model('Login', {
    'username': fields.String(required=True, description='Username'),
    'password': fields.String(required=True, description='Password')
})

login_response = api.model('LoginResponse', {
    'access_token': fields.String(description='JWT access token')
})

# Event Models
event_model = api.model('Event', {
    'eventId': fields.Integer(description='Event ID'),
    'title': fields.String(required=True, description='Event title'),
    'description': fields.String(required=True, description='Event description'),
    'poster': fields.String(description='Event poster URL'),
    'start_time': fields.String(description='Start time'),
    'end_time': fields.String(description='End time'),
    'date': fields.String(description='Event date'),
    'entry_fee': fields.Float(description='Entry fee'),
    'category': fields.String(description='Event category')
})

event_input = api.model('EventInput', {
    'title': fields.String(required=True, description='Event title'),
    'description': fields.String(required=True, description='Event description'),
    'date_of_event': fields.String(required=True, description='Date in YYYY-MM-DD format'),
    'start_time': fields.String(required=True, description='Start time in HH:MM AM/PM format'),
    'end_time': fields.String(required=True, description='End time in HH:MM AM/PM format'),
    'entry_fee': fields.Float(required=True, description='Entry fee'),
    'category': fields.String(required=True, description='Event category (Fun/Educational/Social)')
})

# Yap Models
yap_model = api.model('Yap', {
    'id': fields.String(description='Yap ID'),
    'content': fields.String(required=True, description='Yap content'),
    'timestamp': fields.DateTime(description='Creation timestamp'),
    'location': fields.String(description='Location'),
    'user_id': fields.Integer(description='User ID'),
    'username': fields.String(description='Username'),
    'display_name': fields.String(description='Display name'),
    'avatar': fields.String(description='User avatar'),
    'likes_count': fields.Integer(description='Number of likes'),
    'replies_count': fields.Integer(description='Number of replies'),
    'retweets_count': fields.Integer(description='Number of retweets'),
    'media': fields.List(fields.Raw, description='Media attachments'),
    'hashtags': fields.List(fields.String, description='Hashtags')
})

yap_input = api.model('YapInput', {
    'content': fields.String(required=True, description='Yap content'),
    'location': fields.String(description='Location (optional)'),
    'original_yap_id': fields.String(description='Original yap ID for retweets (optional)')
})

# Product Models
product_model = api.model('Product', {
    'id': fields.String(description='Product ID'),
    'title': fields.String(required=True, description='Product title'),
    'description': fields.String(description='Product description'),
    'price': fields.Float(description='Product price'),
    'category': fields.String(description='Product category'),
    'brand': fields.String(description='Brand name'),
    'contact_info': fields.String(description='Contact information'),
    'images': fields.List(fields.String, description='Product images'),
    'average_rating': fields.Float(description='Average rating'),
    'variations': fields.List(fields.Raw, description='Product variations'),
    'seller': fields.Raw(description='Seller information')
})

cart_add_model = api.model('AddToCart', {
    'product_id': fields.String(required=True, description='Product ID'),
    'product_variation_id': fields.String(description='Product variation ID (optional)'),
    'quantity': fields.Integer(description='Quantity (default: 1)')
})

# Friend Models
friend_request_model = api.model('FriendRequest', {
    'user_id': fields.Integer(required=True, description='Target user ID')
})

friend_model = api.model('Friend', {
    'id': fields.Integer(description='Friend user ID'),
    'username': fields.String(description='Username'),
    'first_name': fields.String(description='First name'),
    'last_name': fields.String(description='Last name'),
    'avatar': fields.String(description='Avatar URL'),
    'display_name': fields.String(description='Display name'),
    'is_online': fields.Boolean(description='Online status'),
    'friendship_id': fields.Integer(description='Friendship ID'),
    'since': fields.DateTime(description='Friends since')
})

# Conversation Models
conversation_model = api.model('Conversation', {
    'conversation_id': fields.String(description='Conversation ID'),
    'friend': fields.Raw(description='Friend information'),
    'last_message': fields.Raw(description='Last message'),
    'updated_at': fields.DateTime(description='Last updated')
})

# ============= Authentication Endpoints Documentation =============

@auth_ns.route('/login')
class Login(Resource):
    @auth_ns.expect(login_model)
    @auth_ns.marshal_with(login_response)
    @auth_ns.doc(
        description='Authenticate user and receive JWT token',
        responses={
            200: 'Login successful',
            401: 'Invalid credentials',
            404: 'User not found'
        }
    )
    def post(self):
        '''User login'''
        pass  # Implementation is in auth_view.py

@auth_ns.route('/authenticated_user')
class AuthenticatedUser(Resource):
    @auth_ns.doc(
        security='jwt',
        description='Get current authenticated user information',
        responses={
            200: 'Success',
            401: 'Unauthorized',
            404: 'User not found'
        }
    )
    @auth_ns.marshal_with(user_model)
    def get(self):
        '''Get authenticated user details'''
        pass  # Implementation is in auth_view.py

@auth_ns.route('/logout')
class Logout(Resource):
    @auth_ns.doc(
        security='jwt',
        description='Logout user and invalidate JWT token',
        responses={
            200: 'Logout successful',
            401: 'Unauthorized'
        }
    )
    def post(self):
        '''User logout'''
        pass  # Implementation is in auth_view.py

# ============= User Endpoints Documentation =============

@users_ns.route('/users')
class UserList(Resource):
    @users_ns.doc(
        description='Get all users',
        responses={
            200: 'Success',
            404: 'No users found'
        }
    )
    @users_ns.marshal_list_with(user_model)
    def get(self):
        '''List all users'''
        pass  # Implementation is in user_view.py

@users_ns.route('/users/<int:user_id>')
@users_ns.param('user_id', 'User ID')
class User(Resource):
    @users_ns.doc(
        description='Get specific user by ID',
        responses={
            200: 'Success',
            404: 'User not found'
        }
    )
    @users_ns.marshal_with(user_model)
    def get(self, user_id):
        '''Get a user by ID'''
        pass  # Implementation is in user_view.py

@users_ns.route('/profile')
class UserProfile(Resource):
    @users_ns.doc(
        security='jwt',
        description='Get current user profile',
        responses={
            200: 'Success',
            401: 'Unauthorized',
            404: 'User not found'
        }
    )
    @users_ns.marshal_with(user_model)
    def get(self):
        '''Get current user profile'''
        pass  # Implementation is in user_view.py

    @users_ns.doc(
        security='jwt',
        description='Update user profile',
        responses={
            200: 'Profile updated successfully',
            401: 'Unauthorized',
            404: 'User not found'
        }
    )
    def put(self):
        '''Update current user profile'''
        pass  # Implementation is in user_view.py

# ============= Event Endpoints Documentation =============

@events_ns.route('/events')
class EventList(Resource):
    @events_ns.doc(
        description='Get all events',
        responses={
            200: 'Success'
        }
    )
    @events_ns.marshal_list_with(event_model)
    def get(self):
        '''List all events'''
        pass  # Implementation is in event_view.py

@events_ns.route('/add-event')
class AddEvent(Resource):
    @events_ns.doc(
        security='jwt',
        description='Create a new event',
        responses={
            201: 'Event created successfully',
            400: 'Missing required fields',
            401: 'Unauthorized'
        }
    )
    @events_ns.expect(event_input)
    def post(self):
        '''Create a new event'''
        pass  # Implementation is in event_view.py

@events_ns.route('/events/<int:event_id>')
@events_ns.param('event_id', 'Event ID')
class Event(Resource):
    @events_ns.doc(
        description='Get specific event by ID',
        responses={
            200: 'Success',
            404: 'Event not found'
        }
    )
    @events_ns.marshal_with(event_model)
    def get(self, event_id):
        '''Get an event by ID'''
        pass  # Implementation is in event_view.py

# ============= Yap Endpoints Documentation =============

@yaps_ns.route('/yaps')
class YapList(Resource):
    @yaps_ns.doc(
        description='Get all yaps with pagination',
        params={
            'page': 'Page number (default: 1)',
            'per_page': 'Items per page (default: 10)'
        },
        responses={
            200: 'Success'
        }
    )
    @yaps_ns.marshal_list_with(yap_model)
    def get(self):
        '''List all yaps'''
        pass  # Implementation is in yap_view.py

@yaps_ns.route('/add_yap')
class AddYap(Resource):
    @yaps_ns.doc(
        security='jwt',
        description='Create a new yap',
        responses={
            201: 'Yap created successfully',
            400: 'Content is required',
            401: 'Unauthorized'
        }
    )
    @yaps_ns.expect(yap_input)
    def post(self):
        '''Create a new yap'''
        pass  # Implementation is in yap_view.py

# ============= Marketplace Endpoints Documentation =============

@marketplace_ns.route('/products')
class ProductList(Resource):
    @marketplace_ns.doc(
        description='Get all products',
        responses={
            200: 'Success',
            500: 'Server error'
        }
    )
    @marketplace_ns.marshal_list_with(product_model)
    def get(self):
        '''List all products'''
        pass  # Implementation is in marketplace_view.py

@marketplace_ns.route('/products/<string:product_id>')
@marketplace_ns.param('product_id', 'Product ID')
class Product(Resource):
    @marketplace_ns.doc(
        description='Get specific product by ID',
        responses={
            200: 'Success',
            404: 'Product not found'
        }
    )
    @marketplace_ns.marshal_with(product_model)
    def get(self, product_id):
        '''Get a product by ID'''
        pass  # Implementation is in marketplace_view.py

@marketplace_ns.route('/cart/add')
class AddToCart(Resource):
    @marketplace_ns.doc(
        security='jwt',
        description='Add product to cart',
        responses={
            201: 'Product added to cart',
            400: 'Product ID required',
            401: 'Unauthorized',
            404: 'Product not found'
        }
    )
    @marketplace_ns.expect(cart_add_model)
    def post(self):
        '''Add product to cart'''
        pass  # Implementation is in marketplace_view.py

# ============= Friends Endpoints Documentation =============

@friends_ns.route('/friends')
class FriendList(Resource):
    @friends_ns.doc(
        security='jwt',
        description='Get list of accepted friends',
        responses={
            200: 'Success',
            401: 'Unauthorized'
        }
    )
    @friends_ns.marshal_list_with(friend_model)
    def get(self):
        '''List all friends'''
        pass  # Implementation is in friends_view.py

@friends_ns.route('/friends/request')
class SendFriendRequest(Resource):
    @friends_ns.doc(
        security='jwt',
        description='Send a friend request',
        responses={
            201: 'Friend request sent',
            400: 'Invalid request',
            401: 'Unauthorized',
            404: 'User not found'
        }
    )
    @friends_ns.expect(friend_request_model)
    def post(self):
        '''Send friend request'''
        pass  # Implementation is in friends_view.py

@friends_ns.route('/conversations')
class ConversationList(Resource):
    @friends_ns.doc(
        security='jwt',
        description='Get all conversations for current user',
        responses={
            200: 'Success',
            401: 'Unauthorized'
        }
    )
    @friends_ns.marshal_list_with(conversation_model)
    def get(self):
        '''List all conversations'''
        pass  # Implementation is in friends_view.py

# Custom Swagger UI configuration
api.documentation = {
    'tags': [
        {'name': 'auth', 'description': 'Authentication endpoints'},
        {'name': 'users', 'description': 'User management endpoints'},
        {'name': 'events', 'description': 'Event management endpoints'},
        {'name': 'yaps', 'description': 'Yap (post) management endpoints'},
        {'name': 'marketplace', 'description': 'Marketplace and product endpoints'},
        {'name': 'friends', 'description': 'Friends and messaging endpoints'}
    ],
    'security': [{'jwt': []}],
    'securityDefinitions': {
        'jwt': {
            'type': 'apiKey',
            'in': 'header',
            'name': 'Authorization',
            'description': 'JWT Authorization header using the Bearer scheme. Example: "Bearer {token}"'
        }
    }
}

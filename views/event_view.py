from models import db, Users, Events, Comment_events
from flask import request, jsonify, Blueprint,make_response
from werkzeug.security import generate_password_hash
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import or_, func
from datetime import datetime
import base64
from flask import request
import json
import os
import boto3
import base64
from dotenv import load_dotenv
load_dotenv()

event_bp = Blueprint('event_bp', __name__)

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

@event_bp.route('/events', methods=['GET'])
def get_events():
    events = Events.query.all()
    output = [{
        'eventId': event.id,
        'title': event.title,
        'description': event.description,
        'poster': event.image_url if event.image_url else None,
        'start_time': event.start_time,
        'end_time': event.end_time,
        'date': event.date_of_event.strftime('%d %b %Y'),
        'entry_fee': event.entry_fee,
        'category': event.category,
        'comments': [{
            'id': comment.id,
            'text': comment.text,
            'image': comment.user.image_url if comment.user.image_url else None,
            'username': comment.user.username,
            'dateCreated': comment.created_at
        } for comment in event.comments]
    } for event in events]
    return make_response(jsonify(output), 200)
    

@event_bp.route('/events/<int:event_id>', methods=['GET'])
def get_specific_event(event_id):
    event = Events.query.get(event_id)
    if not event:
        return jsonify({'message': 'Event not found'}), 404
    
    output = {
        'eventId': event.id, 
        'title': event.title, 
        'poster': event.image_url if event.image_url else None,
        'description': event.description, 
        'start_time': event.start_time.strftime('%H:%M') if event.start_time else None,
        'end_time': event.end_time.strftime('%H:%M') if event.end_time else None,
        'date': event.date_of_event.strftime('%Y-%m-%d') if event.date_of_event else None,
        'entry_fee': event.entry_fee,
        'category': event.category,
        'comments': [{
            'id': comment.id,
            'text': comment.text, 
            'image': comment.user.image_url if comment.user.image_url else None,
            'username': comment.user.username, 
            'dateCreated': comment.created_at 
        } for comment in event.comments]
    }
    
    return jsonify(output)


# Route to add a new event
@event_bp.route('/add-event', methods=['POST'])
@jwt_required()
def add_event():
    try:
        current_user = get_jwt_identity()

        # Determine if the request is JSON or form-data
        if request.is_json:
            data = request.get_json()
        else:
            data = {key: request.form[key] for key in request.form}

        # Extract event details
        title = data.get('title')
        description = data.get('description')
        date_of_event_str = data.get('date_of_event')
        start_time_str = data.get('start_time')
        end_time_str = data.get('end_time')
        entry_fee = data.get('entry_fee')
        category = data.get('category')

        # Check for missing fields
        if not all([title, description, date_of_event_str, start_time_str, end_time_str, entry_fee, category]):
            return make_response(jsonify({"error": "Missing required fields"}), 400)

        # Parse date and time strings into datetime objects
        date_of_event = datetime.strptime(date_of_event_str, "%Y-%m-%d")
        start_time = datetime.strptime(start_time_str, '%I:%M %p').time()
        end_time = datetime.strptime(end_time_str, '%I:%M %p').time()

        # Combine date and time into datetime objects
        start_datetime = datetime.combine(date_of_event, start_time)
        end_datetime = datetime.combine(date_of_event, end_time)

        # Access the image file
        image_file = request.files.get('image_url')

        # Handle R2 image upload
        image_key = None
        if image_file:
            image_key = f'event_images/{current_user}/{image_file.filename}'
            try:
                s3_client.upload_fileobj(image_file, R2_BUCKET_NAME, image_key)
            except Exception as e:
                return jsonify({'error': f"Failed to upload image: {str(e)}"}), 500

        # Use the uploaded image's R2 URL
        r2_image_url = f"{IMAGE_PREFIX}/{image_key}" if image_key else None

        # Create new event
        new_event = Events(
            title=title,
            description=description,
            start_time=start_datetime,
            end_time=end_datetime,
            date_of_event=date_of_event,
            entry_fee=entry_fee,
            category=category,
            image_url=r2_image_url,  # Store R2 URL here
            user_id=current_user
        )

        db.session.add(new_event)
        db.session.commit()

        return make_response(jsonify({"message": "New event created!"}), 201)
    except Exception as e:
        db.session.rollback()
        return make_response(jsonify({"error": str(e)}), 500)


# Route to update an event
@event_bp.route('/update-event/<int:event_id>', methods=['PUT'])
@jwt_required()
def update_event(event_id):
    current_user = get_jwt_identity()
    event = Events.query.filter_by(id=event_id, user_id=current_user).first()
    
    if not event:
        return jsonify({'message': 'Event not found or you are not authorized to update this event'}), 404

    data = request.form  # Handle form data for file uploads

    # Extract data from the request form
    title = data.get('title')
    description = data.get('description')
    date_of_event_str = data.get('date_of_event')
    start_time_str = data.get('start_time')
    end_time_str = data.get('end_time')
    entry_fee = data.get('entry_fee')
    category = data.get('category')

    # Check if all required fields are present
    if not all([title, description]):
        return make_response(jsonify({"error": "Missing required fields"}), 400)

    
    # Parse date and time strings into datetime objects
    date_of_event = datetime.strptime(date_of_event_str, "%Y-%m-%d")
    start_time = datetime.strptime(start_time_str, '%I:%M %p').time()
    end_time = datetime.strptime(end_time_str, '%I:%M %p').time()

    # Combine date and time into datetime objects
    start_datetime = datetime.combine(date_of_event, start_time)
    end_datetime = datetime.combine(date_of_event, end_time)
   

    # Access the image file
    image_file = request.files.get('image_url')

    # Handle R2 image upload
    image_key = None
    if image_file:
        image_key = f'event_images/{current_user}/{image_file.filename}'
        try:
            s3_client.upload_fileobj(image_file, R2_BUCKET_NAME, image_key)
        except Exception as e:
            return jsonify({'error': f"Failed to upload image: {str(e)}"}), 500

    # Use the uploaded image's R2 URL
    r2_image_url = f"{IMAGE_PREFIX}/{image_key}" if image_key else None

    # Update event data
    event.title = title
    event.description = description
    event.start_datetime = start_datetime
    event.end_datetime = end_datetime
    event.entry_fee = entry_fee
    event.category = category
    if r2_image_url:
        event.image_url = r2_image_url  # Update image URL if a new one was uploaded

    db.session.commit()

    return jsonify({'message': 'Event updated successfully'})
@event_bp.route('/delete-event/<int:event_id>', methods=['DELETE'])
@jwt_required()
def delete_event(event_id):
    current_user = get_jwt_identity()
    event = Events.query.filter_by(id=event_id, user_id=current_user).first()
    if not event:
        return jsonify({'message': 'Event not found or you are not authorized to delete this event'}), 404
    db.session.delete(event)
    db.session.commit()
    return jsonify({'message': 'Event deleted successfully'})

@event_bp.route('/comment-event/<int:event_id>', methods=['POST'])
@jwt_required()
def comment_event(event_id):
    current_user = get_jwt_identity()
    event = Events.query.get(event_id)
    
    if not event:
        return jsonify({'message': 'Event not found'}), 404
    
    data = request.get_json()
    comment_text = data.get('text')
    
    if not comment_text:
        return jsonify({'message': 'Comment text is required'}), 400
    
    new_comment = Comment_events(
        text=comment_text,
        user_id=current_user,
        event_id=event_id
    )
    
    db.session.add(new_comment)
    db.session.commit()
    
    return jsonify({'message': 'Comment added successfully'})

@event_bp.route('/update-comment-event/<int:comment_id>', methods=['PUT'])
@jwt_required()
def update_comment_event(comment_id):
    current_user = get_jwt_identity()
    comment = Comment_events.query.get(comment_id)
    
    if not comment:
        return jsonify({'message': 'Comment not found'}), 404
    
    if comment.user_id != current_user:
        return jsonify({'message': 'You are not authorized to update this comment'}), 403
    
    data = request.get_json()
    new_comment_text = data.get('text')
    
    if not new_comment_text:
        return jsonify({'message': 'New comment text is required'}), 400
    
    comment.text = new_comment_text
    db.session.commit()
    
    return jsonify({'message': 'Comment updated successfully'})

@event_bp.route('/delete-comment-event/<int:comment_id>', methods=['DELETE'])
@jwt_required()
def delete_comment(comment_id):
    current_user = get_jwt_identity()
    comment = Comment_events.query.get(comment_id)
    
    if not comment:
        return jsonify({'message': 'Comment not found'}), 404
    
    if comment.user_id != current_user:
        return jsonify({'message': 'You are not authorized to delete this comment'}), 403
    
    db.session.delete(comment)
    db.session.commit()
    
    return jsonify({'message': 'Comment deleted successfully'})

def get_events_by_category(category):
    events = Events.query.filter_by(category=category).all()
    
    output = []
    for event in events:
        event_data = {
            'eventId': event.id,
        'title': event.title,
        'description': event.description,
        'poster': event.image_url if event.image_url else None,
        'start_time': event.start_time,
        'end_time': event.end_time,
        'date': event.date_of_event.strftime('%d %b %Y'),
        'entry_fee': event.entry_fee,
        'category': event.category,
        'comments': [{
            'id': comment.id,
            'text': comment.text,
            'image': comment.user.image_url if comment.user.image_url else None,
            'username': comment.user.username,
            'dateCreated': comment.created_at
        } for comment in event.comments]
        }
        output.append(event_data)
    
    return jsonify({'events': output})

@event_bp.route('/events/fun', methods=['GET'])
def get_funny_events():
    return get_events_by_category('Fun')

# Route to get educational events
@event_bp.route('/events/educational', methods=['GET'])
def get_educational_events():
    return get_events_by_category('Educational')

# Route to get social events
@event_bp.route('/events/social', methods=['GET'])
def get_events_events():
    return get_events_by_category('Social')

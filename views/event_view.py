from models import db, Users, Events, Comment_events, EventTicketGroup, CommentEventLike
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

def _serialize_ticket_group(group):
    return {
        'id': group.id,
        'name': group.name,
        'price': group.price,
        'quantity': group.quantity,
        'ticketsPerGroup': group.tickets_per_group,
        'description': group.description,
        'createdAt': group.created_at.isoformat() if group.created_at else None,
        'updatedAt': group.updated_at.isoformat() if group.updated_at else None,
    }


def _serialize_comment(comment, current_user_id=None):
    likes = comment.likes or []
    replies = sorted(comment.replies or [], key=lambda r: r.created_at)
    return {
        'id': comment.id,
        'text': comment.text,
        'createdAt': comment.created_at.isoformat() if comment.created_at else None,
        'updatedAt': comment.updated_at.isoformat() if comment.updated_at else None,
        'user': {
            'id': comment.user.id if comment.user else None,
            'username': comment.user.username if comment.user else None,
            'avatar': comment.user.avatar if comment.user else None,
        },
        'likesCount': len(likes),
        'likedByCurrentUser': any(like.user_id == current_user_id for like in likes) if current_user_id else False,
        'parentCommentId': comment.parent_comment_id,
        'replies': [_serialize_comment(reply, current_user_id) for reply in replies],
    }


def _serialize_event(event, current_user_id=None):
    comments = [c for c in event.comments if c.parent_comment_id is None]
    comments_sorted = sorted(comments, key=lambda c: c.created_at)
    return {
        'eventId': event.id,
        'title': event.title,
        'description': event.description,
        'poster': event.image_url if event.image_url else None,
        'start_time': event.start_time.isoformat() if event.start_time else None,
        'end_time': event.end_time.isoformat() if event.end_time else None,
        'date': event.date_of_event.strftime('%d %b %Y') if event.date_of_event else None,
        'date_of_event': event.date_of_event.strftime('%Y-%m-%d') if event.date_of_event else None,
        'entry_fee': event.entry_fee,
        'category': event.category,
        'user_id': event.user_id,
        'username': event.user.username if event.user else None,
        'userimage': event.user.avatar if event.user else None,
        'ticketGroups': [_serialize_ticket_group(group) for group in sorted(event.ticket_groups, key=lambda g: g.created_at)],
        'comments': [_serialize_comment(comment, current_user_id) for comment in comments_sorted],
    }


@event_bp.route('/events', methods=['GET'])
@jwt_required(optional=True)
def get_events():
    events = Events.query.order_by(Events.created_at.desc()).all()
    current_user = get_jwt_identity()
    output = [_serialize_event(event, current_user) for event in events]
    return make_response(jsonify(output), 200)
    

@event_bp.route('/events/<string:event_id>', methods=['GET'])
@jwt_required(optional=True)
def get_specific_event(event_id):
    event = Events.query.get(event_id)
    if not event:
        return jsonify({'message': 'Event not found'}), 404
    current_user = get_jwt_identity()
    output = _serialize_event(event, current_user)
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

        ticket_groups_raw = data.get('ticket_groups')

        # Check for missing fields
        if not all([title, description, date_of_event_str, start_time_str, end_time_str, category]):
            return make_response(jsonify({"error": "Missing required fields"}), 400)

        # Parse date and time strings into datetime objects
        date_of_event = datetime.strptime(date_of_event_str, "%Y-%m-%d")
        try:
            start_time = datetime.strptime(start_time_str, '%I:%M %p').time()
            end_time = datetime.strptime(end_time_str, '%I:%M %p').time()
        except ValueError:
            return make_response(jsonify({"error": "Invalid time format. Expected HH:MM AM/PM"}), 400)

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

        ticket_groups = []
        if ticket_groups_raw:
            if isinstance(ticket_groups_raw, str):
                try:
                    ticket_groups_data = json.loads(ticket_groups_raw)
                except json.JSONDecodeError:
                    ticket_groups_data = []
            else:
                ticket_groups_data = ticket_groups_raw

            for group in ticket_groups_data or []:
                name = group.get('name')
                price = group.get('price')
                quantity = group.get('quantity')
                tickets_per_group = group.get('ticketsPerGroup', 1)
                description_group = group.get('description')

                if not name or price is None or quantity is None:
                    continue

                ticket_group = EventTicketGroup(
                    event=new_event,
                    name=name,
                    price=float(price),
                    quantity=int(quantity),
                    tickets_per_group=int(tickets_per_group) if tickets_per_group else 1,
                    description=description_group
                )
                ticket_groups.append(ticket_group)
                db.session.add(ticket_group)

        db.session.commit()

        return make_response(jsonify({
            "message": "New event created!",
            "event": _serialize_event(new_event, current_user)
        }), 201)
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

    # Allow JSON payloads for API clients
    if not data:
        if request.is_json:
            data = request.get_json()
        else:
            data = {}

    # Extract data from the request form
    title = data.get('title')
    description = data.get('description')
    date_of_event_str = data.get('date_of_event')
    start_time_str = data.get('start_time')
    end_time_str = data.get('end_time')
    entry_fee = data.get('entry_fee')
    category = data.get('category')
    ticket_groups_raw = data.get('ticket_groups')

    # Check if all required fields are present
    if not all([title, description]):
        return make_response(jsonify({"error": "Missing required fields"}), 400)

    
    start_datetime = event.start_time
    end_datetime = event.end_time
    if date_of_event_str and start_time_str and end_time_str:
        date_of_event = datetime.strptime(date_of_event_str, "%Y-%m-%d")
        start_time = datetime.strptime(start_time_str, '%I:%M %p').time()
        end_time = datetime.strptime(end_time_str, '%I:%M %p').time()
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
    event.start_time = start_datetime
    event.end_time = end_datetime
    event.entry_fee = entry_fee
    event.category = category
    if r2_image_url:
        event.image_url = r2_image_url  # Update image URL if a new one was uploaded

    if ticket_groups_raw is not None:
        EventTicketGroup.query.filter_by(event_id=event.id).delete()

        if isinstance(ticket_groups_raw, str):
            try:
                ticket_groups_data = json.loads(ticket_groups_raw)
            except json.JSONDecodeError:
                ticket_groups_data = []
        else:
            ticket_groups_data = ticket_groups_raw

        for group in ticket_groups_data or []:
            name = group.get('name')
            price = group.get('price')
            quantity = group.get('quantity')
            tickets_per_group = group.get('ticketsPerGroup', 1)
            description_group = group.get('description')

            if not name or price is None or quantity is None:
                continue

            ticket_group = EventTicketGroup(
                event=event,
                name=name,
                price=float(price),
                quantity=int(quantity),
                tickets_per_group=int(tickets_per_group) if tickets_per_group else 1,
                description=description_group
            )
            db.session.add(ticket_group)

    db.session.commit()

    return jsonify({'message': 'Event updated successfully', 'event': _serialize_event(event, current_user)})
@event_bp.route('/delete-event/<string:event_id>', methods=['DELETE'])
@jwt_required()
def delete_event(event_id):
    current_user = get_jwt_identity()
    event = Events.query.filter_by(id=event_id, user_id=current_user).first()
    if not event:
        return jsonify({'message': 'Event not found or you are not authorized to delete this event'}), 404
    db.session.delete(event)
    db.session.commit()
    return jsonify({'message': 'Event deleted successfully'})

@event_bp.route('/comment-event/<string:event_id>', methods=['POST'])
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

    parent_id = data.get('parent_comment_id')
    parent_comment = None
    if parent_id:
        parent_comment = Comment_events.query.filter_by(id=parent_id, event_id=event_id).first()
        if not parent_comment:
            return jsonify({'message': 'Parent comment not found'}), 404

    new_comment = Comment_events(
        text=comment_text,
        user_id=current_user,
        event_id=event_id,
        parent_comment_id=parent_comment.id if parent_comment else None
    )

    db.session.add(new_comment)
    db.session.commit()

    return jsonify({'message': 'Comment added successfully', 'comment': _serialize_comment(new_comment, current_user)})

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

    return jsonify({'message': 'Comment updated successfully', 'comment': _serialize_comment(comment, current_user)})

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


@event_bp.route('/comment-event/<string:event_id>/likes/<int:comment_id>', methods=['POST'])
@jwt_required()
def toggle_comment_like(event_id, comment_id):
    current_user = get_jwt_identity()
    comment = Comment_events.query.filter_by(id=comment_id, event_id=event_id).first()

    if not comment:
        return jsonify({'message': 'Comment not found'}), 404

    existing_like = CommentEventLike.query.filter_by(comment_id=comment_id, user_id=current_user).first()

    if existing_like:
        db.session.delete(existing_like)
        db.session.commit()
        liked = False
    else:
        new_like = CommentEventLike(comment_id=comment_id, user_id=current_user)
        db.session.add(new_like)
        db.session.commit()
        liked = True

    likes_count = CommentEventLike.query.filter_by(comment_id=comment_id).count()

    return jsonify({
        'message': 'Comment like updated',
        'likesCount': likes_count,
        'likedByCurrentUser': liked
    })

def get_events_by_category(category):
    events = Events.query.filter_by(category=category).all()
    current_user = get_jwt_identity()
    output = [_serialize_event(event, current_user) for event in events]

    return jsonify({'events': output})

@event_bp.route('/events/fun', methods=['GET'])
@jwt_required(optional=True)
def get_funny_events():
    return get_events_by_category('Fun')

# Route to get educational events
@event_bp.route('/events/educational', methods=['GET'])
@jwt_required(optional=True)
def get_educational_events():
    return get_events_by_category('Educational')

# Route to get social events
@event_bp.route('/events/social', methods=['GET'])
@jwt_required(optional=True)
def get_events_events():
    return get_events_by_category('Social')

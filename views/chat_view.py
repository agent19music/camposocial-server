from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from werkzeug.utils import secure_filename
import os
from models import Message, Reaction, ChatMedia, db, Friendship, Users # Import your models
from. import redis_client  # Import your Redis client instance
from. import upload_media_to_r2  # Import the R2 upload function

chat_bp = Blueprint('chat', __name__)

@chat_bp.route('/messages/<int:friend_id>', methods=['POST'])
@jwt_required()
def send_message(friend_id):
    """
    Send a message to a friend.
    """
    try:
        user_id = get_jwt_identity()
        data = request.form
        content = data.get('content')
        reply_to_id = data.get('reply_to_id')
        files = request.files.getlist('media')

        if not content:
            return jsonify({"error": "Content is required"}), 400

        # Encryption logic (using openpgp)
        #... (Your openpgp encryption code here, encrypt content)
        encrypted_content = content  # Placeholder - replace with actual encrypted content

        new_message = Message(
            encrypted_content=encrypted_content,
            user_id=user_id,
            timestamp=datetime.utcnow(),
            reply_to_id=reply_to_id
        )
        db.session.add(new_message)
        db.session.flush()  # Get the message id

        # Handle media uploads
        if files:
            for file in files:
                if file:
                    filename = secure_filename(file.filename)
                    file_ext = filename.rsplit('.', 1).lower()
                    media_type = 'image' if file_ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'avif'] else 'video'
                    
                    # Construct the S3 (R2) file path
                    s3_path = f"messages/{user_id}/{filename}"
                    
                    try:
                        media_url = upload_media_to_r2(file.read(), s3_path, file.content_type)
                        chat_media = ChatMedia(media_url=media_url, media_type=media_type, message_id=new_message.id)
                        db.session.add(chat_media)
                    except Exception as e:
                        db.session.rollback()
                        return jsonify({"error": f"Media upload failed: {str(e)}"}), 500

        db.session.commit()

        # Invalidate Redis cache
        redis_key = f"messages:{user_id}:{friend_id}"
        redis_client.delete(redis_key)

        return jsonify({
            "message_id": new_message.id,
            "timestamp": new_message.timestamp.isoformat(),  # Use isoformat for datetime
            "media": [{"media_url": m.media_url, "media_type": m.media_type} for m in new_message.media]
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@chat_bp.route('/messages/<int:friend_id>', methods=['GET'])
@jwt_required()
def get_messages(friend_id):
    """
    Get paginated messages with a friend.
    """
    try:
        user_id = get_jwt_identity()
        batch_size = int(request.args.get('batch_size', 10))
        last_message_id = request.args.get('last_message_id')

        redis_key = f"messages:{user_id}:{friend_id}:{last_message_id}" if last_message_id else f"messages:{user_id}:{friend_id}"
        cached_messages = redis_client.get(redis_key)

        if cached_messages:
            messages_data = eval(cached_messages)  # Use json.loads if you store it as a JSON string
            messages = [Message(**msg) for msg in messages_data]
        else:
            query = Message.query.filter(
                ((Message.user_id == user_id) & (Message.friend_id == friend_id)) |
                ((Message.user_id == friend_id) & (Message.friend_id == user_id))
            ).order_by(Message.timestamp.desc())

            if last_message_id:
                query = query.filter(Message.id < last_message_id)

            messages = query.limit(batch_size).all()

            # Cache the messages
            redis_client.set(redis_key, str([msg.to_dict() for msg in messages]))
            redis_client.expire(redis_key, 3600)  # Expire after 1 hour

        return jsonify({"messages": [msg.to_dict() for msg in messages]}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@chat_bp.route('/messages/<int:message_id>', methods=['PUT'])
@jwt_required()
def edit_message(message_id):
    """
    Edit a message.
    """
    try:
        user_id = get_jwt_identity()
        message = Message.query.get_or_404(message_id)

        if message.user_id!= user_id:
            return jsonify({"error": "You are not authorized to edit this message."}), 403

        data = request.get_json()
        new_content = data.get('content')

        if not new_content:
            return jsonify({"error": "New content is required."}), 400

        # Encryption logic (using openpgp)
        #... (Your openpgp encryption code here, encrypt new_content)
        encrypted_content = new_content  # Placeholder - replace with actual encrypted content

        message.encrypted_content = encrypted_content
        db.session.commit()

        # Invalidate Redis cache
        redis_key = f"messages:{user_id}:{message.friend_id}"
        redis_client.delete(redis_key)

        return jsonify({"message": "Message updated successfully!"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@chat_bp.route('/messages/<int:message_id>', methods=['DELETE'])
@jwt_required()
def delete_message(message_id):
    """
    Delete a message.
    """
    try:
        user_id = get_jwt_identity()
        message = Message.query.get_or_404(message_id)

        if message.user_id!= user_id:
            return jsonify({"error": "You are not authorized to delete this message."}), 403

        db.session.delete(message)  # Hard delete
        db.session.commit()

        # Invalidate Redis cache
        redis_key = f"messages:{user_id}:{message.friend_id}"
        redis_client.delete(redis_key)

        return jsonify({"message": "Message deleted successfully!"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@chat_bp.route('/messages/<int:message_id>/reactions', methods=['POST'])
@jwt_required()
def add_reaction(message_id):
    """
    Add a reaction to a message.
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        reaction_type = data.get('reaction_type')

        if not reaction_type:
            return jsonify({"error": "Reaction type is required."}), 400

        # Check if the user has already reacted to this message
        existing_reaction = Reaction.query.filter_by(message_id=message_id, user_id=user_id).first()
        if existing_reaction:
            return jsonify({"error": "You have already reacted to this message."}), 400

        new_reaction = Reaction(
            reaction_type=reaction_type,
            message_id=message_id,
            user_id=user_id
        )
        db.session.add(new_reaction)
        db.session.commit()

        # Invalidate Redis cache
        message = Message.query.get_or_404(message_id)
        redis_key = f"messages:{user_id}:{message.friend_id}"
        redis_client.delete(redis_key)

        return jsonify({"message": "Reaction added successfully!"}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@chat_bp.route('/chat-list', methods=['GET'])
@jwt_required()
def get_chat_list():
    """
    Get a list of users the current user has chats with.
    """
    try:
        user_id = get_jwt_identity()

        # Get a list of friends the user has chats with
        friends_with_chats = db.session.query(Friendship.friend_id).filter(
            Friendship.user_id == user_id,
            Friendship.status == 'accepted'
        ).outerjoin(Message, (Message.user_id == Friendship.friend_id) | (Message.user_id == user_id)).filter(
            Message.id.isnot(None)
        ).distinct().all()

        # Extract the friend IDs
        friend_ids = [friend.friend_id for friend in friends_with_chats]

        # Fetch user details for the friends (you might want to optimize this with a join)
        friends = Users.query.filter(Users.id.in_(friend_ids)).all()

        # Return the list of friends with their details
        return jsonify({
            "chat_list": [
                {
                    "id": friend.id,
                    "first_name": friend.first_name,
                    "last_name": friend.last_name,
                    #... other user details you want to include
                } for friend in friends
            ]
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500        
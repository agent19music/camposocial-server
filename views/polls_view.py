from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Poll, PollOption, PollVote, Users, Group, GroupMember, EnhancedNotification
from datetime import datetime, timedelta
from sqlalchemy import and_, or_, func
from cuid import cuid

polls_bp = Blueprint('polls', __name__)

# ============= Helper Functions =============
def can_create_poll_in_group(group_id, user_id):
    """Check if user can create polls in a group"""
    member = GroupMember.query.filter_by(
        group_id=group_id,
        user_id=user_id,
        is_active=True
    ).first()
    
    if not member:
        return False
    return member.role in ['admin', 'moderator']

def can_view_poll(poll, user_id):
    """Check if user can view a poll"""
    # Campus-wide polls are visible to all
    if not poll.group_id:
        return True
    
    # Group polls - check membership
    group = Group.query.get(poll.group_id)
    if not group or not group.is_active:
        return False
    
    # Public group polls can be viewed by all
    if group.privacy_type == 'public':
        return True
    
    # Private/secret group polls - check membership
    member = GroupMember.query.filter_by(
        group_id=poll.group_id,
        user_id=user_id,
        is_active=True
    ).first()
    
    return member is not None

def has_user_voted(poll_id, user_id):
    """Check if user has already voted in a poll"""
    vote = PollVote.query.filter_by(
        poll_id=poll_id,
        user_id=user_id
    ).first()
    return vote is not None

def calculate_poll_results(poll_id):
    """Calculate and return poll results"""
    poll = Poll.query.get(poll_id)
    if not poll:
        return None
    
    options = PollOption.query.filter_by(poll_id=poll_id).order_by(PollOption.order_index).all()
    
    results = []
    for option in options:
        percentage = 0
        if poll.total_votes > 0:
            percentage = round((option.vote_count / poll.total_votes) * 100, 1)
        
        results.append({
            'option_id': option.id,
            'option_text': option.option_text,
            'vote_count': option.vote_count,
            'percentage': percentage
        })
    
    return results

# ============= Poll CRUD Operations =============

@polls_bp.route('/polls', methods=['POST'])
@jwt_required()
def create_poll():
    """Create a new poll"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        # Validate required fields
        if not data.get('title'):
            return jsonify({'error': 'Poll title is required'}), 400
        
        if not data.get('options') or len(data['options']) < 2:
            return jsonify({'error': 'At least 2 options are required'}), 400
        
        # Check if it's a group poll
        group_id = data.get('group_id')
        if group_id:
            # Verify user can create polls in this group
            if not can_create_poll_in_group(group_id, user_id):
                return jsonify({'error': 'You do not have permission to create polls in this group'}), 403
        
        # Create poll
        poll = Poll(
            id=cuid(),
            title=data['title'],
            description=data.get('description'),
            creator_id=user_id,
            group_id=group_id,
            poll_type=data.get('poll_type', 'single'),
            category=data.get('category', 'general'),
            is_anonymous=data.get('is_anonymous', False)
        )
        
        # Set end time if provided
        if data.get('duration_hours'):
            poll.ends_at = datetime.utcnow() + timedelta(hours=data['duration_hours'])
        
        db.session.add(poll)
        db.session.flush()
        
        # Add poll options
        for index, option_text in enumerate(data['options']):
            if option_text.strip():  # Ignore empty options
                option = PollOption(
                    poll_id=poll.id,
                    option_text=option_text.strip(),
                    order_index=index
                )
                db.session.add(option)
        
        db.session.commit()
        
        # Send notifications if it's a group poll
        if group_id:
            group = Group.query.get(group_id)
            # Notify group members
            members = GroupMember.query.filter_by(
                group_id=group_id,
                is_active=True
            ).all()
            
            for member in members:
                if member.user_id != user_id:
                    notification = EnhancedNotification(
                        type='POLL_CREATED',
                        priority='medium',
                        recipient_id=member.user_id,
                        sender_id=user_id,
                        poll_id=poll.id,
                        group_id=group_id,
                        title='New Poll',
                        message=f'New poll in {group.name}: "{poll.title}"',
                        action_url=f'/polls/{poll.id}'
                    )
                    db.session.add(notification)
            
            db.session.commit()
        
        return jsonify({
            'message': 'Poll created successfully',
            'poll': {
                'id': poll.id,
                'title': poll.title,
                'description': poll.description,
                'group_id': poll.group_id,
                'category': poll.category,
                'is_anonymous': poll.is_anonymous,
                'ends_at': poll.ends_at.isoformat() if poll.ends_at else None,
                'created_at': poll.created_at.isoformat()
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@polls_bp.route('/polls', methods=['GET'])
@jwt_required()
def get_polls():
    """Get all polls (campus-wide and from user's groups)"""
    try:
        user_id = get_jwt_identity()
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        category = request.args.get('category')
        group_id = request.args.get('group_id')
        active_only = request.args.get('active_only', 'true').lower() == 'true'
        
        # Get user's groups for filtering
        user_groups = GroupMember.query.filter_by(
            user_id=user_id,
            is_active=True
        ).all()
        user_group_ids = [gm.group_id for gm in user_groups]
        
        # Base query
        query = Poll.query.filter(Poll.is_active == True)
        
        # Filter by group if specified
        if group_id:
            query = query.filter(Poll.group_id == group_id)
        else:
            # Show campus-wide polls and polls from user's groups
            query = query.filter(
                or_(
                    Poll.group_id == None,  # Campus-wide polls
                    Poll.group_id.in_(user_group_ids) if user_group_ids else False
                )
            )
        
        # Filter by category
        if category:
            query = query.filter(Poll.category == category)
        
        # Filter active polls only
        if active_only:
            query = query.filter(
                or_(
                    Poll.ends_at == None,
                    Poll.ends_at > datetime.utcnow()
                )
            )
        
        # Order by creation date
        query = query.order_by(Poll.created_at.desc())
        
        # Paginate
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        # Format response
        polls = []
        for poll in paginated.items:
            # Check if user has voted
            has_voted = has_user_voted(poll.id, user_id)
            
            # Get creator info
            creator = Users.query.get(poll.creator_id)
            
            # Get group info if applicable
            group = None
            if poll.group_id:
                group = Group.query.get(poll.group_id)
            
            polls.append({
                'id': poll.id,
                'title': poll.title,
                'description': poll.description,
                'category': poll.category,
                'poll_type': poll.poll_type,
                'is_anonymous': poll.is_anonymous,
                'total_votes': poll.total_votes,
                'has_voted': has_voted,
                'ends_at': poll.ends_at.isoformat() if poll.ends_at else None,
                'is_expired': poll.ends_at < datetime.utcnow() if poll.ends_at else False,
                'creator': {
                    'id': creator.id,
                    'username': creator.username,
                    'display_name': creator.display_name,
                    'avatar': creator.avatar
                } if creator else None,
                'group': {
                    'id': group.id,
                    'name': group.name,
                    'icon_image': group.icon_image
                } if group else None,
                'created_at': poll.created_at.isoformat()
            })
        
        return jsonify({
            'polls': polls,
            'total': paginated.total,
            'pages': paginated.pages,
            'current_page': page
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@polls_bp.route('/polls/<poll_id>', methods=['GET'])
@jwt_required()
def get_poll_details(poll_id):
    """Get detailed information about a specific poll"""
    try:
        user_id = get_jwt_identity()
        
        poll = Poll.query.filter_by(id=poll_id, is_active=True).first()
        if not poll:
            return jsonify({'error': 'Poll not found'}), 404
        
        # Check if user can view this poll
        if not can_view_poll(poll, user_id):
            return jsonify({'error': 'You do not have permission to view this poll'}), 403
        
        # Get poll options
        options = PollOption.query.filter_by(poll_id=poll_id).order_by(PollOption.order_index).all()
        
        # Check if user has voted
        user_vote = PollVote.query.filter_by(
            poll_id=poll_id,
            user_id=user_id
        ).first()
        
        # Get creator info
        creator = Users.query.get(poll.creator_id)
        
        # Get group info if applicable
        group = None
        if poll.group_id:
            group = Group.query.get(poll.group_id)
        
        # Format options
        options_data = []
        show_results = user_vote is not None or (poll.ends_at and poll.ends_at < datetime.utcnow())
        
        for option in options:
            option_data = {
                'id': option.id,
                'option_text': option.option_text,
                'order_index': option.order_index
            }
            
            # Include results if user has voted or poll has ended
            if show_results:
                percentage = 0
                if poll.total_votes > 0:
                    percentage = round((option.vote_count / poll.total_votes) * 100, 1)
                
                option_data.update({
                    'vote_count': option.vote_count,
                    'percentage': percentage,
                    'is_user_choice': user_vote.option_id == option.id if user_vote else False
                })
            
            options_data.append(option_data)
        
        # Get recent voters (non-anonymous polls only)
        recent_voters = []
        if not poll.is_anonymous and show_results:
            recent_votes = db.session.query(PollVote, Users, PollOption).join(
                Users, PollVote.user_id == Users.id
            ).join(
                PollOption, PollVote.option_id == PollOption.id
            ).filter(
                PollVote.poll_id == poll_id
            ).order_by(PollVote.voted_at.desc()).limit(10).all()
            
            for vote, user, option in recent_votes:
                recent_voters.append({
                    'user': {
                        'id': user.id,
                        'username': user.username,
                        'display_name': user.display_name,
                        'avatar': user.avatar
                    },
                    'option': option.option_text,
                    'voted_at': vote.voted_at.isoformat()
                })
        
        return jsonify({
            'id': poll.id,
            'title': poll.title,
            'description': poll.description,
            'category': poll.category,
            'poll_type': poll.poll_type,
            'is_anonymous': poll.is_anonymous,
            'total_votes': poll.total_votes,
            'has_voted': user_vote is not None,
            'show_results': show_results,
            'ends_at': poll.ends_at.isoformat() if poll.ends_at else None,
            'is_expired': poll.ends_at < datetime.utcnow() if poll.ends_at else False,
            'creator': {
                'id': creator.id,
                'username': creator.username,
                'display_name': creator.display_name,
                'avatar': creator.avatar
            } if creator else None,
            'group': {
                'id': group.id,
                'name': group.name,
                'icon_image': group.icon_image
            } if group else None,
            'options': options_data,
            'recent_voters': recent_voters,
            'created_at': poll.created_at.isoformat()
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@polls_bp.route('/polls/<poll_id>/vote', methods=['POST'])
@jwt_required()
def vote_on_poll(poll_id):
    """Vote on a poll"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        # Validate input
        if 'option_id' not in data:
            return jsonify({'error': 'Option ID is required'}), 400
        
        option_id = data['option_id']
        
        # Get poll
        poll = Poll.query.filter_by(id=poll_id, is_active=True).first()
        if not poll:
            return jsonify({'error': 'Poll not found'}), 404
        
        # Check if poll has ended
        if poll.ends_at and poll.ends_at < datetime.utcnow():
            return jsonify({'error': 'This poll has ended'}), 400
        
        # Check if user can view/vote in this poll
        if not can_view_poll(poll, user_id):
            return jsonify({'error': 'You do not have permission to vote in this poll'}), 403
        
        # Check if user has already voted
        existing_vote = PollVote.query.filter_by(
            poll_id=poll_id,
            user_id=user_id
        ).first()
        
        if existing_vote:
            return jsonify({'error': 'You have already voted in this poll'}), 400
        
        # Verify option belongs to this poll
        option = PollOption.query.filter_by(
            id=option_id,
            poll_id=poll_id
        ).first()
        
        if not option:
            return jsonify({'error': 'Invalid option for this poll'}), 400
        
        # Create vote
        vote = PollVote(
            poll_id=poll_id,
            user_id=user_id,
            option_id=option_id
        )
        db.session.add(vote)
        
        # Update vote counts
        option.vote_count += 1
        poll.total_votes += 1
        
        db.session.commit()
        
        # Get updated results
        results = calculate_poll_results(poll_id)
        
        # Send notification to poll creator
        if poll.creator_id != user_id:
            notification = EnhancedNotification(
                type='POLL_VOTE',
                priority='low',
                recipient_id=poll.creator_id,
                sender_id=user_id,
                poll_id=poll_id,
                title='New Poll Vote',
                message=f'Someone voted on your poll: "{poll.title}"',
                action_url=f'/polls/{poll_id}'
            )
            db.session.add(notification)
            db.session.commit()
        
        return jsonify({
            'message': 'Vote recorded successfully',
            'results': results,
            'total_votes': poll.total_votes
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@polls_bp.route('/polls/<poll_id>/results', methods=['GET'])
@jwt_required()
def get_poll_results(poll_id):
    """Get poll results"""
    try:
        user_id = get_jwt_identity()
        
        poll = Poll.query.filter_by(id=poll_id, is_active=True).first()
        if not poll:
            return jsonify({'error': 'Poll not found'}), 404
        
        # Check if user can view this poll
        if not can_view_poll(poll, user_id):
            return jsonify({'error': 'You do not have permission to view this poll'}), 403
        
        # Check if user can see results
        has_voted = has_user_voted(poll_id, user_id)
        is_expired = poll.ends_at < datetime.utcnow() if poll.ends_at else False
        is_creator = poll.creator_id == user_id
        
        if not (has_voted or is_expired or is_creator):
            return jsonify({'error': 'You must vote first to see the results'}), 403
        
        # Get results
        results = calculate_poll_results(poll_id)
        
        # Get voter demographics (for non-anonymous polls)
        demographics = None
        if not poll.is_anonymous and is_creator:
            # This could include breakdown by user categories, join dates, etc.
            demographics = {
                'total_voters': poll.total_votes,
                'participation_rate': 0  # Could calculate based on group members
            }
        
        return jsonify({
            'poll_id': poll_id,
            'title': poll.title,
            'total_votes': poll.total_votes,
            'results': results,
            'demographics': demographics,
            'is_anonymous': poll.is_anonymous,
            'ends_at': poll.ends_at.isoformat() if poll.ends_at else None,
            'is_expired': is_expired
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@polls_bp.route('/polls/<poll_id>', methods=['DELETE'])
@jwt_required()
def delete_poll(poll_id):
    """Delete a poll (creator only)"""
    try:
        user_id = get_jwt_identity()
        
        poll = Poll.query.filter_by(id=poll_id, is_active=True).first()
        if not poll:
            return jsonify({'error': 'Poll not found'}), 404
        
        # Check if user is the creator or group admin
        is_creator = poll.creator_id == user_id
        is_group_admin = False
        
        if poll.group_id:
            member = GroupMember.query.filter_by(
                group_id=poll.group_id,
                user_id=user_id,
                is_active=True
            ).first()
            if member and member.role == 'admin':
                is_group_admin = True
        
        if not (is_creator or is_group_admin):
            return jsonify({'error': 'You do not have permission to delete this poll'}), 403
        
        # Soft delete
        poll.is_active = False
        db.session.commit()
        
        return jsonify({'message': 'Poll deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ============= Trending Polls =============

@polls_bp.route('/polls/trending', methods=['GET'])
@jwt_required()
def get_trending_polls():
    """Get trending polls (most votes in last 24 hours)"""
    try:
        user_id = get_jwt_identity()
        
        # Get user's groups
        user_groups = GroupMember.query.filter_by(
            user_id=user_id,
            is_active=True
        ).all()
        user_group_ids = [gm.group_id for gm in user_groups]
        
        # Query for trending polls
        trending = db.session.query(
            Poll,
            func.count(PollVote.id).label('recent_votes')
        ).outerjoin(
            PollVote,
            and_(
                PollVote.poll_id == Poll.id,
                PollVote.voted_at >= datetime.utcnow() - timedelta(hours=24)
            )
        ).filter(
            Poll.is_active == True,
            or_(
                Poll.ends_at == None,
                Poll.ends_at > datetime.utcnow()
            ),
            or_(
                Poll.group_id == None,
                Poll.group_id.in_(user_group_ids) if user_group_ids else False
            )
        ).group_by(Poll.id).order_by(
            func.count(PollVote.id).desc()
        ).limit(10).all()
        
        # Format response
        polls = []
        for poll, recent_votes in trending:
            # Get creator info
            creator = Users.query.get(poll.creator_id)
            
            # Check if user has voted
            has_voted = has_user_voted(poll.id, user_id)
            
            polls.append({
                'id': poll.id,
                'title': poll.title,
                'description': poll.description,
                'category': poll.category,
                'total_votes': poll.total_votes,
                'recent_votes': recent_votes,
                'has_voted': has_voted,
                'ends_at': poll.ends_at.isoformat() if poll.ends_at else None,
                'creator': {
                    'id': creator.id,
                    'username': creator.username,
                    'display_name': creator.display_name
                } if creator else None,
                'created_at': poll.created_at.isoformat()
            })
        
        return jsonify({
            'trending_polls': polls
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============= User's Poll Activity =============

@polls_bp.route('/my-polls', methods=['GET'])
@jwt_required()
def get_user_polls():
    """Get polls created by the current user"""
    try:
        user_id = get_jwt_identity()
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # Query user's polls
        query = Poll.query.filter_by(
            creator_id=user_id,
            is_active=True
        ).order_by(Poll.created_at.desc())
        
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        polls = []
        for poll in paginated.items:
            # Get group info if applicable
            group = None
            if poll.group_id:
                group = Group.query.get(poll.group_id)
            
            polls.append({
                'id': poll.id,
                'title': poll.title,
                'description': poll.description,
                'category': poll.category,
                'total_votes': poll.total_votes,
                'is_anonymous': poll.is_anonymous,
                'ends_at': poll.ends_at.isoformat() if poll.ends_at else None,
                'is_expired': poll.ends_at < datetime.utcnow() if poll.ends_at else False,
                'group': {
                    'id': group.id,
                    'name': group.name
                } if group else None,
                'created_at': poll.created_at.isoformat()
            })
        
        return jsonify({
            'polls': polls,
            'total': paginated.total,
            'pages': paginated.pages,
            'current_page': page
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@polls_bp.route('/my-votes', methods=['GET'])
@jwt_required()
def get_user_votes():
    """Get polls the user has voted in"""
    try:
        user_id = get_jwt_identity()
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # Query polls user has voted in
        query = db.session.query(Poll, PollVote, PollOption).join(
            PollVote, PollVote.poll_id == Poll.id
        ).join(
            PollOption, PollVote.option_id == PollOption.id
        ).filter(
            PollVote.user_id == user_id,
            Poll.is_active == True
        ).order_by(PollVote.voted_at.desc())
        
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        votes = []
        for poll, vote, option in paginated.items:
            # Get creator info
            creator = Users.query.get(poll.creator_id)
            
            votes.append({
                'poll': {
                    'id': poll.id,
                    'title': poll.title,
                    'category': poll.category,
                    'total_votes': poll.total_votes,
                    'creator': {
                        'id': creator.id,
                        'username': creator.username
                    } if creator else None
                },
                'voted_option': option.option_text,
                'voted_at': vote.voted_at.isoformat()
            })
        
        return jsonify({
            'votes': votes,
            'total': paginated.total,
            'pages': paginated.pages,
            'current_page': page
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

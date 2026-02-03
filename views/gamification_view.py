from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import (db, Users, UserPoints, Achievement, UserAchievement, 
                   PointTransaction, Yap, Like, Reply, Events, Products, 
                   Reviews, CommunityMember, EnhancedNotification)
from datetime import datetime, timedelta, date
from sqlalchemy import func, and_, or_, desc
import json

gamification_bp = Blueprint('gamification', __name__)

# ============= Point Values Configuration =============
POINT_VALUES = {
    'post_yap': 5,
    'receive_like': 2,
    'give_like': 1,
    'reply_to_yap': 3,
    'receive_reply': 2,
    'create_event': 20,
    'attend_event': 10,
    'list_product': 15,
    'sell_product': 25,
    'write_review': 10,
    'join_group': 5,
    'create_group': 30,
    'group_post': 7,
    'create_poll': 15,
    'vote_poll': 3,
    'daily_login': 5,
    'streak_bonus': 10,  # Per 7 days
    'friend_added': 5,
    'profile_complete': 50,  # One-time bonus
}

# ============= Helper Functions =============

def get_or_create_user_points(user_id):
    """Get or create UserPoints record for a user"""
    user_points = UserPoints.query.filter_by(user_id=user_id).first()
    if not user_points:
        user_points = UserPoints(
            user_id=user_id,
            points_total=0,
            points_this_week=0,
            points_this_month=0,
            level=1,
            streak_days=0
        )
        db.session.add(user_points)
        db.session.flush()
    return user_points

def award_points(user_id, points, transaction_type, description=None, reference_id=None):
    """Award points to a user and create transaction record"""
    try:
        user_points = get_or_create_user_points(user_id)
        
        # Update points
        user_points.points_total += points
        user_points.points_this_week += points
        user_points.points_this_month += points
        
        # Calculate level (every 100 points = 1 level)
        user_points.level = max(1, (user_points.points_total // 100) + 1)
        
        # Create transaction record
        transaction = PointTransaction(
            user_id=user_id,
            points=points,
            transaction_type=transaction_type,
            description=description or f"Earned {points} points for {transaction_type}",
            reference_id=reference_id
        )
        db.session.add(transaction)
        
        # Check for achievement unlocks
        check_and_award_achievements(user_id, transaction_type)
        
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print(f"Error awarding points: {str(e)}")
        return False

def check_and_award_achievements(user_id, trigger_type=None):
    """Check and award achievements based on user activity"""
    user_points = UserPoints.query.filter_by(user_id=user_id).first()
    if not user_points:
        return
    
    # Get all active achievements
    achievements = Achievement.query.filter_by(is_active=True).all()
    
    for achievement in achievements:
        # Check if user already has this achievement
        existing = UserAchievement.query.filter_by(
            user_id=user_id,
            achievement_id=achievement.id
        ).first()
        
        if existing:
            continue
        
        # Parse criteria (stored as JSON string)
        try:
            criteria = json.loads(achievement.criteria) if achievement.criteria else {}
        except:
            criteria = {}
        
        # Check if achievement criteria is met
        if check_achievement_criteria(user_id, achievement, criteria):
            # Award achievement
            user_achievement = UserAchievement(
                user_id=user_id,
                achievement_id=achievement.id
            )
            db.session.add(user_achievement)
            
            # Award bonus points if specified
            if achievement.points_required:
                award_points(user_id, achievement.points_required, 
                           'achievement_bonus', 
                           f"Achievement unlocked: {achievement.name}")
            
            # Send notification
            notification = EnhancedNotification(
                type='ACHIEVEMENT_UNLOCKED',
                priority='high',
                recipient_id=user_id,
                achievement_id=achievement.id,
                title='Achievement Unlocked!',
                message=f'You earned the "{achievement.name}" badge!',
                action_url='/profile/achievements'
            )
            db.session.add(notification)

def check_achievement_criteria(user_id, achievement, criteria):
    """Check if user meets achievement criteria"""
    # Example criteria checks based on achievement category
    if achievement.category == 'social':
        if 'min_yaps' in criteria:
            yap_count = Yap.query.filter_by(user_id=user_id).count()
            if yap_count < criteria['min_yaps']:
                return False
        
        if 'min_likes_received' in criteria:
            likes_received = Like.query.join(Yap).filter(
                Yap.user_id == user_id
            ).count()
            if likes_received < criteria['min_likes_received']:
                return False
    
    elif achievement.category == 'marketplace':
        if 'min_products_sold' in criteria:
            # Check sold products count
            sold_count = 0  # Would need to track this in Orders
            if sold_count < criteria['min_products_sold']:
                return False
    
    elif achievement.category == 'events':
        if 'min_events_created' in criteria:
            event_count = Events.query.filter_by(user_id=user_id).count()
            if event_count < criteria['min_events_created']:
                return False
    
    elif achievement.category == 'community':
        if 'min_groups_joined' in criteria:
            group_count = CommunityMember.query.filter_by(
                user_id=user_id,
                is_active=True
            ).count()
            if group_count < criteria['min_groups_joined']:
                return False
    
    # Check points requirement
    if achievement.points_required:
        user_points = UserPoints.query.filter_by(user_id=user_id).first()
        if not user_points or user_points.points_total < achievement.points_required:
            return False
    
    return True

def update_daily_streak(user_id):
    """Update user's daily login streak"""
    user_points = get_or_create_user_points(user_id)
    today = date.today()
    
    # Check last activity date
    if user_points.last_activity_date:
        days_diff = (today - user_points.last_activity_date).days
        
        if days_diff == 1:
            # Continuing streak
            user_points.streak_days += 1
            
            # Award streak bonus every 7 days
            if user_points.streak_days % 7 == 0:
                award_points(user_id, POINT_VALUES['streak_bonus'], 
                           'streak_bonus', f"{user_points.streak_days} day streak!")
        elif days_diff > 1:
            # Streak broken
            user_points.streak_days = 1
    else:
        # First activity
        user_points.streak_days = 1
    
    user_points.last_activity_date = today
    
    # Award daily login points
    award_points(user_id, POINT_VALUES['daily_login'], 'daily_login', 'Daily login bonus')
    
    db.session.commit()

def calculate_reputation_scores(user_id):
    """Calculate various reputation scores for a user"""
    user_points = get_or_create_user_points(user_id)
    
    # Seller reputation (based on reviews)
    seller_reviews = Reviews.query.join(Products).filter(
        Products.seller_id == user_id
    ).all()
    if seller_reviews:
        avg_rating = sum(r.rating for r in seller_reviews) / len(seller_reviews)
        user_points.seller_reputation = avg_rating
    
    # Event organizer rating (based on attendance and feedback)
    events_created = Events.query.filter_by(user_id=user_id).count()
    if events_created > 0:
        # Simple calculation - could be enhanced with attendance data
        user_points.event_organizer_rating = min(5.0, events_created * 0.5)
    
    # Study contributor score (based on group posts and helpful content)
    study_posts = 0  # Would need to track this
    user_points.study_contributor_score = study_posts * 10
    
    # Community helper rating (based on replies and helpful interactions)
    helpful_replies = Reply.query.filter_by(user_id=user_id).count()
    user_points.community_helper_rating = min(5.0, helpful_replies * 0.1)
    
    db.session.commit()

# ============= Points API Endpoints =============

@gamification_bp.route('/points/my-points', methods=['GET'])
@jwt_required()
def get_my_points():
    """Get current user's points and level"""
    try:
        user_id = get_jwt_identity()
        user_points = get_or_create_user_points(user_id)
        
        # Update daily streak if needed
        update_daily_streak(user_id)
        
        # Calculate reputation scores
        calculate_reputation_scores(user_id)
        
        return jsonify({
            'points_total': user_points.points_total,
            'points_this_week': user_points.points_this_week,
            'points_this_month': user_points.points_this_month,
            'level': user_points.level,
            'streak_days': user_points.streak_days,
            'next_level_points': (user_points.level * 100) - user_points.points_total,
            'reputation': {
                'seller': user_points.seller_reputation,
                'event_organizer': user_points.event_organizer_rating,
                'study_contributor': user_points.study_contributor_score,
                'community_helper': user_points.community_helper_rating
            }
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@gamification_bp.route('/points/history', methods=['GET'])
@jwt_required()
def get_points_history():
    """Get user's point transaction history"""
    try:
        user_id = get_jwt_identity()
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        query = PointTransaction.query.filter_by(user_id=user_id)\
                                     .order_by(PointTransaction.created_at.desc())
        
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        transactions = []
        for transaction in paginated.items:
            transactions.append({
                'id': transaction.id,
                'points': transaction.points,
                'type': transaction.transaction_type,
                'description': transaction.description,
                'created_at': transaction.created_at.isoformat()
            })
        
        return jsonify({
            'transactions': transactions,
            'total': paginated.total,
            'pages': paginated.pages,
            'current_page': page
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============= Achievements API Endpoints =============

@gamification_bp.route('/achievements', methods=['GET'])
@jwt_required()
def get_all_achievements():
    """Get all available achievements"""
    try:
        user_id = get_jwt_identity()
        
        # Get all achievements
        achievements = Achievement.query.filter_by(is_active=True).all()
        
        # Get user's earned achievements
        user_achievements = UserAchievement.query.filter_by(user_id=user_id).all()
        earned_ids = [ua.achievement_id for ua in user_achievements]
        
        # Format response
        achievement_list = []
        for achievement in achievements:
            achievement_list.append({
                'id': achievement.id,
                'name': achievement.name,
                'description': achievement.description,
                'icon_url': achievement.icon_url,
                'category': achievement.category,
                'badge_type': achievement.badge_type,
                'points_required': achievement.points_required,
                'is_earned': achievement.id in earned_ids,
                'earned_at': next((ua.earned_at.isoformat() for ua in user_achievements 
                                 if ua.achievement_id == achievement.id), None)
            })
        
        # Group by category
        categories = {}
        for achievement in achievement_list:
            category = achievement['category'] or 'general'
            if category not in categories:
                categories[category] = []
            categories[category].append(achievement)
        
        return jsonify({
            'achievements': achievement_list,
            'by_category': categories,
            'total_earned': len(earned_ids),
            'total_available': len(achievements)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@gamification_bp.route('/achievements/my-achievements', methods=['GET'])
@jwt_required()
def get_my_achievements():
    """Get user's earned achievements"""
    try:
        user_id = get_jwt_identity()
        
        # Get user's achievements with details
        user_achievements = db.session.query(UserAchievement, Achievement).join(
            Achievement, UserAchievement.achievement_id == Achievement.id
        ).filter(UserAchievement.user_id == user_id).order_by(
            UserAchievement.earned_at.desc()
        ).all()
        
        achievements = []
        for user_achievement, achievement in user_achievements:
            achievements.append({
                'id': achievement.id,
                'name': achievement.name,
                'description': achievement.description,
                'icon_url': achievement.icon_url,
                'category': achievement.category,
                'badge_type': achievement.badge_type,
                'earned_at': user_achievement.earned_at.isoformat(),
                'progress': user_achievement.progress
            })
        
        return jsonify({
            'achievements': achievements,
            'total': len(achievements)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============= Leaderboards API Endpoints =============

@gamification_bp.route('/leaderboard/weekly', methods=['GET'])
@jwt_required()
def get_weekly_leaderboard():
    """Get weekly points leaderboard"""
    try:
        user_id = get_jwt_identity()
        limit = request.args.get('limit', 20, type=int)
        
        # Get top users by weekly points
        leaderboard = db.session.query(UserPoints, Users).join(
            Users, UserPoints.user_id == Users.id
        ).order_by(UserPoints.points_this_week.desc()).limit(limit).all()
        
        # Get current user's rank
        user_points = UserPoints.query.filter_by(user_id=user_id).first()
        user_rank = None
        if user_points:
            user_rank = UserPoints.query.filter(
                UserPoints.points_this_week > user_points.points_this_week
            ).count() + 1
        
        # Format response
        rankings = []
        for rank, (points, user) in enumerate(leaderboard, 1):
            rankings.append({
                'rank': rank,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'display_name': user.display_name,
                    'avatar': user.avatar
                },
                'points': points.points_this_week,
                'level': points.level,
                'is_current_user': user.id == user_id
            })
        
        return jsonify({
            'leaderboard': rankings,
            'current_user_rank': user_rank,
            'period': 'weekly'
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@gamification_bp.route('/leaderboard/monthly', methods=['GET'])
@jwt_required()
def get_monthly_leaderboard():
    """Get monthly points leaderboard"""
    try:
        user_id = get_jwt_identity()
        limit = request.args.get('limit', 20, type=int)
        
        # Get top users by monthly points
        leaderboard = db.session.query(UserPoints, Users).join(
            Users, UserPoints.user_id == Users.id
        ).order_by(UserPoints.points_this_month.desc()).limit(limit).all()
        
        # Get current user's rank
        user_points = UserPoints.query.filter_by(user_id=user_id).first()
        user_rank = None
        if user_points:
            user_rank = UserPoints.query.filter(
                UserPoints.points_this_month > user_points.points_this_month
            ).count() + 1
        
        # Format response
        rankings = []
        for rank, (points, user) in enumerate(leaderboard, 1):
            rankings.append({
                'rank': rank,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'display_name': user.display_name,
                    'avatar': user.avatar
                },
                'points': points.points_this_month,
                'level': points.level,
                'is_current_user': user.id == user_id
            })
        
        return jsonify({
            'leaderboard': rankings,
            'current_user_rank': user_rank,
            'period': 'monthly'
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@gamification_bp.route('/leaderboard/all-time', methods=['GET'])
@jwt_required()
def get_all_time_leaderboard():
    """Get all-time points leaderboard"""
    try:
        user_id = get_jwt_identity()
        limit = request.args.get('limit', 20, type=int)
        
        # Get top users by total points
        leaderboard = db.session.query(UserPoints, Users).join(
            Users, UserPoints.user_id == Users.id
        ).order_by(UserPoints.points_total.desc()).limit(limit).all()
        
        # Get current user's rank
        user_points = UserPoints.query.filter_by(user_id=user_id).first()
        user_rank = None
        if user_points:
            user_rank = UserPoints.query.filter(
                UserPoints.points_total > user_points.points_total
            ).count() + 1
        
        # Format response
        rankings = []
        for rank, (points, user) in enumerate(leaderboard, 1):
            # Get achievement count
            achievement_count = UserAchievement.query.filter_by(user_id=user.id).count()
            
            rankings.append({
                'rank': rank,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'display_name': user.display_name,
                    'avatar': user.avatar
                },
                'points': points.points_total,
                'level': points.level,
                'achievements': achievement_count,
                'is_current_user': user.id == user_id
            })
        
        return jsonify({
            'leaderboard': rankings,
            'current_user_rank': user_rank,
            'period': 'all-time'
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@gamification_bp.route('/leaderboard/friends', methods=['GET'])
@jwt_required()
def get_friends_leaderboard():
    """Get leaderboard among friends"""
    try:
        user_id = get_jwt_identity()
        
        # Get user's friends (from Friendship model)
        from models import Friendship
        
        # Get accepted friendships
        friendships = Friendship.query.filter(
            and_(
                or_(
                    Friendship.requester_id == user_id,
                    Friendship.addressee_id == user_id
                ),
                Friendship.status == 'accepted'
            )
        ).all()
        
        # Get friend IDs
        friend_ids = []
        for friendship in friendships:
            if friendship.requester_id == user_id:
                friend_ids.append(friendship.addressee_id)
            else:
                friend_ids.append(friendship.requester_id)
        
        # Include current user
        friend_ids.append(user_id)
        
        # Get leaderboard for friends
        leaderboard = db.session.query(UserPoints, Users).join(
            Users, UserPoints.user_id == Users.id
        ).filter(UserPoints.user_id.in_(friend_ids))\
         .order_by(UserPoints.points_total.desc()).all()
        
        # Format response
        rankings = []
        for rank, (points, user) in enumerate(leaderboard, 1):
            rankings.append({
                'rank': rank,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'display_name': user.display_name,
                    'avatar': user.avatar
                },
                'points': points.points_total,
                'level': points.level,
                'streak_days': points.streak_days,
                'is_current_user': user.id == user_id
            })
        
        return jsonify({
            'leaderboard': rankings,
            'total_friends': len(friend_ids) - 1
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============= Admin Functions (for testing) =============

@gamification_bp.route('/admin/init-achievements', methods=['POST'])
@jwt_required()
def initialize_achievements():
    """Initialize default achievements (admin only)"""
    try:
        # This should be restricted to admin users only
        # For now, we'll initialize some default achievements
        
        default_achievements = [
            # Social achievements
            {
                'name': 'First Yap',
                'description': 'Post your first yap',
                'category': 'social',
                'badge_type': 'bronze',
                'criteria': json.dumps({'min_yaps': 1}),
                'points_required': 10
            },
            {
                'name': 'Social Butterfly',
                'description': 'Post 50 yaps',
                'category': 'social',
                'badge_type': 'silver',
                'criteria': json.dumps({'min_yaps': 50}),
                'points_required': 50
            },
            {
                'name': 'Influencer',
                'description': 'Receive 100 likes on your yaps',
                'category': 'social',
                'badge_type': 'gold',
                'criteria': json.dumps({'min_likes_received': 100}),
                'points_required': 100
            },
            # Marketplace achievements
            {
                'name': 'First Sale',
                'description': 'Make your first sale',
                'category': 'marketplace',
                'badge_type': 'bronze',
                'criteria': json.dumps({'min_products_sold': 1}),
                'points_required': 25
            },
            {
                'name': 'Top Seller',
                'description': 'Sell 10 products',
                'category': 'marketplace',
                'badge_type': 'gold',
                'criteria': json.dumps({'min_products_sold': 10}),
                'points_required': 200
            },
            # Event achievements
            {
                'name': 'Event Organizer',
                'description': 'Create your first event',
                'category': 'events',
                'badge_type': 'bronze',
                'criteria': json.dumps({'min_events_created': 1}),
                'points_required': 30
            },
            {
                'name': 'Party Planner',
                'description': 'Create 5 events',
                'category': 'events',
                'badge_type': 'silver',
                'criteria': json.dumps({'min_events_created': 5}),
                'points_required': 100
            },
            # Community achievements
            {
                'name': 'Group Joiner',
                'description': 'Join your first group',
                'category': 'community',
                'badge_type': 'bronze',
                'criteria': json.dumps({'min_groups_joined': 1}),
                'points_required': 10
            },
            {
                'name': 'Community Leader',
                'description': 'Join 10 groups',
                'category': 'community',
                'badge_type': 'gold',
                'criteria': json.dumps({'min_groups_joined': 10}),
                'points_required': 75
            },
            # Academic achievements
            {
                'name': 'Study Buddy',
                'description': 'Help others with study materials',
                'category': 'academic',
                'badge_type': 'silver',
                'criteria': json.dumps({'min_study_posts': 10}),
                'points_required': 50
            }
        ]
        
        for achievement_data in default_achievements:
            # Check if achievement already exists
            existing = Achievement.query.filter_by(name=achievement_data['name']).first()
            if not existing:
                achievement = Achievement(**achievement_data)
                db.session.add(achievement)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Achievements initialized successfully',
            'count': len(default_achievements)
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

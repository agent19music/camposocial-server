"""
Phase 8 Combined Views: Trending/Discovery and Enhanced Notifications
This file combines the trending system and enhanced notifications to complete Phase 8
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import (db, TrendingTopic, Yap, Events, Products, Community, Like, Reply,
                   CommunityMember, Poll, PollVote, Users, EnhancedNotification, 
                   NotificationPreference, Hashtag, YapHashtag, Follow)
from datetime import datetime, timedelta, time
from sqlalchemy import func, and_, or_, desc, case
from collections import defaultdict
import math

# Create blueprints
trending_bp = Blueprint('trending', __name__)
notifications_bp = Blueprint('notifications', __name__)

# ==================== TRENDING & DISCOVERY SYSTEM ====================

# Trending score calculation weights
TRENDING_WEIGHTS = {
    'like': 1.0,
    'reply': 2.0,
    'retweet': 3.0,
    'view': 0.1,
    'group_join': 5.0,
    'poll_vote': 1.5,
    'event_rsvp': 4.0,
    'product_view': 0.5,
    'product_purchase': 10.0
}

# Time decay factor (half-life in hours)
TRENDING_HALF_LIFE = 24

def calculate_trending_score(engagement_count, hours_old):
    """Calculate trending score with time decay"""
    if hours_old <= 0:
        hours_old = 0.1
    
    # Exponential decay based on half-life
    decay_factor = math.pow(0.5, hours_old / TRENDING_HALF_LIFE)
    score = engagement_count * decay_factor
    
    return score

def update_trending_topics():
    """Update trending topics in the database"""
    try:
        now = datetime.utcnow()
        cutoff_time = now - timedelta(hours=48)  # Consider last 48 hours
        
        # Clear old trending topics
        TrendingTopic.query.filter(
            TrendingTopic.last_updated < now - timedelta(hours=6)
        ).update({'is_active': False})
        
        # Update trending hashtags
        trending_hashtags = db.session.query(
            Hashtag.id,
            Hashtag.name,
            func.count(YapHashtag.id).label('usage_count')
        ).join(
            YapHashtag, YapHashtag.hashtag_id == Hashtag.id
        ).join(
            Yap, YapHashtag.yap_id == Yap.id
        ).filter(
            Yap.created_at >= cutoff_time
        ).group_by(Hashtag.id).order_by(
            func.count(YapHashtag.id).desc()
        ).limit(20).all()
        
        for hashtag_id, hashtag_name, usage_count in trending_hashtags:
            hours_old = 1  # Simplified for hashtags
            score = calculate_trending_score(usage_count, hours_old)
            
            # Update or create trending topic
            trending = TrendingTopic.query.filter_by(
                topic_type='hashtag',
                topic_id=str(hashtag_id)
            ).first()
            
            if trending:
                trending.score = score
                trending.engagement_count = usage_count
                trending.last_updated = now
                trending.is_active = True
            else:
                trending = TrendingTopic(
                    topic_type='hashtag',
                    topic_id=str(hashtag_id),
                    topic_name=f'#{hashtag_name}',
                    score=score,
                    engagement_count=usage_count
                )
                db.session.add(trending)
        
        # Update trending yaps
        trending_yaps = db.session.query(
            Yap.id,
            Yap.content,
            func.count(Like.id).label('like_count'),
            func.count(Reply.id).label('reply_count'),
            func.extract('epoch', now - Yap.created_at) / 3600
        ).outerjoin(
            Like, Like.yap_id == Yap.id
        ).outerjoin(
            Reply, Reply.yap_id == Yap.id
        ).filter(
            Yap.created_at >= cutoff_time
        ).group_by(Yap.id).having(
            (func.count(Like.id) + func.count(Reply.id) * 2) > 5
        ).order_by(
            (func.count(Like.id) + func.count(Reply.id) * 2).desc()
        ).limit(20).all()
        
        for yap_id, content, like_count, reply_count, hours_old in trending_yaps:
            engagement = like_count + (reply_count * 2)
            score = calculate_trending_score(engagement, hours_old or 1)
            
            trending = TrendingTopic.query.filter_by(
                topic_type='yap',
                topic_id=yap_id
            ).first()
            
            if trending:
                trending.score = score
                trending.engagement_count = engagement
                trending.last_updated = now
                trending.is_active = True
            else:
                trending = TrendingTopic(
                    topic_type='yap',
                    topic_id=yap_id,
                    topic_name=content[:100],
                    score=score,
                    engagement_count=engagement
                )
                db.session.add(trending)
        
        # Update trending groups (by new members)
        trending_groups = db.session.query(
            Community.id,
            Community.name,
            func.count(CommunityMember.id).label('new_members')
        ).join(
            CommunityMember, CommunityMember.community_id == Community.id
        ).filter(
            CommunityMember.joined_at >= cutoff_time,
            Community.is_active == True
        ).group_by(Community.id).having(
            func.count(CommunityMember.id) > 3
        ).order_by(
            func.count(CommunityMember.id).desc()
        ).limit(10).all()
        
        for community_id, group_name, new_members in trending_groups:
            score = calculate_trending_score(new_members * 5, 12)  # Weight group joins higher
            
            trending = TrendingTopic.query.filter_by(
                topic_type='group',
                topic_id=community_id
            ).first()
            
            if trending:
                trending.score = score
                trending.engagement_count = new_members
                trending.last_updated = now
                trending.is_active = True
            else:
                trending = TrendingTopic(
                    topic_type='group',
                    topic_id=community_id,
                    topic_name=group_name,
                    score=score,
                    engagement_count=new_members
                )
                db.session.add(trending)
        
        db.session.commit()
        return True
        
    except Exception as e:
        db.session.rollback()
        print(f"Error updating trending topics: {str(e)}")
        return False

def get_personalized_recommendations(user_id, content_type='mixed'):
    """Get personalized content recommendations for a user"""
    recommendations = []
    
    # Get user's interests based on activity
    user_hashtags = db.session.query(Hashtag.id).join(
        YapHashtag, YapHashtag.hashtag_id == Hashtag.id
    ).join(
        Yap, YapHashtag.yap_id == Yap.id
    ).filter(Yap.user_id == user_id).distinct().limit(10).all()
    
    user_groups = CommunityMember.query.filter_by(
        user_id=user_id,
        is_active=True
    ).all()
    
    # Get followed users
    following = Follow.query.filter_by(follower_id=user_id).all()
    following_ids = [f.following_id for f in following]
    
    if content_type in ['yaps', 'mixed']:
        # Recommend yaps from followed users and similar hashtags
        recommended_yaps = Yap.query.filter(
            or_(
                Yap.user_id.in_(following_ids),
                Yap.hashtags.any(YapHashtag.hashtag_id.in_([h[0] for h in user_hashtags]))
            ),
            Yap.created_at >= datetime.utcnow() - timedelta(days=7)
        ).order_by(Yap.created_at.desc()).limit(10).all()
        
        for yap in recommended_yaps:
            recommendations.append({
                'type': 'yap',
                'id': yap.id,
                'content': yap.content,
                'reason': 'from_followed_user' if yap.user_id in following_ids else 'similar_interests'
            })
    
    if content_type in ['groups', 'mixed']:
        # Recommend groups based on current groups' categories
        if user_groups:
            categories = [gm.group.category for gm in user_groups if gm.group.category]
            recommended_groups = Community.query.filter(
                Community.category.in_(categories),
                ~Community.id.in_([gm.community_id for gm in user_groups]),
                Community.is_active == True,
                Community.privacy_type == 'public'
            ).order_by(Community.member_count.desc()).limit(5).all()
            
            for group in recommended_groups:
                recommendations.append({
                    'type': 'group',
                    'id': group.id,
                    'name': group.name,
                    'reason': 'similar_category'
                })
    
    return recommendations

# ============= Trending API Endpoints =============

@trending_bp.route('/trending/hashtags', methods=['GET'])
def get_trending_hashtags():
    """Get trending hashtags (public endpoint, no auth required)"""
    try:
        limit = request.args.get('limit', 10, type=int)
        limit = min(limit, 50)  # Cap at 50
        
        cutoff_time = datetime.utcnow() - timedelta(hours=48)
        
        # Get trending hashtags with yap counts
        trending_hashtags = db.session.query(
            Hashtag.name,
            func.count(YapHashtag.id).label('count')
        ).join(
            YapHashtag, YapHashtag.hashtag_id == Hashtag.id
        ).join(
            Yap, YapHashtag.yap_id == Yap.id
        ).filter(
            Yap.created_at >= cutoff_time
        ).group_by(Hashtag.id, Hashtag.name).order_by(
            func.count(YapHashtag.id).desc()
        ).limit(limit).all()
        
        hashtags = [
            {'name': name, 'count': count}
            for name, count in trending_hashtags
        ]
        
        return jsonify({
            'hashtags': hashtags,
            'updated_at': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@trending_bp.route('/trending/all', methods=['GET'])
@jwt_required()
def get_all_trending():
    """Get all trending topics across categories"""
    try:
        # Update trending topics first
        update_trending_topics()
        
        # Get active trending topics
        trending = TrendingTopic.query.filter_by(is_active=True)\
                                     .order_by(TrendingTopic.score.desc())\
                                     .limit(50).all()
        
        # Community by type
        by_type = defaultdict(list)
        for topic in trending:
            by_type[topic.topic_type].append({
                'id': topic.topic_id,
                'name': topic.topic_name,
                'score': topic.score,
                'engagement_count': topic.engagement_count,
                'trending_since': topic.trending_since.isoformat()
            })
        
        return jsonify({
            'trending': {
                'hashtags': by_type.get('hashtag', [])[:10],
                'yaps': by_type.get('yap', [])[:10],
                'events': by_type.get('event', [])[:10],
                'groups': by_type.get('group', [])[:5],
                'products': by_type.get('product', [])[:5]
            },
            'updated_at': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@trending_bp.route('/trending/<topic_type>', methods=['GET'])
@jwt_required()
def get_trending_by_type(topic_type):
    """Get trending topics for a specific type"""
    try:
        valid_types = ['hashtag', 'yap', 'event', 'group', 'product', 'poll']
        if topic_type not in valid_types:
            return jsonify({'error': 'Invalid topic type'}), 400
        
        limit = request.args.get('limit', 20, type=int)
        
        # Update trending topics
        update_trending_topics()
        
        # Get trending for specific type
        trending = TrendingTopic.query.filter_by(
            topic_type=topic_type,
            is_active=True
        ).order_by(TrendingTopic.score.desc()).limit(limit).all()
        
        results = []
        for topic in trending:
            # Get additional details based on type
            details = {}
            if topic_type == 'yap':
                yap = Yap.query.get(topic.topic_id)
                if yap:
                    user = Users.query.get(yap.user_id)
                    details = {
                        'user': {
                            'id': user.id,
                            'username': user.username,
                            'display_name': user.display_name
                        } if user else None
                    }
            elif topic_type == 'group':
                group = Community.query.get(topic.topic_id)
                if group:
                    details = {
                        'member_count': group.member_count,
                        'category': group.category
                    }
            
            results.append({
                'id': topic.topic_id,
                'name': topic.topic_name,
                'score': topic.score,
                'engagement_count': topic.engagement_count,
                'trending_since': topic.trending_since.isoformat(),
                **details
            })
        
        return jsonify({
            'type': topic_type,
            'trending': results,
            'count': len(results)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@trending_bp.route('/discover', methods=['GET'])
@jwt_required()
def discover_content():
    """Get personalized content discovery recommendations"""
    try:
        user_id = get_jwt_identity()
        content_type = request.args.get('type', 'mixed')
        
        recommendations = get_personalized_recommendations(user_id, content_type)
        
        # Also get some trending content
        trending = TrendingTopic.query.filter_by(is_active=True)\
                                     .order_by(TrendingTopic.score.desc())\
                                     .limit(10).all()
        
        trending_items = []
        for topic in trending:
            trending_items.append({
                'type': topic.topic_type,
                'id': topic.topic_id,
                'name': topic.topic_name,
                'score': topic.score
            })
        
        return jsonify({
            'personalized': recommendations,
            'trending': trending_items,
            'generated_at': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== ENHANCED NOTIFICATIONS SYSTEM ====================

def get_or_create_notification_preferences(user_id):
    """Get or create notification preferences for a user"""
    prefs = NotificationPreference.query.filter_by(user_id=user_id).first()
    if not prefs:
        prefs = NotificationPreference(user_id=user_id)
        db.session.add(prefs)
        db.session.flush()
    return prefs

def should_send_notification(user_id, notification_type, priority='medium'):
    """Check if notification should be sent based on user preferences"""
    prefs = get_or_create_notification_preferences(user_id)
    
    # Check priority level
    priority_levels = {'low': 0, 'medium': 1, 'high': 2}
    min_priority = priority_levels.get(prefs.min_priority_level, 0)
    notification_priority = priority_levels.get(priority, 1)
    
    if notification_priority < min_priority:
        return False
    
    # Check quiet hours
    if prefs.quiet_hours_enabled:
        now = datetime.utcnow().time()
        if prefs.quiet_hours_start and prefs.quiet_hours_end:
            if prefs.quiet_hours_start <= prefs.quiet_hours_end:
                # Normal case: quiet hours don't cross midnight
                if prefs.quiet_hours_start <= now <= prefs.quiet_hours_end:
                    return False
            else:
                # Quiet hours cross midnight
                if now >= prefs.quiet_hours_start or now <= prefs.quiet_hours_end:
                    return False
    
    # Check notification type preferences
    type_mapping = {
        'GROUP_INVITE': prefs.group_invites,
        'GROUP_ACTIVITY': prefs.group_activity,
        'TRENDING_CONTENT': prefs.trending_content,
        'FRIEND_MILESTONE': prefs.friend_milestones,
        'EVENT_REMINDER': prefs.event_reminders,
        'MARKETPLACE_ALERT': prefs.marketplace_alerts,
        'POLL_RESULT': prefs.poll_results,
        'ACHIEVEMENT_UNLOCKED': prefs.achievement_unlocked
    }
    
    # Default to True if type not in mapping
    return type_mapping.get(notification_type, True)

def create_smart_notification(recipient_id, notification_type, **kwargs):
    """Create a smart notification with priority and grouping"""
    priority = kwargs.get('priority', 'medium')
    
    # Check if notification should be sent
    if not should_send_notification(recipient_id, notification_type, priority):
        return None
    
    # Create notification
    notification = EnhancedNotification(
        type=notification_type,
        priority=priority,
        recipient_id=recipient_id,
        sender_id=kwargs.get('sender_id'),
        community_id=kwargs.get('community_id'),
        poll_id=kwargs.get('poll_id'),
        achievement_id=kwargs.get('achievement_id'),
        yap_id=kwargs.get('yap_id'),
        event_id=kwargs.get('event_id'),
        title=kwargs.get('title', 'Notification'),
        message=kwargs.get('message', ''),
        action_url=kwargs.get('action_url')
    )
    
    db.session.add(notification)
    return notification

# ============= Notification API Endpoints =============

@notifications_bp.route('/notifications', methods=['GET'])
@jwt_required()
def get_notifications():
    """Get user's notifications with smart grouping"""
    try:
        user_id = get_jwt_identity()
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        unread_only = request.args.get('unread_only', 'false').lower() == 'true'
        priority = request.args.get('priority')
        
        # Base query
        query = EnhancedNotification.query.filter_by(recipient_id=user_id)
        
        if unread_only:
            query = query.filter_by(is_read=False)
        
        if priority:
            query = query.filter_by(priority=priority)
        
        # Order by priority and creation time
        query = query.order_by(
            case(
                (EnhancedNotification.priority == 'high', 0),
                (EnhancedNotification.priority == 'medium', 1),
                else_=2
            ),
            EnhancedNotification.created_at.desc()
        )
        
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        # Format notifications
        notifications = []
        for notif in paginated.items:
            # Get sender info if applicable
            sender = None
            if notif.sender_id:
                sender_user = Users.query.get(notif.sender_id)
                if sender_user:
                    sender = {
                        'id': sender_user.id,
                        'username': sender_user.username,
                        'display_name': sender_user.display_name,
                        'avatar': sender_user.avatar
                    }
            
            notifications.append({
                'id': notif.id,
                'type': notif.type,
                'priority': notif.priority,
                'title': notif.title,
                'message': notif.message,
                'action_url': notif.action_url,
                'is_read': notif.is_read,
                'sender': sender,
                'created_at': notif.created_at.isoformat(),
                'read_at': notif.read_at.isoformat() if notif.read_at else None
            })
        
        # Get unread count
        unread_count = EnhancedNotification.query.filter_by(
            recipient_id=user_id,
            is_read=False
        ).count()
        
        return jsonify({
            'notifications': notifications,
            'total': paginated.total,
            'pages': paginated.pages,
            'current_page': page,
            'unread_count': unread_count
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@notifications_bp.route('/notifications/mark-read', methods=['POST'])
@jwt_required()
def mark_notifications_read():
    """Mark notifications as read"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        notification_ids = data.get('notification_ids', [])
        mark_all = data.get('mark_all', False)
        
        if mark_all:
            # Mark all unread notifications as read
            EnhancedNotification.query.filter_by(
                recipient_id=user_id,
                is_read=False
            ).update({
                'is_read': True,
                'read_at': datetime.utcnow()
            })
        elif notification_ids:
            # Mark specific notifications as read
            EnhancedNotification.query.filter(
                EnhancedNotification.id.in_(notification_ids),
                EnhancedNotification.recipient_id == user_id
            ).update({
                'is_read': True,
                'read_at': datetime.utcnow()
            }, synchronize_session=False)
        else:
            return jsonify({'error': 'No notifications specified'}), 400
        
        db.session.commit()
        
        return jsonify({'message': 'Notifications marked as read'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@notifications_bp.route('/notifications/preferences', methods=['GET'])
@jwt_required()
def get_notification_preferences():
    """Get user's notification preferences"""
    try:
        user_id = get_jwt_identity()
        prefs = get_or_create_notification_preferences(user_id)
        
        return jsonify({
            'preferences': {
                'notification_types': {
                    'group_invites': prefs.group_invites,
                    'group_activity': prefs.group_activity,
                    'trending_content': prefs.trending_content,
                    'friend_milestones': prefs.friend_milestones,
                    'event_reminders': prefs.event_reminders,
                    'marketplace_alerts': prefs.marketplace_alerts,
                    'poll_results': prefs.poll_results,
                    'achievement_unlocked': prefs.achievement_unlocked
                },
                'delivery': {
                    'email_enabled': prefs.email_enabled,
                    'push_enabled': prefs.push_enabled,
                    'sms_enabled': prefs.sms_enabled
                },
                'quiet_hours': {
                    'enabled': prefs.quiet_hours_enabled,
                    'start': prefs.quiet_hours_start.isoformat() if prefs.quiet_hours_start else None,
                    'end': prefs.quiet_hours_end.isoformat() if prefs.quiet_hours_end else None
                },
                'min_priority_level': prefs.min_priority_level
            }
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@notifications_bp.route('/notifications/preferences', methods=['PUT'])
@jwt_required()
def update_notification_preferences():
    """Update user's notification preferences"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        prefs = get_or_create_notification_preferences(user_id)
        
        # Update notification types
        if 'notification_types' in data:
            types = data['notification_types']
            for key, value in types.items():
                if hasattr(prefs, key):
                    setattr(prefs, key, value)
        
        # Update delivery preferences
        if 'delivery' in data:
            delivery = data['delivery']
            if 'email_enabled' in delivery:
                prefs.email_enabled = delivery['email_enabled']
            if 'push_enabled' in delivery:
                prefs.push_enabled = delivery['push_enabled']
            if 'sms_enabled' in delivery:
                prefs.sms_enabled = delivery['sms_enabled']
        
        # Update quiet hours
        if 'quiet_hours' in data:
            quiet = data['quiet_hours']
            if 'enabled' in quiet:
                prefs.quiet_hours_enabled = quiet['enabled']
            if 'start' in quiet and quiet['start']:
                prefs.quiet_hours_start = time.fromisoformat(quiet['start'])
            if 'end' in quiet and quiet['end']:
                prefs.quiet_hours_end = time.fromisoformat(quiet['end'])
        
        # Update priority level
        if 'min_priority_level' in data:
            prefs.min_priority_level = data['min_priority_level']
        
        prefs.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'message': 'Preferences updated successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@notifications_bp.route('/notifications/test', methods=['POST'])
@jwt_required()
def send_test_notification():
    """Send a test notification (for testing)"""
    try:
        user_id = get_jwt_identity()
        
        notification = create_smart_notification(
            recipient_id=user_id,
            notification_type='TEST',
            priority='high',
            title='Test Notification',
            message='This is a test notification from CampoSocial Phase 8!',
            action_url='/settings/notifications'
        )
        
        if notification:
            db.session.commit()
            return jsonify({'message': 'Test notification sent successfully'}), 200
        else:
            return jsonify({'message': 'Notification not sent due to user preferences'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

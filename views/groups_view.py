from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Group, GroupMember, GroupPost, Yap, Users, EnhancedNotification
from datetime import datetime
from sqlalchemy import or_, and_, func
from cuid import cuid

groups_bp = Blueprint('groups', __name__)

# ============= Helper Functions =============
def get_user_role_in_group(group_id, user_id):
    """Get user's role in a specific group"""
    member = GroupMember.query.filter_by(
        group_id=group_id,
        user_id=user_id,
        is_active=True
    ).first()
    return member.role if member else None

def is_group_member(group_id, user_id):
    """Check if user is a member of the group"""
    return GroupMember.query.filter_by(
        group_id=group_id,
        user_id=user_id,
        is_active=True
    ).first() is not None

def can_view_group(group, user_id):
    """Check if user can view group content"""
    if group.privacy_type == 'public':
        return True
    elif group.privacy_type == 'private':
        return is_group_member(group.id, user_id)
    elif group.privacy_type == 'secret':
        return is_group_member(group.id, user_id)
    return False

def update_group_member_count(group_id):
    """Update the member count for a group"""
    group = Group.query.get(group_id)
    if group:
        member_count = GroupMember.query.filter_by(
            group_id=group_id,
            is_active=True
        ).count()
        group.member_count = member_count
        db.session.commit()

# ============= Group CRUD Operations =============

@groups_bp.route('/groups', methods=['POST'])
@jwt_required()
def create_group():
    """Create a new group"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        # Validate required fields
        if not data.get('name'):
            return jsonify({'error': 'Group name is required'}), 400
        
        # Create new group
        new_group = Group(
            id=cuid(),
            name=data['name'],
            description=data.get('description', ''),
            category=data.get('category', 'other'),
            privacy_type=data.get('privacy_type', 'public'),
            cover_image=data.get('cover_image'),
            icon_image=data.get('icon_image'),
            rules=data.get('rules'),
            created_by=user_id,
            member_count=1  # Creator is the first member
        )
        
        db.session.add(new_group)
        db.session.flush()
        
        # Add creator as admin
        creator_member = GroupMember(
            group_id=new_group.id,
            user_id=user_id,
            role='admin'
        )
        db.session.add(creator_member)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Group created successfully',
            'group': {
                'id': new_group.id,
                'name': new_group.name,
                'description': new_group.description,
                'category': new_group.category,
                'privacy_type': new_group.privacy_type,
                'member_count': new_group.member_count,
                'created_at': new_group.created_at.isoformat()
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@groups_bp.route('/groups', methods=['GET'])
@jwt_required()
def get_groups():
    """Get all visible groups for the user"""
    try:
        user_id = get_jwt_identity()
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        category = request.args.get('category')
        search = request.args.get('search')
        
        # Base query - exclude secret groups unless user is a member
        query = Group.query.filter(
            Group.is_active == True,
            or_(
                Group.privacy_type != 'secret',
                Group.members.any(
                    and_(
                        GroupMember.user_id == user_id,
                        GroupMember.is_active == True
                    )
                )
            )
        )
        
        # Apply filters
        if category:
            query = query.filter(Group.category == category)
        
        if search:
            query = query.filter(
                or_(
                    Group.name.ilike(f'%{search}%'),
                    Group.description.ilike(f'%{search}%')
                )
            )
        
        # Order by member count and creation date
        query = query.order_by(Group.member_count.desc(), Group.created_at.desc())
        
        # Paginate
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        # Format response
        groups = []
        for group in paginated.items:
            # Check if user is a member
            is_member = is_group_member(group.id, user_id)
            user_role = get_user_role_in_group(group.id, user_id) if is_member else None
            
            groups.append({
                'id': group.id,
                'name': group.name,
                'description': group.description,
                'category': group.category,
                'privacy_type': group.privacy_type,
                'cover_image': group.cover_image,
                'icon_image': group.icon_image,
                'member_count': group.member_count,
                'is_verified': group.is_verified,
                'is_member': is_member,
                'user_role': user_role,
                'created_at': group.created_at.isoformat()
            })
        
        return jsonify({
            'groups': groups,
            'total': paginated.total,
            'pages': paginated.pages,
            'current_page': page
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@groups_bp.route('/groups/discover', methods=['GET'])
@jwt_required()
def discover_groups():
    """Discover recommended groups based on user interests"""
    try:
        user_id = get_jwt_identity()
        
        # Get user's current groups
        user_groups = GroupMember.query.filter_by(
            user_id=user_id,
            is_active=True
        ).all()
        user_group_ids = [gm.group_id for gm in user_groups]
        
        # Get categories of user's current groups
        if user_group_ids:
            user_categories = db.session.query(Group.category).filter(
                Group.id.in_(user_group_ids)
            ).distinct().all()
            user_categories = [cat[0] for cat in user_categories if cat[0]]
        else:
            user_categories = []
        
        # Find recommended groups
        recommended_query = Group.query.filter(
            Group.is_active == True,
            Group.privacy_type == 'public',
            ~Group.id.in_(user_group_ids)  # Exclude groups user is already in
        )
        
        # Prioritize groups in same categories
        if user_categories:
            recommended_query = recommended_query.order_by(
                db.case(
                    [(Group.category.in_(user_categories), 0)],
                    else_=1
                ),
                Group.member_count.desc()
            )
        else:
            recommended_query = recommended_query.order_by(Group.member_count.desc())
        
        recommended = recommended_query.limit(10).all()
        
        # Get trending groups (most new members in last week)
        trending_groups = db.session.query(
            Group,
            func.count(GroupMember.id).label('new_members')
        ).join(
            GroupMember,
            and_(
                GroupMember.group_id == Group.id,
                GroupMember.joined_at >= func.date('now', '-7 days')
            )
        ).filter(
            Group.is_active == True,
            Group.privacy_type == 'public',
            ~Group.id.in_(user_group_ids)
        ).group_by(Group.id).order_by(
            func.count(GroupMember.id).desc()
        ).limit(5).all()
        
        # Format responses
        recommended_list = []
        for group in recommended:
            recommended_list.append({
                'id': group.id,
                'name': group.name,
                'description': group.description,
                'category': group.category,
                'member_count': group.member_count,
                'icon_image': group.icon_image,
                'is_verified': group.is_verified
            })
        
        trending_list = []
        for group, new_members in trending_groups:
            trending_list.append({
                'id': group.id,
                'name': group.name,
                'description': group.description,
                'category': group.category,
                'member_count': group.member_count,
                'new_members_this_week': new_members,
                'icon_image': group.icon_image,
                'is_verified': group.is_verified
            })
        
        return jsonify({
            'recommended': recommended_list,
            'trending': trending_list
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@groups_bp.route('/groups/<group_id>', methods=['GET'])
@jwt_required()
def get_group_details(group_id):
    """Get detailed information about a specific group"""
    try:
        user_id = get_jwt_identity()
        
        group = Group.query.filter_by(id=group_id, is_active=True).first()
        if not group:
            return jsonify({'error': 'Group not found'}), 404
        
        # Check if user can view this group
        if not can_view_group(group, user_id):
            return jsonify({'error': 'You do not have permission to view this group'}), 403
        
        # Get user's membership status
        is_member = is_group_member(group_id, user_id)
        user_role = get_user_role_in_group(group_id, user_id) if is_member else None
        
        # Get group creator info
        creator = Users.query.get(group.created_by)
        
        # Get recent members (for display)
        recent_members = db.session.query(Users).join(
            GroupMember,
            GroupMember.user_id == Users.id
        ).filter(
            GroupMember.group_id == group_id,
            GroupMember.is_active == True
        ).order_by(GroupMember.joined_at.desc()).limit(10).all()
        
        members_list = [{
            'id': member.id,
            'username': member.username,
            'display_name': member.display_name,
            'avatar': member.avatar
        } for member in recent_members]
        
        return jsonify({
            'id': group.id,
            'name': group.name,
            'description': group.description,
            'category': group.category,
            'privacy_type': group.privacy_type,
            'cover_image': group.cover_image,
            'icon_image': group.icon_image,
            'rules': group.rules,
            'member_count': group.member_count,
            'is_verified': group.is_verified,
            'is_member': is_member,
            'user_role': user_role,
            'creator': {
                'id': creator.id,
                'username': creator.username,
                'display_name': creator.display_name,
                'avatar': creator.avatar
            } if creator else None,
            'recent_members': members_list,
            'created_at': group.created_at.isoformat(),
            'updated_at': group.updated_at.isoformat()
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@groups_bp.route('/groups/<group_id>', methods=['PUT'])
@jwt_required()
def update_group(group_id):
    """Update group information (admin/moderator only)"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        group = Group.query.filter_by(id=group_id, is_active=True).first()
        if not group:
            return jsonify({'error': 'Group not found'}), 404
        
        # Check if user has permission to update
        user_role = get_user_role_in_group(group_id, user_id)
        if user_role not in ['admin', 'moderator']:
            return jsonify({'error': 'You do not have permission to update this group'}), 403
        
        # Update allowed fields
        if 'name' in data:
            group.name = data['name']
        if 'description' in data:
            group.description = data['description']
        if 'category' in data:
            group.category = data['category']
        if 'privacy_type' in data and user_role == 'admin':
            group.privacy_type = data['privacy_type']
        if 'cover_image' in data:
            group.cover_image = data['cover_image']
        if 'icon_image' in data:
            group.icon_image = data['icon_image']
        if 'rules' in data:
            group.rules = data['rules']
        
        group.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'message': 'Group updated successfully',
            'group': {
                'id': group.id,
                'name': group.name,
                'description': group.description,
                'category': group.category,
                'privacy_type': group.privacy_type,
                'updated_at': group.updated_at.isoformat()
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@groups_bp.route('/groups/<group_id>', methods=['DELETE'])
@jwt_required()
def delete_group(group_id):
    """Delete a group (admin only)"""
    try:
        user_id = get_jwt_identity()
        
        group = Group.query.filter_by(id=group_id, is_active=True).first()
        if not group:
            return jsonify({'error': 'Group not found'}), 404
        
        # Check if user is admin
        user_role = get_user_role_in_group(group_id, user_id)
        if user_role != 'admin':
            return jsonify({'error': 'Only group admin can delete the group'}), 403
        
        # Soft delete
        group.is_active = False
        group.updated_at = datetime.utcnow()
        
        # Deactivate all memberships
        GroupMember.query.filter_by(group_id=group_id).update({'is_active': False})
        
        db.session.commit()
        
        return jsonify({'message': 'Group deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ============= Group Membership Management =============

@groups_bp.route('/groups/<group_id>/join', methods=['POST'])
@jwt_required()
def join_group(group_id):
    """Join a group"""
    try:
        user_id = get_jwt_identity()
        
        group = Group.query.filter_by(id=group_id, is_active=True).first()
        if not group:
            return jsonify({'error': 'Group not found'}), 404
        
        # Check if already a member
        existing_member = GroupMember.query.filter_by(
            group_id=group_id,
            user_id=user_id
        ).first()
        
        if existing_member:
            if existing_member.is_active:
                return jsonify({'error': 'You are already a member of this group'}), 400
            else:
                # Reactivate membership
                existing_member.is_active = True
                existing_member.joined_at = datetime.utcnow()
        else:
            # Check if group is private
            if group.privacy_type == 'private':
                # For private groups, could implement a request system
                # For now, we'll allow direct joining
                pass
            elif group.privacy_type == 'secret':
                return jsonify({'error': 'You cannot join a secret group without an invitation'}), 403
            
            # Create new membership
            new_member = GroupMember(
                group_id=group_id,
                user_id=user_id,
                role='member'
            )
            db.session.add(new_member)
        
        db.session.commit()
        update_group_member_count(group_id)
        
        # Send notification to group admins
        admins = GroupMember.query.filter_by(
            group_id=group_id,
            role='admin',
            is_active=True
        ).all()
        
        user = Users.query.get(user_id)
        for admin in admins:
            if admin.user_id != user_id:
                notification = EnhancedNotification(
                    type='GROUP_NEW_MEMBER',
                    priority='low',
                    recipient_id=admin.user_id,
                    sender_id=user_id,
                    group_id=group_id,
                    title='New Group Member',
                    message=f'{user.username} joined {group.name}',
                    action_url=f'/groups/{group_id}'
                )
                db.session.add(notification)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Successfully joined the group',
            'group_id': group_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@groups_bp.route('/groups/<group_id>/leave', methods=['POST'])
@jwt_required()
def leave_group(group_id):
    """Leave a group"""
    try:
        user_id = get_jwt_identity()
        
        member = GroupMember.query.filter_by(
            group_id=group_id,
            user_id=user_id,
            is_active=True
        ).first()
        
        if not member:
            return jsonify({'error': 'You are not a member of this group'}), 400
        
        # Check if user is the only admin
        if member.role == 'admin':
            admin_count = GroupMember.query.filter_by(
                group_id=group_id,
                role='admin',
                is_active=True
            ).count()
            
            if admin_count == 1:
                return jsonify({'error': 'You cannot leave as you are the only admin. Please assign another admin first.'}), 400
        
        # Deactivate membership
        member.is_active = False
        db.session.commit()
        update_group_member_count(group_id)
        
        return jsonify({'message': 'Successfully left the group'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@groups_bp.route('/groups/<group_id>/members', methods=['GET'])
@jwt_required()
def get_group_members(group_id):
    """Get list of group members"""
    try:
        user_id = get_jwt_identity()
        
        group = Group.query.filter_by(id=group_id, is_active=True).first()
        if not group:
            return jsonify({'error': 'Group not found'}), 404
        
        # Check if user can view members
        if not can_view_group(group, user_id):
            return jsonify({'error': 'You do not have permission to view this group'}), 403
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        role_filter = request.args.get('role')
        
        # Query members
        query = db.session.query(Users, GroupMember).join(
            GroupMember,
            GroupMember.user_id == Users.id
        ).filter(
            GroupMember.group_id == group_id,
            GroupMember.is_active == True
        )
        
        if role_filter:
            query = query.filter(GroupMember.role == role_filter)
        
        # Order by role importance and join date
        query = query.order_by(
            db.case(
                [(GroupMember.role == 'admin', 0),
                 (GroupMember.role == 'moderator', 1)],
                else_=2
            ),
            GroupMember.joined_at.desc()
        )
        
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        members = []
        for user, member in paginated.items:
            members.append({
                'user_id': user.id,
                'username': user.username,
                'display_name': user.display_name,
                'avatar': user.avatar,
                'role': member.role,
                'joined_at': member.joined_at.isoformat()
            })
        
        return jsonify({
            'members': members,
            'total': paginated.total,
            'pages': paginated.pages,
            'current_page': page
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@groups_bp.route('/groups/<group_id>/members/<int:member_id>/role', methods=['PUT'])
@jwt_required()
def update_member_role(group_id, member_id):
    """Update a member's role (admin only)"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        new_role = data.get('role')
        
        if new_role not in ['admin', 'moderator', 'member']:
            return jsonify({'error': 'Invalid role'}), 400
        
        # Check if user is admin
        user_role = get_user_role_in_group(group_id, user_id)
        if user_role != 'admin':
            return jsonify({'error': 'Only group admins can change member roles'}), 403
        
        # Get target member
        target_member = GroupMember.query.filter_by(
            group_id=group_id,
            user_id=member_id,
            is_active=True
        ).first()
        
        if not target_member:
            return jsonify({'error': 'Member not found'}), 404
        
        # Update role
        target_member.role = new_role
        db.session.commit()
        
        # Send notification to the member
        group = Group.query.get(group_id)
        notification = EnhancedNotification(
            type='GROUP_ROLE_CHANGED',
            priority='medium',
            recipient_id=member_id,
            sender_id=user_id,
            group_id=group_id,
            title='Group Role Updated',
            message=f'Your role in {group.name} has been changed to {new_role}',
            action_url=f'/groups/{group_id}'
        )
        db.session.add(notification)
        db.session.commit()
        
        return jsonify({
            'message': 'Member role updated successfully',
            'new_role': new_role
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ============= Group Posts =============

@groups_bp.route('/groups/<group_id>/posts', methods=['POST'])
@jwt_required()
def create_group_post(group_id):
    """Create a post in a group"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        # Check if user is a member
        if not is_group_member(group_id, user_id):
            return jsonify({'error': 'You must be a member to post in this group'}), 403
        
        # Create the yap first
        yap = Yap(
            id=cuid(),
            content=data['content'],
            user_id=user_id,
            location=data.get('location')
        )
        db.session.add(yap)
        db.session.flush()
        
        # Create group post association
        group_post = GroupPost(
            id=cuid(),
            group_id=group_id,
            yap_id=yap.id,
            is_pinned=False
        )
        db.session.add(group_post)
        
        db.session.commit()
        
        # Get user info for response
        user = Users.query.get(user_id)
        
        return jsonify({
            'message': 'Post created successfully',
            'post': {
                'id': group_post.id,
                'yap_id': yap.id,
                'content': yap.content,
                'group_id': group_id,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'display_name': user.display_name,
                    'avatar': user.avatar
                },
                'created_at': yap.created_at.isoformat()
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@groups_bp.route('/groups/<group_id>/posts', methods=['GET'])
@jwt_required()
def get_group_posts(group_id):
    """Get posts from a group"""
    try:
        user_id = get_jwt_identity()
        
        group = Group.query.filter_by(id=group_id, is_active=True).first()
        if not group:
            return jsonify({'error': 'Group not found'}), 404
        
        # Check if user can view group
        if not can_view_group(group, user_id):
            return jsonify({'error': 'You do not have permission to view this group'}), 403
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # Query group posts
        query = db.session.query(GroupPost, Yap, Users).join(
            Yap, GroupPost.yap_id == Yap.id
        ).join(
            Users, Yap.user_id == Users.id
        ).filter(
            GroupPost.group_id == group_id
        ).order_by(
            GroupPost.is_pinned.desc(),
            GroupPost.created_at.desc()
        )
        
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        posts = []
        for group_post, yap, user in paginated.items:
            # Get likes count
            likes_count = yap.likes.count() if yap.likes else 0
            replies_count = yap.replies.count() if yap.replies else 0
            
            posts.append({
                'id': group_post.id,
                'yap_id': yap.id,
                'content': yap.content,
                'location': yap.location,
                'is_pinned': group_post.is_pinned,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'display_name': user.display_name,
                    'avatar': user.avatar
                },
                'likes_count': likes_count,
                'replies_count': replies_count,
                'created_at': yap.created_at.isoformat()
            })
        
        return jsonify({
            'posts': posts,
            'total': paginated.total,
            'pages': paginated.pages,
            'current_page': page
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@groups_bp.route('/groups/<group_id>/posts/<post_id>/pin', methods=['PUT'])
@jwt_required()
def toggle_pin_post(group_id, post_id):
    """Pin or unpin a group post (admin/moderator only)"""
    try:
        user_id = get_jwt_identity()
        
        # Check if user has permission
        user_role = get_user_role_in_group(group_id, user_id)
        if user_role not in ['admin', 'moderator']:
            return jsonify({'error': 'Only admins and moderators can pin posts'}), 403
        
        # Get the group post
        group_post = GroupPost.query.filter_by(
            id=post_id,
            group_id=group_id
        ).first()
        
        if not group_post:
            return jsonify({'error': 'Post not found'}), 404
        
        # Toggle pin status
        group_post.is_pinned = not group_post.is_pinned
        db.session.commit()
        
        return jsonify({
            'message': 'Post pin status updated',
            'is_pinned': group_post.is_pinned
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ============= User's Groups =============

@groups_bp.route('/my-groups', methods=['GET'])
@jwt_required()
def get_user_groups():
    """Get groups the current user is a member of"""
    try:
        user_id = get_jwt_identity()
        
        # Query user's groups
        user_groups = db.session.query(Group, GroupMember).join(
            GroupMember,
            GroupMember.group_id == Group.id
        ).filter(
            GroupMember.user_id == user_id,
            GroupMember.is_active == True,
            Group.is_active == True
        ).order_by(GroupMember.joined_at.desc()).all()
        
        groups = []
        for group, membership in user_groups:
            groups.append({
                'id': group.id,
                'name': group.name,
                'description': group.description,
                'category': group.category,
                'privacy_type': group.privacy_type,
                'icon_image': group.icon_image,
                'member_count': group.member_count,
                'user_role': membership.role,
                'joined_at': membership.joined_at.isoformat()
            })
        
        return jsonify({
            'groups': groups,
            'total': len(groups)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

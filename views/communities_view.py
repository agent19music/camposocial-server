from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Community, CommunityMember, CommunityPost, Yap, Users, EnhancedNotification, YapMedia, CommunityHashtag, CommunityPostHashtag, Like, CommunityInvite, Badge, UserBadge
from datetime import datetime, timedelta
from sqlalchemy import or_, and_, func, case
from cuid import cuid
from werkzeug.utils import secure_filename
import boto3
import os
import re
import secrets


communities_bp = Blueprint('communities', __name__)

# Initialize R2 client at module level
R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID') or os.getenv('AWS_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY') or os.getenv('AWS_SECRET_ACCESS_KEY')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME')
R2_ENDPOINT_URL = os.getenv('R2_ENDPOINT_URL')
IMAGE_PREFIX = os.getenv('IMAGE_PREFIX')

s3_client = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT_URL,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY
)

# ============= Helper Functions =============
def get_user_role_in_group(community_id, user_id):
    """Get user's role in a specific community"""
    member = CommunityMember.query.filter_by(
        community_id=community_id,
        user_id=user_id,
        is_active=True
    ).first()
    return member.role if member else None

def is_group_member(community_id, user_id):
    """Check if user is a member of the community"""
    return CommunityMember.query.filter_by(
        community_id=community_id,
        user_id=user_id,
        is_active=True
    ).first() is not None

def can_view_group(community, user_id):
    """Check if user can view community content"""
    if community.privacy_type == 'public':
        return True
    elif community.privacy_type == 'private':
        return is_group_member(community.id, user_id)
    elif community.privacy_type == 'secret':
        return is_group_member(community.id, user_id)
    return False

def update_group_member_count(community_id):
    """Update the member count for a community"""
    community = Community.query.get(community_id)
    if community:
        member_count = CommunityMember.query.filter_by(
            community_id=community_id,
            is_active=True
        ).count()
        community.member_count = member_count
        db.session.commit()

# ============= Community CRUD Operations =============

@communities_bp.route('/communities', methods=['POST'])
@jwt_required()
def create_group():
    """Create a new community"""
    try:
        user_id = get_jwt_identity()
        
        # Determine if request is JSON or Multipart Form Data
        if request.content_type and 'multipart/form-data' in request.content_type:
            data = request.form
            cover_image_file = request.files.get('cover_image')
            icon_image_file = request.files.get('icon_image')
        else:
            data = request.get_json() or {}
            cover_image_file = None
            icon_image_file = None
        
        # Validate required fields
        if not data.get('name'):
            return jsonify({'error': 'Community name is required'}), 400
        
        # Generate slug from name
        slug = Community.generate_slug(data['name'])
        
        # Handle cover image upload
        cover_image_url = data.get('cover_image') or Community.DEFAULT_COVER_IMAGE
        if cover_image_file:
            filename = secure_filename(cover_image_file.filename)
            s3_path = f"communities/{slug}/cover_{secrets.token_hex(4)}_{filename}"
            try:
                s3_client.upload_fileobj(
                    cover_image_file,
                    R2_BUCKET_NAME,
                    s3_path,
                    ExtraArgs={'ACL': 'public-read', 'ContentType': cover_image_file.content_type}
                )
                cover_image_url = f"{IMAGE_PREFIX}/{s3_path}"
            except Exception as e:
                print(f"Error uploading cover image: {str(e)}")
                # Fallback to default if upload fails, or handle error
        
        # Handle icon image upload
        icon_image_url = data.get('icon_image') or Community.DEFAULT_ICON_IMAGE
        if icon_image_file:
            filename = secure_filename(icon_image_file.filename)
            s3_path = f"communities/{slug}/icon_{secrets.token_hex(4)}_{filename}"
            try:
                s3_client.upload_fileobj(
                    icon_image_file,
                    R2_BUCKET_NAME,
                    s3_path,
                    ExtraArgs={'ACL': 'public-read', 'ContentType': icon_image_file.content_type}
                )
                icon_image_url = f"{IMAGE_PREFIX}/{s3_path}"
            except Exception as e:
                print(f"Error uploading icon image: {str(e)}")

        # Create new community
        new_group = Community(
            id=cuid(),
            slug=slug,
            name=data['name'],
            description=data.get('description', ''),
            category=data.get('category', 'other'),
            privacy_type=data.get('privacy_type', 'public'),
            cover_image=cover_image_url,
            icon_image=icon_image_url,
            rules=data.get('rules'),
            created_by=user_id,
            university_restriction=data.get('university_restriction'), # Optional: restrict to specific uni
            member_count=1  # Creator is the first member
        )

        
        db.session.add(new_group)
        db.session.flush()
        
        # Add creator as admin
        creator_member = CommunityMember(
            community_id=new_group.id,
            user_id=user_id,
            role='admin'
        )
        db.session.add(creator_member)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Community created successfully',
            'community': {
                'id': new_group.id,
                'slug': new_group.slug,
                'name': new_group.name,
                'description': new_group.description,
                'category': new_group.category,
                'privacy_type': new_group.privacy_type,
                'cover_image': new_group.cover_image,
                'icon_image': new_group.icon_image,
                'university_restriction': new_group.university_restriction,
                'member_count': new_group.member_count,
                'created_at': new_group.created_at.isoformat()
            }

        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@communities_bp.route('/communities', methods=['GET'])
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
        query = Community.query.filter(
            Community.is_active == True,
            or_(
                Community.privacy_type != 'secret',
                Community.members.any(
                    and_(
                        CommunityMember.user_id == user_id,
                        CommunityMember.is_active == True
                    )
                )
            )
        )
        
        # Apply filters
        if category:
            query = query.filter(Community.category == category)
        
        if search:
            query = query.filter(
                or_(
                    Community.name.ilike(f'%{search}%'),
                    Community.description.ilike(f'%{search}%')
                )
            )
        
        # Order by member count and creation date
        query = query.order_by(Community.member_count.desc(), Community.created_at.desc())
        
        # Paginate
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        # Format response
        groups = []
        for community in paginated.items:
            # Check if user is a member
            is_member = is_group_member(community.id, user_id)
            user_role = get_user_role_in_group(community.id, user_id) if is_member else None
            
            groups.append({
                'id': community.id,
                'slug': community.slug,
                'name': community.name,
                'description': community.description,
                'category': community.category,
                'privacy_type': community.privacy_type,
                'cover_image': community.cover_image,
                'icon_image': community.icon_image,
                'member_count': community.member_count,
                'university_restriction': community.university_restriction,
                'is_verified': community.is_verified,
                'is_member': is_member,
                'user_role': user_role,
                'created_at': community.created_at.isoformat()
            })

        
        return jsonify({
            'groups': groups,
            'total': paginated.total,
            'pages': paginated.pages,
            'current_page': page
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@communities_bp.route('/communities/discover', methods=['GET'])
@jwt_required()
def discover_groups():
    """Discover recommended groups based on user interests"""
    try:
        user_id = get_jwt_identity()
        
        # Get user's current groups
        user_groups = CommunityMember.query.filter_by(
            user_id=user_id,
            is_active=True
        ).all()
        user_group_ids = [gm.community_id for gm in user_groups]
        
        # Get categories of user's current groups
        if user_group_ids:
            user_categories = db.session.query(Community.category).filter(
                Community.id.in_(user_group_ids)
            ).distinct().all()
            user_categories = [cat[0] for cat in user_categories if cat[0]]
        else:
            user_categories = []
        
        # Find recommended groups
        # Handle empty user_group_ids list to avoid SQL issues
        if user_group_ids:
            recommended_query = Community.query.filter(
                Community.is_active == True,
                Community.privacy_type == 'public',
                ~Community.id.in_(user_group_ids)  # Exclude groups user is already in
            )
        else:
            recommended_query = Community.query.filter(
                Community.is_active == True,
                Community.privacy_type == 'public'
            )
        
        # Prioritize groups in same categories
        if user_categories:
            recommended_query = recommended_query.order_by(
                case(
                    (Community.category.in_(user_categories), 0),
                    else_=1
                ),
                Community.member_count.desc()
            )
        else:
            recommended_query = recommended_query.order_by(Community.member_count.desc())
        
        recommended = recommended_query.limit(10).all()
        
        # Get trending groups (most new members in last week)
        # Use datetime instead of func.date for PostgreSQL compatibility
        week_ago = datetime.utcnow() - timedelta(days=7)
        
        trending_query = db.session.query(
            Community,
            func.count(CommunityMember.id).label('new_members')
        ).join(
            CommunityMember,
            CommunityMember.community_id == Community.id
        ).filter(
            Community.is_active == True,
            Community.privacy_type == 'public',
            CommunityMember.joined_at >= week_ago
        )
        
        # Exclude groups user is already in
        if user_group_ids:
            trending_query = trending_query.filter(~Community.id.in_(user_group_ids))
        
        trending_groups = trending_query.group_by(Community.id).order_by(
            func.count(CommunityMember.id).desc()
        ).limit(5).all()
        
        # Format responses
        recommended_list = []
        for community in recommended:
            recommended_list.append({
                'id': community.id,
                'slug': community.slug,
                'name': community.name,
                'description': community.description,
                'category': community.category,
                'member_count': community.member_count,
                'icon_image': community.icon_image,
                'cover_image': community.cover_image,
                'is_verified': community.is_verified
            })
        
        trending_list = []
        for community, new_members in trending_groups:
            trending_list.append({
                'id': community.id,
                'slug': community.slug,
                'name': community.name,
                'description': community.description,
                'category': community.category,
                'member_count': community.member_count,
                'new_members_this_week': new_members,
                'icon_image': community.icon_image,
                'cover_image': community.cover_image,
                'is_verified': community.is_verified
            })
        
        return jsonify({
            'recommended': recommended_list,
            'trending': trending_list
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@communities_bp.route('/communities/<community_slug>', methods=['GET'])
@jwt_required()
def get_group_details(community_slug):
    """Get detailed information about a specific community by slug"""
    try:
        user_id = get_jwt_identity()
        
        # Look up community by slug instead of ID
        community = Community.query.filter_by(slug=community_slug, is_active=True).first()
        if not community:
            return jsonify({'error': 'Community not found'}), 404
        
        # Check if user can view this community
        if not can_view_group(community, user_id):
            return jsonify({'error': 'You do not have permission to view this community'}), 403
        
        # Get user's membership status (use community.id for membership checks)
        is_member = is_group_member(community.id, user_id)
        user_role = get_user_role_in_group(community.id, user_id) if is_member else None
        
        # Get community creator info
        creator = Users.query.get(community.created_by)
        
        # Get recent members (for display)
        recent_members = db.session.query(Users).join(
            CommunityMember,
            CommunityMember.user_id == Users.id
        ).filter(
            CommunityMember.community_id == community.id,
            CommunityMember.is_active == True
        ).order_by(CommunityMember.joined_at.desc()).limit(10).all()
        
        members_list = [{
            'id': member.id,
            'username': member.username,
            'display_name': member.display_name,
            'avatar': member.avatar
        } for member in recent_members]
        
        return jsonify({
            'id': community.id,
            'slug': community.slug,
            'name': community.name,
            'description': community.description,
            'category': community.category,
            'privacy_type': community.privacy_type,
            'cover_image': community.cover_image,
            'icon_image': community.icon_image,
            'rules': community.rules,
            'member_count': community.member_count,
            'is_verified': community.is_verified,
            'is_member': is_member,
            'user_role': user_role,
            'creator': {
                'id': creator.id,
                'username': creator.username,
                'display_name': creator.display_name,
                'avatar': creator.avatar
            } if creator else None,
            'recent_members': members_list,
            'created_at': community.created_at.isoformat(),
            'updated_at': community.updated_at.isoformat()
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@communities_bp.route('/communities/<community_slug>', methods=['PUT'])
@jwt_required()
def update_group(community_slug):
    """Update community information (admin/moderator only)"""
    try:
        user_id = get_jwt_identity()
        
        # Handle both JSON and FormData
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        community = Community.query.filter_by(slug=community_slug, is_active=True).first()
        if not community:
            return jsonify({'error': 'Community not found'}), 404
        
        # Check if user has permission to update
        user_role = get_user_role_in_group(community.id, user_id)
        if user_role not in ['admin', 'moderator']:
            return jsonify({'error': 'You do not have permission to update this community'}), 403
        
        
        # Handle file uploads
        cover_image_file = request.files.get('cover_image')
        icon_image_file = request.files.get('icon_image')
        
        if cover_image_file:
            filename = secure_filename(cover_image_file.filename)
            s3_path = f"groups/{community.id}/cover_{filename}"
            
            try:
                s3_client.upload_fileobj(
                    cover_image_file,
                    R2_BUCKET_NAME,
                    s3_path,
                    ExtraArgs={'ACL': 'public-read'}
                )
                community.cover_image = f"{IMAGE_PREFIX}/{s3_path}"
            except Exception as e:
                return jsonify({'error': f'Failed to upload cover image: {str(e)}'}), 500
        
        if icon_image_file:
            filename = secure_filename(icon_image_file.filename)
            s3_path = f"groups/{community.id}/icon_{filename}"
            
            try:
                s3_client.upload_fileobj(
                    icon_image_file,
                    R2_BUCKET_NAME,
                    s3_path,
                    ExtraArgs={'ACL': 'public-read'}
                )
                community.icon_image = f"{IMAGE_PREFIX}/{s3_path}"
            except Exception as e:
                return jsonify({'error': f'Failed to upload icon image: {str(e)}'}), 500
        
        # Update allowed fields from JSON/form data
        if 'name' in data:
            community.name = data['name']
        if 'description' in data:
            community.description = data['description']
        if 'category' in data:
            community.category = data['category']
        if 'privacy_type' in data and user_role == 'admin':
            community.privacy_type = data['privacy_type']
        if 'rules' in data:
            community.rules = data['rules']
        
        community.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'message': 'Community updated successfully',
            'community': {
                'id': community.id,
                'slug': community.slug,
                'name': community.name,
                'description': community.description,
                'category': community.category,
                'privacy_type': community.privacy_type,
                'cover_image': community.cover_image,
                'icon_image': community.icon_image,
                'updated_at': community.updated_at.isoformat()
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@communities_bp.route('/communities/<community_id>', methods=['DELETE'])
@jwt_required()
def delete_group(community_id):
    """Delete a community (admin only)"""
    try:
        user_id = get_jwt_identity()
        
        community = Community.query.filter_by(id=community_id, is_active=True).first()
        if not community:
            return jsonify({'error': 'Community not found'}), 404
        
        # Check if user is admin
        user_role = get_user_role_in_group(community_id, user_id)
        if user_role != 'admin':
            return jsonify({'error': 'Only community admin can delete the community'}), 403
        
        # Soft delete
        community.is_active = False
        community.updated_at = datetime.utcnow()
        
        # Deactivate all memberships
        CommunityMember.query.filter_by(community_id=community_id).update({'is_active': False})
        
        db.session.commit()
        
        return jsonify({'message': 'Community deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@communities_bp.route('/communities/<community_id>/transfer-ownership', methods=['PUT'])
@jwt_required()
def transfer_group_ownership(community_id):
    """Transfer community ownership to another member"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        new_owner_id = data.get('new_owner_id')
        
        if not new_owner_id:
            return jsonify({'error': 'New owner ID is required'}), 400
        
        community = Community.query.filter_by(id=community_id, is_active=True).first()
        if not community:
            return jsonify({'error': 'Community not found'}), 404
            
        # Verify current user is the owner (creator)
        if community.created_by != user_id:
             return jsonify({'error': 'Only the community owner can transfer ownership'}), 403
             
        # Verify new owner is a member
        new_owner_member = CommunityMember.query.filter_by(
            community_id=community_id,
            user_id=new_owner_id,
            is_active=True
        ).first()
        
        if not new_owner_member:
            return jsonify({'error': 'Selected user must be a member of the community'}), 400
            
        # Transfer ownership
        community.created_by = new_owner_id
        
        # Ensure new owner is admin
        new_owner_member.role = 'admin'
        
        # NOTE: The old owner remains an admin by default as they were the creator. 
        # We don't need to change their role explicitly as 'admin' is appropriate.
        
        # Create notification for new owner
        notification = EnhancedNotification(
            type='GROUP_OWNERSHIP_TRANSFERRED',
            priority='high',
            recipient_id=new_owner_id,
            sender_id=user_id,
            community_id=community_id,
            title='You are now the Owner!',
            message=f'Ownership of {community.name} has been transferred to you.',
            action_url=f'/communities/{community.slug}'
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Community ownership transferred successfully',
            'new_owner_id': new_owner_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ============= Community Membership Management =============

@communities_bp.route('/communities/<community_id>/join', methods=['POST'])
@jwt_required()
def join_group(community_id):
    """Join a community"""
    try:
        user_id = get_jwt_identity()
        user = Users.query.get(user_id) # Need user info for validation
        
        community = Community.query.filter_by(id=community_id, is_active=True).first()

        if not community:
            return jsonify({'error': 'Community not found'}), 404
        
        # Check if already a member
        existing_member = CommunityMember.query.filter_by(
            community_id=community_id,
            user_id=user_id
        ).first()
        
        if existing_member:
            if existing_member.is_active:
                return jsonify({'error': 'You are already a member of this community'}), 400
            else:
                # Reactivate membership
                existing_member.is_active = True
                existing_member.joined_at = datetime.utcnow()
        else:
            # Check if community is private
            # Check if community is private/secret
            if community.privacy_type == 'secret' or community.privacy_type == 'private':
                return jsonify({'error': 'This community is invite-only. You need an invitation link to join.'}), 403
            
            # Check University Restriction
            if community.university_restriction:
                # If restriction is set, user MUST have matching university
                if not user.university or community.university_restriction.lower() != user.university.lower():
                     return jsonify({'error': f'This community is restricted to students of {community.university_restriction}'}), 403

            # Create new membership
            new_member = CommunityMember(

                community_id=community_id,
                user_id=user_id,
                role='member'
            )
            db.session.add(new_member)
        
        db.session.commit()
        update_group_member_count(community_id)
        
        # Send notification to community admins
        admins = CommunityMember.query.filter_by(
            community_id=community_id,
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
                    community_id=community_id,
                    title='New Community Member',
                    message=f'{user.username} joined {community.name}',
                    action_url=f'/communities/{community_id}'
                )
                db.session.add(notification)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Successfully joined the community',
            'community_id': community_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@communities_bp.route('/communities/<community_id>/leave', methods=['POST'])
@jwt_required()
def leave_group(community_id):
    """Leave a community"""
    try:
        user_id = get_jwt_identity()
        
        member = CommunityMember.query.filter_by(
            community_id=community_id,
            user_id=user_id,
            is_active=True
        ).first()
        
        if not member:
            return jsonify({'error': 'You are not a member of this community'}), 400
        
        # Check if user is the only admin
        if member.role == 'admin':
            admin_count = CommunityMember.query.filter_by(
                community_id=community_id,
                role='admin',
                is_active=True
            ).count()
            
            if admin_count == 1:
                return jsonify({'error': 'You cannot leave as you are the only admin. Please assign another admin first.'}), 400
        
        # Deactivate membership
        member.is_active = False
        db.session.commit()
        update_group_member_count(community_id)
        
        return jsonify({'message': 'Successfully left the community'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@communities_bp.route('/communities/<community_id>/members', methods=['GET'])
@jwt_required()
def get_group_members(community_id):
    """Get list of community members"""
    try:
        user_id = get_jwt_identity()
        
        community = Community.query.filter_by(id=community_id, is_active=True).first()
        if not community:
            return jsonify({'error': 'Community not found'}), 404
        
        # Check if user can view members
        if not can_view_group(community, user_id):
            return jsonify({'error': 'You do not have permission to view this community'}), 403
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        role_filter = request.args.get('role')
        
        # Query members
        query = db.session.query(Users, CommunityMember).join(
            CommunityMember,
            CommunityMember.user_id == Users.id
        ).filter(
            CommunityMember.community_id == community_id,
            CommunityMember.is_active == True
        )
        
        if role_filter:
            query = query.filter(CommunityMember.role == role_filter)
        
        # Order by role importance and join date
        query = query.order_by(
            db.case(
                (CommunityMember.role == 'admin', 0),
                (CommunityMember.role == 'moderator', 1),
                else_=2
            ),
            CommunityMember.joined_at.desc()
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

@communities_bp.route('/communities/<community_id>/members/<int:member_id>/role', methods=['PUT'])
@jwt_required()
def update_member_role(community_id, member_id):
    """Update a member's role (admin only)"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        new_role = data.get('role')
        
        if new_role not in ['admin', 'moderator', 'member']:
            return jsonify({'error': 'Invalid role'}), 400
        
        # Check if user is admin
        user_role = get_user_role_in_group(community_id, user_id)
        if user_role != 'admin':
            return jsonify({'error': 'Only community admins can change member roles'}), 403
        
        # Get target member
        target_member = CommunityMember.query.filter_by(
            community_id=community_id,
            user_id=member_id,
            is_active=True
        ).first()
        
        if not target_member:
            return jsonify({'error': 'Member not found'}), 404
        
        # Update role
        target_member.role = new_role
        db.session.commit()
        
        # Send notification to the member
        community = Community.query.get(community_id)
        notification = EnhancedNotification(
            type='GROUP_ROLE_CHANGED',
            priority='medium',
            recipient_id=member_id,
            sender_id=user_id,
            community_id=community_id,
            title='Community Role Updated',
            message=f'Your role in {community.name} has been changed to {new_role}',
            action_url=f'/communities/{community_id}'
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

# ============= Community Posts =============

@communities_bp.route('/communities/<community_slug>/posts', methods=['POST'])
@jwt_required()
def create_group_post(community_slug):
    """Create a post in a community"""
    try:
        user_id = get_jwt_identity()
        data = request.form  # Use form data to handle text and file uploads
        files = request.files.getlist('media')  # Get media files (images/videos)
        
        # Look up community by slug
        community = Community.query.filter_by(slug=community_slug, is_active=True).first()
        if not community:
            return jsonify({'error': 'Community not found'}), 404
        
        # Check if user is a member
        if not is_group_member(community.id, user_id):
            return jsonify({'error': 'You must be a member to post in this community'}), 403
        
        content = data.get('content', '').strip()
        if not content and not files:
            return jsonify({'error': 'Content or media is required'}), 400
        
        # Allow empty content if there are files
        if not content:
            content = ""
        
        # Handle media uploads
        uploaded_media = []
        if files:
            for file in files:
                if file:
                    filename = secure_filename(file.filename)
                    file_ext = filename.split('.')[-1].lower()
                    
                    # Validate media type
                    if file_ext not in ['jpg', 'jpeg', 'png', 'gif', 'mp4', 'mov', 'avif', 'webp']:
                        return jsonify({'error': f'Invalid file type: {file_ext}'}), 400
                    
                    # Set media type
                    media_type = 'image' if file_ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'avif'] else 'video'
                    
                    # Define the S3 (R2) file path
                    s3_path = f"groups/{community.id}/posts/{filename}"
                    
                    # Upload the file to R2
                    try:
                        s3_client.upload_fileobj(
                            file,
                            R2_BUCKET_NAME,
                            s3_path,
                            ExtraArgs={'ACL': 'public-read'}
                        )
                    except Exception as e:
                        return jsonify({'error': f'Failed to upload media: {str(e)}'}), 500
                    
                    # Generate the R2 URL
                    r2_url = f"{IMAGE_PREFIX}/{s3_path}"
                    uploaded_media.append({
                        'media_url': r2_url,
                        'media_type': media_type
                    })
        
        # Create the yap first (with community_id for attribution)
        yap = Yap(
            id=cuid(),
            content=content,
            user_id=user_id,
            location=data.get('location'),
            community_id=community.id  # Link yap to community
        )
        db.session.add(yap)
        db.session.flush()
        
        # Add media entries to the database
        for media in uploaded_media:
            new_media = YapMedia(
                yap_id=yap.id,
                media_url=media['media_url'],
                media_type=media['media_type']
            )
            db.session.add(new_media)
        
        # Create community post association
        group_post = CommunityPost(
            id=cuid(),
            community_id=community.id,
            yap_id=yap.id,
            is_pinned=False
        )
        db.session.add(group_post)
        db.session.flush()
        
        # Extract and process community hashtags (separate from main yap hashtags)
        hashtag_pattern = r'#(\w+)'
        hashtags = re.findall(hashtag_pattern, content)
        
        for hashtag_name in hashtags:
            hashtag_name = hashtag_name.lower()
            
            # Check if community hashtag exists for this community
            community_hashtag = CommunityHashtag.query.filter_by(
                name=hashtag_name,
                community_id=community.id
            ).first()
            
            if not community_hashtag:
                # Create new community hashtag
                community_hashtag = CommunityHashtag(
                    name=hashtag_name,
                    community_id=community.id,
                    usage_count=1
                )
                db.session.add(community_hashtag)
                db.session.flush()
            else:
                # Increment usage count for trending
                community_hashtag.usage_count += 1
            
            # Link hashtag to community post
            group_post_hashtag = CommunityPostHashtag(
                community_post_id=group_post.id,
                community_hashtag_id=community_hashtag.id
            )
            db.session.add(group_post_hashtag)
        
        db.session.commit()
        
        # Get user info and badges for response
        user = Users.query.get(user_id)
        user_badges = db.session.query(UserBadge, Badge).join(Badge).filter(
            UserBadge.user_id == user.id,
            UserBadge.is_displayed == True
        ).order_by(UserBadge.display_order).limit(3).all()
        badges_data = [
            {'id': b.id, 'name': b.name, 'image_url': b.image_url, 'is_animated': b.is_animated}
            for _, b in user_badges
        ]

        return jsonify({
            'message': 'Post created successfully',
            'post': {
                'id': group_post.id,
                'yap_id': yap.id,
                'content': yap.content,
                'community_id': community.id,
                'community_slug': community.slug,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'display_name': user.display_name,
                    'avatar': user.avatar,
                    'badges': badges_data
                },
                'media': [{'media_url': m['media_url'], 'media_type': m['media_type']} for m in uploaded_media],
                'hashtags': hashtags,
                'created_at': yap.created_at.isoformat()
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@communities_bp.route('/communities/<community_slug>/posts', methods=['GET'])
@jwt_required()
def get_group_posts(community_slug):
    """Get posts from a community"""
    try:
        user_id = get_jwt_identity()
        
        community = Community.query.filter_by(slug=community_slug, is_active=True).first()
        if not community:
            return jsonify({'error': 'Community not found'}), 404
        
        # Check if user can view community
        if not can_view_group(community, user_id):
            return jsonify({'error': 'You do not have permission to view this community'}), 403
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # Query community posts
        query = db.session.query(CommunityPost, Yap, Users).join(
            Yap, CommunityPost.yap_id == Yap.id
        ).join(
            Users, Yap.user_id == Users.id
        ).filter(
            CommunityPost.community_id == community.id
        ).order_by(
            CommunityPost.is_pinned.desc(),
            CommunityPost.created_at.desc()
        )
        
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        posts = []
        for group_post, yap, user in paginated.items:
            # Get likes count
            likes_count = yap.likes.count() if yap.likes else 0
            replies_count = yap.replies.count() if yap.replies else 0
            
            # Get media for this yap
            media = []
            yap_media = YapMedia.query.filter_by(yap_id=yap.id).all()
            for m in yap_media:
                media.append({
                    'id': m.id,
                    'media_url': m.media_url,
                    'media_type': m.media_type
                })
            
            # Check if current user liked the post
            liked_by_user = False
            try:
                if user_id:
                    liked_by_user = Like.query.filter_by(yap_id=yap.id, user_id=user_id).first() is not None
            except Exception as e:
                print(f"Error checking like status for yap {yap.id}: {e}")
                # Don't fail the whole request, just default to False
                liked_by_user = False

            # Get user's displayed badges (same as yap_view)
            user_badges = db.session.query(UserBadge, Badge).join(Badge).filter(
                UserBadge.user_id == user.id,
                UserBadge.is_displayed == True
            ).order_by(UserBadge.display_order).limit(3).all()
            badges_data = [
                {'id': b.id, 'name': b.name, 'image_url': b.image_url, 'is_animated': b.is_animated}
                for _, b in user_badges
            ]

            posts.append({
                'id': group_post.id,
                'yap_id': yap.id,
                'content': yap.content,
                'location': yap.location,
                'is_pinned': group_post.is_pinned,
                'liked_by_user': liked_by_user,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'display_name': user.display_name,
                    'avatar': user.avatar,
                    'badges': badges_data
                },
                'media': media,
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

@communities_bp.route('/communities/<community_id>/posts/<post_id>/pin', methods=['PUT'])
@jwt_required()
def toggle_pin_post(community_id, post_id):
    """Pin or unpin a community post (admin/moderator only)"""
    try:
        user_id = get_jwt_identity()
        
        # Check if user has permission
        user_role = get_user_role_in_group(community_id, user_id)
        if user_role not in ['admin', 'moderator']:
            return jsonify({'error': 'Only admins and moderators can pin posts'}), 403
        
        # Get the community post
        group_post = CommunityPost.query.filter_by(
            id=post_id,
            community_id=community_id
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

@communities_bp.route('/my-communities', methods=['GET'])
@jwt_required()
def get_user_groups():
    """Get groups the current user is a member of"""
    try:
        user_id = get_jwt_identity()
        
        # Query user's groups
        user_groups = db.session.query(Community, CommunityMember).join(
            CommunityMember,
            CommunityMember.community_id == Community.id
        ).filter(
            CommunityMember.user_id == user_id,
            CommunityMember.is_active == True,
            Community.is_active == True
        ).order_by(CommunityMember.joined_at.desc()).all()
        
        groups = []
        for community, membership in user_groups:
            groups.append({
                'id': community.id,
                'name': community.name,
                'description': community.description,
                'category': community.category,
                'privacy_type': community.privacy_type,
                'icon_image': community.icon_image,
                'cover_image': community.cover_image,
                'slug': community.slug,
                'member_count': community.member_count,
                'user_role': membership.role,
                'joined_at': membership.joined_at.isoformat()
            })
        
        return jsonify({
            'groups': groups,
            'total': len(groups)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============= Moderation Actions =============

@communities_bp.route('/communities/<community_id>/members/<int:member_id>/kick', methods=['POST'])
@jwt_required()
def kick_member(community_id, member_id):
    """Kick a member from the community (admin/moderator only)"""
    try:
        user_id = get_jwt_identity()
        
        # Check permissions
        user_role = get_user_role_in_group(community_id, user_id)
        if user_role not in ['admin', 'moderator']:
            return jsonify({'error': 'You do not have permission to kick members'}), 403
            
        # Get target member
        target_member = CommunityMember.query.filter_by(
            community_id=community_id,
            user_id=member_id,
            is_active=True
        ).first()
        
        if not target_member:
            return jsonify({'error': 'Member not found'}), 404
            
        # Prevent kicking admins
        if target_member.role == 'admin':
             return jsonify({'error': 'Cannot kick an admin'}), 403
             
        # Moderators cannot kick other moderators
        if user_role == 'moderator' and target_member.role == 'moderator':
            return jsonify({'error': 'Moderators cannot kick other moderators'}), 403

        # Deactivate membership
        target_member.is_active = False
        db.session.commit()
        update_group_member_count(community_id)
        
        # Send notification
        community = Community.query.get(community_id)
        notification = EnhancedNotification(
            type='GROUP_KICKED',
            priority='high',
            recipient_id=member_id,
            sender_id=user_id,
            community_id=community_id,
            title='Removed from Community',
            message=f'You have been removed from {community.name}',
            action_url=f'/communities/discover'
        )
        db.session.add(notification)
        db.session.commit()
        
        return jsonify({'message': 'Member kicked successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@communities_bp.route('/communities/<community_id>/members/<int:member_id>/ban', methods=['POST'])
@jwt_required()
def ban_member(community_id, member_id):
    """Ban a member from the community (admin only for now)"""
    try:
        user_id = get_jwt_identity()
        
        # Check permissions - Strictly Admin for banning
        user_role = get_user_role_in_group(community_id, user_id)
        if user_role != 'admin':
            return jsonify({'error': 'Only admins can ban members'}), 403
            
        # Get target member (active or inactive)
        target_member = CommunityMember.query.filter_by(
            community_id=community_id,
            user_id=member_id
        ).first()
        
        if not target_member:
             # Even if not a member, we might want to create a banned record
             # For this simple implementation, we'll assume they must have interacted first
             # OR we create a "banned" status
            return jsonify({'error': 'Member record not found'}), 404
            
        if target_member.role == 'admin':
             return jsonify({'error': 'Cannot ban an admin'}), 403

        # Update role to 'banned' and deactivate
        target_member.role = 'banned'
        target_member.is_active = False
        db.session.commit()
        update_group_member_count(community_id)
        
        # Notification
        community = Community.query.get(community_id)
        notification = EnhancedNotification(
            type='GROUP_BANNED',
            priority='high',
            recipient_id=member_id,
            sender_id=user_id,
            community_id=community_id,
            title='Banned from Community',
            message=f'You have been banned from {community.name}',
            action_url=f'/communities/discover'
        )
        db.session.add(notification)
        db.session.commit()
        
        return jsonify({'message': 'Member banned successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@communities_bp.route('/communities/<community_id>/posts/<post_id>', methods=['DELETE'])
@jwt_required()
def delete_group_post(community_id, post_id):
    """Delete a community post (Admin/Mod or Author)"""
    try:
        user_id = get_jwt_identity()
        
        group_post = CommunityPost.query.filter_by(id=post_id, community_id=community_id).first()
        if not group_post:
             return jsonify({'error': 'Post not found'}), 404
             
        yap = Yap.query.get(group_post.yap_id)
        
        # Check permissions
        user_role = get_user_role_in_group(community_id, user_id)
        is_author = yap.user_id == user_id
        is_admin_mod = user_role in ['admin', 'moderator']
        
        if not (is_author or is_admin_mod):
            return jsonify({'error': 'You do not have permission to delete this post'}), 403
            
        # Delete association
        db.session.delete(group_post)
        
        # Optional: Delete actual yap if author? 
        # Usually community posts are just links to yaps, but if created within community context...
        # Let's keep the yap but just remove from community feed for now
        
        db.session.commit()
        
        return jsonify({'message': 'Post deleted from community'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ============= Community Invites =============

@communities_bp.route('/communities/<community_slug>/invites', methods=['POST'])
@jwt_required()
def create_invite(community_slug):
    """Create an invite link (members only)"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        community = Community.query.filter_by(slug=community_slug, is_active=True).first()
        if not community:
            return jsonify({'error': 'Community not found'}), 404
            
        # Check if user is a member
        if not is_group_member(community.id, user_id):
            return jsonify({'error': 'You must be a member to create invites'}), 403
            
        # Generate unique token
        token = secrets.token_urlsafe(8)
        while CommunityInvite.query.filter_by(token=token).first():
            token = secrets.token_urlsafe(8)
            
        # Set expiry
        expiry_option = data.get('expiry_option', 'none') # 'none', '12h', '7d', '21d'
        expires_at = None
        
        if expiry_option == '12h':
            expires_at = datetime.utcnow() + timedelta(hours=12)
        elif expiry_option == '7d':
            expires_at = datetime.utcnow() + timedelta(days=7)
        elif expiry_option == '21d':
            expires_at = datetime.utcnow() + timedelta(days=21)
            
        invite = CommunityInvite(
            id=cuid(),
            community_id=community.id,
            created_by=user_id,
            token=token,
            expires_at=expires_at,
            is_active=True
        )
        
        db.session.add(invite)
        db.session.commit()
        
        return jsonify({
            'message': 'Invite created successfully',
            'invite': {
                'token': invite.token,
                'expires_at': invite.expires_at.isoformat() if invite.expires_at else None,
                'url': f'/invite/{invite.token}'
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@communities_bp.route('/communities/<community_slug>/invites', methods=['GET'])
@jwt_required()
def get_invites(community_slug):
    """List active invites (admin only)"""
    try:
        user_id = get_jwt_identity()
        
        community = Community.query.filter_by(slug=community_slug, is_active=True).first()
        if not community:
            return jsonify({'error': 'Community not found'}), 404
            
        # Check if user is admin
        user_role = get_user_role_in_group(community.id, user_id)
        if user_role != 'admin':
            return jsonify({'error': 'Only admins can view invite lists'}), 403
            
        invites = CommunityInvite.query.filter_by(
            community_id=community.id,
            is_active=True
        ).order_by(CommunityInvite.created_at.desc()).all()
        
        return jsonify({
            'invites': [{
                'id': invite.id,
                'token': invite.token,
                'created_at': invite.created_at.isoformat(),
                'expires_at': invite.expires_at.isoformat() if invite.expires_at else None,
                'creator_id': invite.created_by,
                'url': f'/invite/{invite.token}'
            } for invite in invites]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@communities_bp.route('/invites/<token>', methods=['DELETE'])
@jwt_required()
def revoke_invite(token):
    """Revoke an invite link"""
    try:
        user_id = get_jwt_identity()
        
        invite = CommunityInvite.query.filter_by(token=token, is_active=True).first()
        if not invite:
            return jsonify({'error': 'Invite not found'}), 404
            
        # Check if user is admin of the community
        user_role = get_user_role_in_group(invite.community_id, user_id)
        if user_role != 'admin':
            return jsonify({'error': 'Only admins can revoke invites'}), 403
            
        invite.is_active = False
        db.session.commit()
        
        return jsonify({'message': 'Invite revoked successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@communities_bp.route('/invites/<token>', methods=['GET'])
def validate_invite(token):
    """Validate invite and return community info (public)"""
    try:
        invite = CommunityInvite.query.filter_by(token=token, is_active=True).first()
        
        if not invite:
            return jsonify({'error': 'Invalid or expired invite link', 'valid': False}), 404
            
        if invite.expires_at and invite.expires_at < datetime.utcnow():
            return jsonify({'error': 'This invite link has expired', 'valid': False}), 410
            
        community = Community.query.get(invite.community_id)
        creator = Users.query.get(community.created_by)
        
        return jsonify({
            'valid': True,
            'community': {
                'id': community.id,
                'slug': community.slug,
                'name': community.name,
                'description': community.description,
                'member_count': community.member_count,
                'cover_image': community.cover_image,
                'icon_image': community.icon_image,
                'university_restriction': community.university_restriction
            },
            'inviter': {
                'id': creator.id,
                'username': creator.username,
                'display_name': creator.display_name
            } if creator else None
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@communities_bp.route('/invites/<token>/accept', methods=['POST'])
@jwt_required()
def accept_invite(token):
    """Accept an invite and join the community"""
    try:
        user_id = get_jwt_identity()
        user = Users.query.get(user_id)
        
        invite = CommunityInvite.query.filter_by(token=token, is_active=True).first()
        if not invite:
            return jsonify({'error': 'Invalid or expired invite link'}), 404
            
        if invite.expires_at and invite.expires_at < datetime.utcnow():
            return jsonify({'error': 'This invite link has expired'}), 410
            
        community = Community.query.get(invite.community_id)
        
        # Check if already a member
        if is_group_member(community.id, user_id):
            return jsonify({
                'message': 'You are already a member',
                'community_slug': community.slug
            }), 200
            
        # Check university restriction
        if community.university_restriction:
            if not user.university or community.university_restriction.lower() != user.university.lower():
                return jsonify({
                    'error': 'ineligible', 
                    'message': f'Sorry, this community is restricted to students of {community.university_restriction}'
                }), 403
                
        # Create membership
        new_member = CommunityMember(
            community_id=community.id,
            user_id=user_id,
            role='member'
        )
        db.session.add(new_member)
        
        # Update counts
        update_group_member_count(community.id)
        
        # Send notification to inviter if different from joiner
        if invite.created_by != user_id:
            notification = EnhancedNotification(
                type='GROUP_INVITE_ACCEPTED',
                priority='low',
                recipient_id=invite.created_by,
                sender_id=user_id,
                community_id=community.id,
                title='Invite Accepted',
                message=f'{user.username} joined {community.name} using your invite link',
                action_url=f'/communities/{community.slug}'
            )
            db.session.add(notification)
            
        db.session.commit()
        
        return jsonify({
            'message': 'Successfully joined community',
            'community_slug': community.slug
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


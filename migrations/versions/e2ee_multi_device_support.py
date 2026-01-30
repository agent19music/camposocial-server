"""E2EE Multi-Device Support Tables

Revision ID: e2ee_multi_device
Revises: 81e53da69a82
Create Date: 2026-01-26

This migration adds support for multi-device E2EE:
- user_devices: Tracks registered devices with their public keys
- encrypted_key_backups: Stores encrypted private key backups for recovery
- message_recipient_keys: Stores per-device encrypted message content
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e2ee_multi_device'
down_revision = '81e53da69a82'
branch_labels = None
depends_on = None


def upgrade():
    # Create user_devices table
    op.create_table('user_devices',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('device_name', sa.String(100), nullable=True),
        sa.Column('device_type', sa.String(20), nullable=True),
        sa.Column('public_key', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_active', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('user_agent', sa.String(512), nullable=True),
    )
    
    # Create indexes for user_devices
    op.create_index('idx_user_devices_user', 'user_devices', ['user_id', 'is_active'])
    
    # Create encrypted_key_backups table
    op.create_table('encrypted_key_backups',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, unique=True),
        sa.Column('encrypted_private_key', sa.Text(), nullable=False),
        sa.Column('key_salt', sa.String(64), nullable=False),
        sa.Column('key_iv', sa.String(32), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    
    # Create message_recipient_keys table
    op.create_table('message_recipient_keys',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('message_id', sa.Integer(), sa.ForeignKey('messages.id'), nullable=False),
        sa.Column('device_id', sa.String(36), sa.ForeignKey('user_devices.id'), nullable=False),
        sa.Column('encrypted_content', sa.Text(), nullable=False),
        sa.Column('nonce', sa.String(64), nullable=False),
    )
    
    # Create indexes for message_recipient_keys
    op.create_index('idx_message_recipient_keys_message', 'message_recipient_keys', ['message_id'])
    op.create_index('idx_message_recipient_keys_device', 'message_recipient_keys', ['device_id'])


def downgrade():
    # Drop indexes
    op.drop_index('idx_message_recipient_keys_device', 'message_recipient_keys')
    op.drop_index('idx_message_recipient_keys_message', 'message_recipient_keys')
    op.drop_index('idx_user_devices_user', 'user_devices')
    
    # Drop tables
    op.drop_table('message_recipient_keys')
    op.drop_table('encrypted_key_backups')
    op.drop_table('user_devices')

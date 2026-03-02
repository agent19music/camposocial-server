"""Add Signal Protocol E2EE tables and Message fields

Revision ID: signal_e2ee_001
Revises: f9e8d7c6b5a4
Create Date: 2026-02-18 14:01:49.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'signal_e2ee_001'
down_revision = 'f9e8d7c6b5a4'
branch_labels = None
depends_on = None


def upgrade():
    # Create Signal identity keys table
    op.create_table('signal_identity_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.String(length=36), nullable=False),
        sa.Column('identity_key', sa.Text(), nullable=False),
        sa.Column('registration_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'device_id', name='uq_signal_identity_user_device')
    )
    op.create_index('idx_signal_identity_user_device', 'signal_identity_keys', ['user_id', 'device_id'], unique=False)

    # Create Signal signed pre-keys table
    op.create_table('signal_signed_prekeys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.String(length=36), nullable=False),
        sa.Column('key_id', sa.Integer(), nullable=False),
        sa.Column('public_key', sa.Text(), nullable=False),
        sa.Column('signature', sa.Text(), nullable=False),
        sa.Column('timestamp', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'device_id', 'key_id', name='uq_signal_signed_prekey')
    )
    op.create_index('idx_signal_signed_prekey_user_device', 'signal_signed_prekeys', ['user_id', 'device_id'], unique=False)

    # Create Signal one-time pre-keys table
    op.create_table('signal_onetime_prekeys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.String(length=36), nullable=False),
        sa.Column('key_id', sa.Integer(), nullable=False),
        sa.Column('public_key', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'device_id', 'key_id', name='uq_signal_onetime_prekey')
    )
    op.create_index('idx_signal_onetime_prekey_user_device', 'signal_onetime_prekeys', ['user_id', 'device_id'], unique=False)

    # Add Signal Protocol fields to messages table
    op.add_column('messages', sa.Column('message_type', sa.String(length=20), nullable=True))
    op.add_column('messages', sa.Column('sender_device_id', sa.String(length=36), nullable=True))
    op.add_column('messages', sa.Column('sender_registration_id', sa.Integer(), nullable=True))


def downgrade():
    # Remove Signal Protocol fields from messages table
    op.drop_column('messages', 'sender_registration_id')
    op.drop_column('messages', 'sender_device_id')
    op.drop_column('messages', 'message_type')

    # Drop Signal one-time pre-keys table
    op.drop_index('idx_signal_onetime_prekey_user_device', table_name='signal_onetime_prekeys')
    op.drop_table('signal_onetime_prekeys')

    # Drop Signal signed pre-keys table
    op.drop_index('idx_signal_signed_prekey_user_device', table_name='signal_signed_prekeys')
    op.drop_table('signal_signed_prekeys')

    # Drop Signal identity keys table
    op.drop_index('idx_signal_identity_user_device', table_name='signal_identity_keys')
    op.drop_table('signal_identity_keys')

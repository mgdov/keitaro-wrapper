"""Initial local campaign and stream snapshots.

Revision ID: 001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('campaigns', sa.Column('id', sa.Integer(), primary_key=True, autoincrement=False),
                    sa.Column('name', sa.String(255), nullable=False))
    op.create_table('streams', sa.Column('id', sa.Integer(), primary_key=True, autoincrement=False),
                    sa.Column('campaign_id', sa.Integer(), sa.ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=False),
                    sa.Column('name', sa.String(255), nullable=False), sa.Column('position', sa.Integer(), nullable=False),
                    sa.Column('editable', sa.Boolean(), nullable=False), sa.Column('baseline', sa.JSON(), nullable=False),
                    sa.Column('draft', sa.JSON(), nullable=False), sa.Column('version', sa.Integer(), nullable=False),
                    sa.Column('updated_at', sa.String(40), nullable=False))
    op.create_index('ix_streams_campaign_id', 'streams', ['campaign_id'])


def downgrade():
    op.drop_table('streams')
    op.drop_table('campaigns')

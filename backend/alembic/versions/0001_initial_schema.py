"""initial schema

The whole v2 schema, including the ownership columns: friends and debates
belong to an anonymous visitor (owner_key), and seeded public figures are
marked is_public. The public figures themselves are written at app startup,
not here, so editing the data file never needs a migration.

Revision ID: 0001
Revises:
Create Date: 2026-09-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('debates',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('topic', sa.Text(), nullable=False),
    sa.Column('owner_key', sa.String(length=64), nullable=True),
    sa.Column('model_provider', sa.String(length=50), nullable=False),
    sa.Column('model_name', sa.String(length=100), nullable=False),
    sa.Column('temperature', sa.Float(), nullable=False),
    sa.Column('top_p', sa.Float(), nullable=False),
    sa.Column('max_tokens', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_debates_owner_key', 'debates', ['owner_key'], unique=False)

    op.create_table('friends',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('raw_description', sa.Text(), nullable=False),
    sa.Column('owner_key', sa.String(length=64), nullable=True),
    sa.Column('is_public', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_friends_owner_key', 'friends', ['owner_key'], unique=False)

    op.create_table('debate_participants',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('debate_id', sa.UUID(), nullable=False),
    sa.Column('friend_id', sa.UUID(), nullable=False),
    sa.Column('slot', sa.Integer(), nullable=False),
    sa.Column('position', sa.String(length=20), nullable=True),
    sa.Column('participant_label', sa.String(length=20), nullable=True),
    sa.ForeignKeyConstraint(['debate_id'], ['debates.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['friend_id'], ['friends.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('personas',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('friend_id', sa.UUID(), nullable=False),
    sa.Column('persona_json', sa.JSON(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['friend_id'], ['friends.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('debate_messages',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('debate_id', sa.UUID(), nullable=False),
    sa.Column('participant_id', sa.UUID(), nullable=False),
    sa.Column('round_number', sa.Integer(), nullable=False),
    sa.Column('phase', sa.String(length=20), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('structured_output', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['debate_id'], ['debates.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['participant_id'], ['debate_participants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('evaluations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('debate_id', sa.UUID(), nullable=False),
    sa.Column('winner_participant_id', sa.UUID(), nullable=True),
    sa.Column('scores_json', sa.JSON(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['debate_id'], ['debates.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['winner_participant_id'], ['debate_participants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('debate_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('evaluations')
    op.drop_table('debate_messages')
    op.drop_table('personas')
    op.drop_table('debate_participants')
    op.drop_index('ix_friends_owner_key', table_name='friends')

    op.drop_table('friends')
    op.drop_index('ix_debates_owner_key', table_name='debates')

    op.drop_table('debates')

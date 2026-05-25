"""add_created_by_to_screening_jobs

Revision ID: 0536bae1be60
Revises: 8e50fd9a084b
Create Date: 2026-05-22 19:24:36.453260

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0536bae1be60'
down_revision: Union[str, None] = '8e50fd9a084b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('screening_jobs', sa.Column('created_by', sa.String(255), nullable=True))
    op.create_index('ix_screening_jobs_created_by', 'screening_jobs', ['created_by'])


def downgrade() -> None:
    op.drop_index('ix_screening_jobs_created_by', table_name='screening_jobs')
    op.drop_column('screening_jobs', 'created_by')

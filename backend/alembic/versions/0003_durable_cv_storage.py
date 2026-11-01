"""Optional durable CV storage for cloud hosts with ephemeral local disks."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("resume_documents", sa.Column("source_bytes", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("resume_documents", "source_bytes")

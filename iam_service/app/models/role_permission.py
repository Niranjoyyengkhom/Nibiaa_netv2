from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RolePermission(Base):
    """
    Junction table linking Roles to granular Permissions.
    """
    __tablename__ = "iam_role_permissions"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    role_id: Mapped[int] = mapped_column(
        ForeignKey("iam_roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    permission_id: Mapped[int] = mapped_column(
        ForeignKey("iam_permissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_iam_role_permission"),
    )

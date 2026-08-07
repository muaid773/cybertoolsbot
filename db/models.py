from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from .dbase import Base


# ==========================================================
# المستخدمون
# ==========================================================

class User(Base):
    __tablename__ = "users"

    telegram_id = Column(BigInteger, primary_key=True)

    username = Column(String(100))
    first_name = Column(String(100))

    # نقاط المستخدم (تُستخدم في عمليات البحث)
    points = Column(Integer, default=0, nullable=False)

    # عدد جهات الاتصال التي رفعها المستخدم (تُستخدم لحساب المكافآت)
    uploaded_contacts = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    uploaded_links = relationship(
        "UserContact",
        back_populates="user",
        cascade="all, delete-orphan",
    )


# ==========================================================
# الأرقام (جدول ثابت - قاعدة بيانات الأرقام)
# ==========================================================

class Contact(Base):
    """رقم هاتف واحد فريد، بمثابة سجل كاشف الأرقام."""

    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True)

    phone = Column(String(30), unique=True, index=True, nullable=False)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # كل الأسماء المرتبطة بهذا الرقم (قد يحفظه أشخاص بأسماء مختلفة)
    names = relationship(
        "ContactName",
        back_populates="contact",
        cascade="all, delete-orphan",
    )

    # كل من قام برفع/امتلاك هذا الرقم
    links = relationship(
        "UserContact",
        back_populates="contact",
        cascade="all, delete-orphan",
    )


# ==========================================================
# الأسماء (جدول ثابت - مرتبط بالأرقام)
# ==========================================================

class ContactName(Base):
    """اسم واحد مرتبط برقم هاتف. الرقم الواحد قد يملك عدة أسماء."""

    __tablename__ = "contact_names"

    id = Column(Integer, primary_key=True)

    contact_id = Column(
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name = Column(String(255), nullable=False, index=True)

    contact = relationship("Contact", back_populates="names")


# ==========================================================
# الربط بين المستخدم والرقم الذي رفعه
# ==========================================================

class UserContact(Base):
    """
    يمنع الرفع المكرر لنفس الرقم من نفس المستخدم،
    ويُستخدم أيضاً لحساب عدد جهات الاتصال التي رفعها كل مستخدم.
    """

    __tablename__ = "user_contacts"

    id = Column(Integer, primary_key=True)

    user_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False,
    )

    contact_id = Column(
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="uploaded_links")
    contact = relationship("Contact", back_populates="links")

    __table_args__ = (
        UniqueConstraint("user_id", "contact_id", name="uq_user_contact"),
    )
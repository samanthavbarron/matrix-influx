"""Database schema for Matrix message storage."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

class Message(Base):
    """Matrix message model."""
    __tablename__ = "matrix_messages"

    id = Column(Integer, primary_key=True)
    room_id = Column(String(255), nullable=False, index=True)
    sender = Column(String(255), nullable=False, index=True)
    message_type = Column(String(50), nullable=False)
    content = Column(Text, nullable=True)
    content_length = Column(Integer, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

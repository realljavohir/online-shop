from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String(100))
    full_name = Column(String(200))
    phone = Column(String(20))
    role = Column(String(20), default='customer')  # customer, driver, admin
    created_at = Column(DateTime, default=datetime.now)
    
    orders = relationship("Order", back_populates="user", foreign_keys='Order.user_id')
    driver_orders = relationship("Order", back_populates="driver", foreign_keys='Order.driver_id')

class Order(Base):
    __tablename__ = 'orders'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.telegram_id'), nullable=False)
    driver_id = Column(Integer, ForeignKey('users.telegram_id'), nullable=True)
    address_from = Column(Text, nullable=False)
    address_to = Column(Text, nullable=False)
    weight = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    status = Column(String(20), default='pending')  # pending, accepted, in_progress, completed, cancelled
    created_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)
    
    user = relationship("User", foreign_keys=[user_id], back_populates="orders")
    driver = relationship("User", foreign_keys=[driver_id], back_populates="driver_orders")

# Database sozlamalari
DATABASE_URL = "sqlite:///delivery_bot.db"  # PostgreSQL uchun o'zgartirish mumkin
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def init_db():
    """Bazani yaratish"""
    Base.metadata.create_all(bind=engine)

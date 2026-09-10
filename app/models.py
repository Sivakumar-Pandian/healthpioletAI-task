import enum

from sqlalchemy import Column, Enum, Float, Integer, String

from app.database import Base


class LocationType(str, enum.Enum):
    WAREHOUSE = "WAREHOUSE"
    BRANCH = "BRANCH"


class UserRole(str, enum.Enum):
    BRANCH_STAFF = "BRANCH_STAFF"
    CENTRAL_PURCHASING = "CENTRAL_PURCHASING"
    RECEIVING_STAFF = "RECEIVING_STAFF"


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    unit = Column(String, nullable=False)
    storage_condition = Column(String)
    purchase_price = Column(Float, nullable=False)
    tax_percent = Column(Float, nullable=False, default=0)


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    contact = Column(String)


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(Enum(LocationType), nullable=False)


class AppUser(Base):
    __tablename__ = "app_users"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False)

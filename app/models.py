import enum
import datetime

from sqlalchemy import Column, DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

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


class RequisitionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class Requisition(Base):
    __tablename__ = "requisitions"

    id = Column(Integer, primary_key=True)
    document_no = Column(String, unique=True, nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    required_date = Column(String, nullable=False)
    requester_id = Column(Integer, ForeignKey("app_users.id"), nullable=False)
    reason = Column(String)
    status = Column(
        Enum(RequisitionStatus),
        nullable=False,
        default=RequisitionStatus.SUBMITTED,
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    location = relationship("Location")
    product = relationship("Product")
    requester = relationship("AppUser")


class PurchaseOrderStatus(str, enum.Enum):
    OPEN = "OPEN"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    CLOSED = "CLOSED"


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id = Column(Integer, primary_key=True)
    document_no = Column(String, unique=True, nullable=False)
    requisition_id = Column(Integer, ForeignKey("requisitions.id"), nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    tax_percent = Column(Float, nullable=False)
    value_before_tax = Column(Float, nullable=False)
    tax_amount = Column(Float, nullable=False)
    total_value = Column(Float, nullable=False)
    delivery_location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    status = Column(
        Enum(PurchaseOrderStatus),
        nullable=False,
        default=PurchaseOrderStatus.OPEN,
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    requisition = relationship("Requisition")
    supplier = relationship("Supplier")
    product = relationship("Product")
    delivery_location = relationship("Location")

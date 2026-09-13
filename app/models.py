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
    COMPANY_ADMIN = "COMPANY_ADMIN"


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    code = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


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
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)

    company = relationship("Company")


class AppUser(Base):
    __tablename__ = "app_users"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=True)
    password_hash = Column(String, nullable=True)
    role = Column(Enum(UserRole), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    home_location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)

    company = relationship("Company")
    home_location = relationship("Location", foreign_keys=[home_location_id])


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True)
    session_token = Column(String, unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("app_users.id"), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("AppUser")


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


class StockStatus(str, enum.Enum):
    USABLE = "USABLE"
    QUARANTINED = "QUARANTINED"


class LedgerTxnType(str, enum.Enum):
    RECEIPT = "RECEIPT"
    DAMAGE = "DAMAGE"
    CORRECTION = "CORRECTION"
    TRANSFER_OUT = "TRANSFER_OUT"
    TRANSFER_IN = "TRANSFER_IN"
    ISSUE = "ISSUE"


class GoodsReceiptNote(Base):
    __tablename__ = "goods_receipt_notes"

    id = Column(Integer, primary_key=True)
    document_no = Column(String, unique=True, nullable=False)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    batch_number = Column(String, nullable=False)
    expiry_date = Column(String, nullable=False)
    physical_quantity = Column(Integer, nullable=False)
    accepted_quantity = Column(Integer, nullable=False)
    damaged_quantity = Column(Integer, nullable=False)
    missing_quantity = Column(Integer, nullable=False)
    photo_path = Column(String, nullable=True)
    posted_by_id = Column(Integer, ForeignKey("app_users.id"), nullable=False)
    posted_at = Column(DateTime, default=datetime.datetime.utcnow)

    purchase_order = relationship("PurchaseOrder")
    posted_by = relationship("AppUser")


class GrnCorrection(Base):
    __tablename__ = "grn_corrections"

    id = Column(Integer, primary_key=True)
    original_grn_id = Column(
        Integer, ForeignKey("goods_receipt_notes.id"), nullable=False
    )
    old_accepted_quantity = Column(Integer, nullable=False)
    old_damaged_quantity = Column(Integer, nullable=False)
    old_missing_quantity = Column(Integer, nullable=False)
    new_accepted_quantity = Column(Integer, nullable=False)
    new_damaged_quantity = Column(Integer, nullable=False)
    new_missing_quantity = Column(Integer, nullable=False)
    reason = Column(String, nullable=False)
    photo_path = Column(String, nullable=True)
    corrected_by_id = Column(Integer, ForeignKey("app_users.id"), nullable=False)
    corrected_at = Column(DateTime, default=datetime.datetime.utcnow)

    original_grn = relationship("GoodsReceiptNote")
    corrected_by = relationship("AppUser")


class SupplierInvoiceStatus(str, enum.Enum):
    MATCHED = "MATCHED"
    DISPUTED = "DISPUTED"


class SupplierInvoice(Base):
    __tablename__ = "supplier_invoices"

    id = Column(Integer, primary_key=True)
    document_no = Column(String, unique=True, nullable=False)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    grn_id = Column(Integer, ForeignKey("goods_receipt_notes.id"), nullable=False)
    invoiced_quantity = Column(Integer, nullable=False)
    invoiced_value = Column(Float, nullable=False)
    status = Column(Enum(SupplierInvoiceStatus), nullable=False)
    payable_amount = Column(Float, nullable=False)
    disputed_amount = Column(Float, nullable=False, default=0)
    credit_note_reference = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    purchase_order = relationship("PurchaseOrder")
    goods_receipt_note = relationship("GoodsReceiptNote")


class StockTransferStatus(str, enum.Enum):
    DISPATCHED = "DISPATCHED"
    RECEIVED = "RECEIVED"


class StockTransfer(Base):
    __tablename__ = "stock_transfers"

    id = Column(Integer, primary_key=True)
    document_no = Column(String, unique=True, nullable=False)
    source_location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    destination_location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    batch_number = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    status = Column(
        Enum(StockTransferStatus),
        nullable=False,
        default=StockTransferStatus.DISPATCHED,
    )
    dispatched_by_id = Column(Integer, ForeignKey("app_users.id"), nullable=False)
    dispatched_at = Column(DateTime, default=datetime.datetime.utcnow)
    received_by_id = Column(Integer, ForeignKey("app_users.id"), nullable=True)
    received_at = Column(DateTime, nullable=True)

    source_location = relationship("Location", foreign_keys=[source_location_id])
    destination_location = relationship("Location", foreign_keys=[destination_location_id])
    product = relationship("Product")
    dispatched_by = relationship("AppUser", foreign_keys=[dispatched_by_id])
    received_by = relationship("AppUser", foreign_keys=[received_by_id])


class SalesInvoice(Base):
    __tablename__ = "sales_invoices"

    id = Column(Integer, primary_key=True)
    document_no = Column(String, unique=True, nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    batch_number = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    tax_percent = Column(Float, nullable=False)
    value_before_tax = Column(Float, nullable=False)
    tax_amount = Column(Float, nullable=False)
    total_amount = Column(Float, nullable=False)
    cost_of_goods = Column(Float, nullable=False)
    payment_mode = Column(String, nullable=False)
    prescription_reference = Column(String, nullable=True)
    dispensed_by_id = Column(Integer, ForeignKey("app_users.id"), nullable=False)
    dispensed_at = Column(DateTime, default=datetime.datetime.utcnow)

    location = relationship("Location")
    product = relationship("Product")
    dispensed_by = relationship("AppUser")


class StockLedgerEntry(Base):
    __tablename__ = "stock_ledger_entries"

    id = Column(Integer, primary_key=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    batch_number = Column(String, nullable=False)
    txn_type = Column(Enum(LedgerTxnType), nullable=False)
    stock_status = Column(Enum(StockStatus), nullable=False)
    quantity_in = Column(Integer, nullable=False, default=0)
    quantity_out = Column(Integer, nullable=False, default=0)
    reference_document = Column(String, nullable=False)
    performed_by_id = Column(Integer, ForeignKey("app_users.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    location = relationship("Location")
    product = relationship("Product")
    performed_by = relationship("AppUser")

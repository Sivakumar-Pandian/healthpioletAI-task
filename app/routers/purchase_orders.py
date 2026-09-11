from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.context import header_context, success_redirect
from app.database import get_db
from app.document_numbers import next_document_number
from app.models import (
    Location,
    PurchaseOrder,
    PurchaseOrderStatus,
    Requisition,
    RequisitionStatus,
    Supplier,
    GoodsReceiptNote,
)

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])
templates = Jinja2Templates(directory="templates")


def get_requisition_for_po(db: Session, requisition_id: int):
    requisition = db.get(Requisition, requisition_id)
    if requisition is None:
        raise HTTPException(status_code=404, detail="Requisition not found")
    if requisition.status != RequisitionStatus.APPROVED:
        raise HTTPException(status_code=422, detail="Only approved requisitions can be converted to purchase orders")
    if db.query(PurchaseOrder).filter(PurchaseOrder.requisition_id == requisition_id).first():
        raise HTTPException(status_code=422, detail="A purchase order already exists for this requisition")
    return requisition


def get_purchase_order_or_404(db: Session, purchase_order_id: int):
    purchase_order = db.get(PurchaseOrder, purchase_order_id)
    if purchase_order is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return purchase_order


@router.get("", response_class=HTMLResponse)
def list_purchase_orders(request: Request, db: Session = Depends(get_db)):
    context = header_context(db)
    context["purchase_orders"] = db.query(PurchaseOrder).order_by(PurchaseOrder.id).all()
    return templates.TemplateResponse(request, "purchase_orders_list.html", context)


@router.get("/new", response_class=HTMLResponse)
def new_purchase_order_form(
    requisition_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    requisition = get_requisition_for_po(db, requisition_id)
    context = header_context(db)
    context.update(
        {
            "requisition": requisition,
            "suppliers": db.query(Supplier).order_by(Supplier.name).all(),
        }
    )
    return templates.TemplateResponse(request, "purchase_orders_new.html", context)


@router.post("/new")
def create_purchase_order(
    requisition_id: int = Form(...),
    supplier_id: int = Form(...),
    unit_price: float = Form(...),
    tax_percent: float = Form(...),
    delivery_location_id: int = Form(...),
    db: Session = Depends(get_db),
):
    requisition = get_requisition_for_po(db, requisition_id)
    if unit_price < 0 or tax_percent < 0:
        raise HTTPException(status_code=422, detail="Price and tax percent must be non-negative")
    if db.get(Supplier, supplier_id) is None:
        raise HTTPException(status_code=422, detail="Supplier not found")
    if db.get(Location, delivery_location_id) is None:
        raise HTTPException(status_code=422, detail="Delivery location not found")

    value_before_tax = requisition.quantity * unit_price
    tax_amount = value_before_tax * tax_percent / 100
    purchase_order = PurchaseOrder(
        document_no=next_document_number(db, PurchaseOrder, "document_no", "PO"),
        requisition_id=requisition.id,
        supplier_id=supplier_id,
        product_id=requisition.product_id,
        quantity=requisition.quantity,
        unit_price=unit_price,
        tax_percent=tax_percent,
        value_before_tax=value_before_tax,
        tax_amount=tax_amount,
        total_value=value_before_tax + tax_amount,
        delivery_location_id=delivery_location_id,
        status=PurchaseOrderStatus.OPEN,
    )
    db.add(purchase_order)
    db.commit()
    return RedirectResponse(
        url=success_redirect("/purchase-orders", f"{purchase_order.document_no} created"),
        status_code=303,
    )


@router.get("/{purchase_order_id}", response_class=HTMLResponse)
def purchase_order_detail(
    purchase_order_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    context = header_context(db)
    purchase_order = get_purchase_order_or_404(db, purchase_order_id)
    context["purchase_order"] = purchase_order
    context["goods_receipt"] = (
        db.query(GoodsReceiptNote)
        .filter(GoodsReceiptNote.po_id == purchase_order.id)
        .first()
    )
    return templates.TemplateResponse(request, "purchase_orders_detail.html", context)

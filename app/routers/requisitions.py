from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.context import header_context, success_redirect
from app.database import get_db
from app.document_numbers import next_document_number
from app.models import (
    AppUser,
    Location,
    Product,
    PurchaseOrder,
    Requisition,
    RequisitionStatus,
)

router = APIRouter(prefix="/requisitions", tags=["requisitions"])
templates = Jinja2Templates(directory="templates")


def get_requisition_or_404(db: Session, requisition_id: int):
    requisition = db.get(Requisition, requisition_id)
    if requisition is None:
        raise HTTPException(status_code=404, detail="Requisition not found")
    return requisition


@router.get("", response_class=HTMLResponse)
def list_requisitions(
    request: Request,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    context = header_context(db)
    query = db.query(Requisition).order_by(Requisition.id)
    selected_status = status.upper() if status else None
    valid_statuses = {item.value for item in RequisitionStatus}
    if selected_status in valid_statuses:
        query = query.filter(Requisition.status == RequisitionStatus(selected_status))
    context["requisitions"] = query.all()
    context["selected_status"] = selected_status if selected_status in valid_statuses else None
    return templates.TemplateResponse(request, "requisitions_list.html", context)


@router.get("/new", response_class=HTMLResponse)
def new_requisition_form(request: Request, db: Session = Depends(get_db)):
    context = header_context(db)
    context["products"] = db.query(Product).order_by(Product.name).all()
    return templates.TemplateResponse(request, "requisitions_new.html", context)


@router.post("/new")
def create_requisition(
    product_id: int = Form(...),
    quantity: int = Form(...),
    required_date: str = Form(...),
    reason: str = Form(""),
    location_id: int = Form(...),
    requester_id: int = Form(...),
    db: Session = Depends(get_db),
):
    if quantity < 1:
        raise HTTPException(status_code=422, detail="Quantity must be at least one")

    if db.get(Product, product_id) is None:
        raise HTTPException(status_code=422, detail="Product not found")
    if db.get(Location, location_id) is None:
        raise HTTPException(status_code=422, detail="Location not found")
    if db.get(AppUser, requester_id) is None:
        raise HTTPException(status_code=422, detail="Requester not found")

    requisition = Requisition(
        document_no=next_document_number(db, Requisition, "document_no", "REQ"),
        location_id=location_id,
        product_id=product_id,
        quantity=quantity,
        required_date=required_date,
        requester_id=requester_id,
        reason=reason or None,
        status=RequisitionStatus.SUBMITTED,
    )
    db.add(requisition)
    db.commit()
    return RedirectResponse(
        url=success_redirect("/requisitions", f"{requisition.document_no} created"),
        status_code=303,
    )


@router.post("/{requisition_id}/approve")
def approve_requisition(requisition_id: int, db: Session = Depends(get_db)):
    requisition = get_requisition_or_404(db, requisition_id)
    if requisition.status == RequisitionStatus.SUBMITTED:
        requisition.status = RequisitionStatus.APPROVED
        db.commit()
    return RedirectResponse(
        url=success_redirect("/requisitions", f"{requisition.document_no} approved"),
        status_code=303,
    )


@router.post("/{requisition_id}/reject")
def reject_requisition(requisition_id: int, db: Session = Depends(get_db)):
    requisition = get_requisition_or_404(db, requisition_id)
    if requisition.status == RequisitionStatus.SUBMITTED:
        requisition.status = RequisitionStatus.REJECTED
        db.commit()
    return RedirectResponse(
        url=success_redirect("/requisitions", f"{requisition.document_no} rejected"),
        status_code=303,
    )


@router.get("/{requisition_id}", response_class=HTMLResponse)
def requisition_detail(
    requisition_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    requisition = get_requisition_or_404(db, requisition_id)
    context = header_context(db)
    context["requisition"] = requisition
    context["purchase_order"] = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.requisition_id == requisition.id)
        .first()
    )
    return templates.TemplateResponse(request, "requisitions_detail.html", context)

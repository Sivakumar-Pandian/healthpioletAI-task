from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.context import (
    get_acting_user,
    header_context,
    scoped_location_ids,
    success_redirect,
)
from app.database import get_db
from app.document_numbers import next_document_number
from app.models import (
    AppUser,
    Location,
    Product,
    PurchaseOrder,
    Requisition,
    RequisitionStatus,
    UserRole,
)
from app.traceability import build_chain

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
    context = header_context(db, request)
    acting_user = context["acting_user"]
    loc_ids = scoped_location_ids(db, acting_user)

    query = db.query(Requisition).order_by(Requisition.id)
    if loc_ids is not None:
        query = query.filter(Requisition.location_id.in_(loc_ids))

    selected_status = status.upper() if status else None
    valid_statuses = {item.value for item in RequisitionStatus}
    if selected_status in valid_statuses:
        query = query.filter(Requisition.status == RequisitionStatus(selected_status))
    context["requisitions"] = query.all()
    context["selected_status"] = selected_status if selected_status in valid_statuses else None
    return templates.TemplateResponse(request, "requisitions_list.html", context)


@router.get("/new", response_class=HTMLResponse)
def new_requisition_form(request: Request, db: Session = Depends(get_db)):
    context = header_context(db, request)
    context["products"] = db.query(Product).order_by(Product.name).all()
    return templates.TemplateResponse(request, "requisitions_new.html", context)


@router.post("/new")
def create_requisition(
    request: Request,
    product_id: int = Form(...),
    quantity: int = Form(...),
    required_date: str = Form(...),
    reason: str = Form(""),
    location_id: int | None = Form(None),
    requester_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    acting_user = get_acting_user(db, request, acting_as_id=requester_id)

    if requester_id is None and acting_user:
        requester_id = acting_user.id

    if location_id is None:
        if acting_user and acting_user.home_location_id:
            location_id = acting_user.home_location_id
        else:
            context = header_context(db, request)
            locations = context.get("locations", [])
            if locations:
                location_id = locations[0].id
            else:
                raise HTTPException(status_code=422, detail="Location required")

    # Force location_id for BRANCH_STAFF users to their home branch server-side
    if acting_user and acting_user.role == UserRole.BRANCH_STAFF and acting_user.home_location_id:
        location_id = acting_user.home_location_id

    if quantity < 1:
        raise HTTPException(status_code=422, detail="Quantity must be at least one")
    if db.get(Product, product_id) is None:
        raise HTTPException(status_code=422, detail="Product not found")
    if db.get(Location, location_id) is None:
        raise HTTPException(status_code=422, detail="Location not found")
    if requester_id is None or db.get(AppUser, requester_id) is None:
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
    context = header_context(db, request)
    acting_user = context["acting_user"]
    loc_ids = scoped_location_ids(db, acting_user)

    if loc_ids is not None and requisition.location_id not in loc_ids:
        raise HTTPException(status_code=403, detail="Access denied for this branch")

    context["requisition"] = requisition
    context["purchase_order"] = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.requisition_id == requisition.id)
        .first()
    )
    context["chain_steps"] = build_chain(db, requisition.id)
    return templates.TemplateResponse(request, "requisitions_detail.html", context)

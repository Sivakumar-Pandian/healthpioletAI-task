from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.requests import Request
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine, get_db
from app.context import header_context, scoped_location_ids, success_redirect
from app.models import (
    AppUser,
    GoodsReceiptNote,
    GrnCorrection,
    Location,
    LocationType,
    PurchaseOrder,
    PurchaseOrderStatus,
    Requisition,
    RequisitionStatus,
    StockLedgerEntry,
    StockStatus,
    SupplierInvoice,
    UserRole,
    Product,
    Supplier,
)
from app.stock import computed_stock
from app.routers.auth import router as auth_router
from app.routers.purchase_orders import router as purchase_orders_router
from app.routers.requisitions import router as requisitions_router
from app.routers.goods_receipts import router as goods_receipts_router
from app.routers.stock_ledger import router as stock_ledger_router
from app.routers.stock_transfers import router as stock_transfers_router
from app.routers.supplier_invoices import router as supplier_invoices_router
from app.routers.dispensing import router as dispensing_router
from app.routers.traceability import router as traceability_router
from app.routers.demo import router as demo_router
from app.routers.notifications import router as notifications_router
from app.routers.qr import router as qr_router
from app.seed import seed_if_empty

app = FastAPI()

# Create tables on startup
@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Set up Jinja2 templates
templates = Jinja2Templates(directory="templates")
app.include_router(auth_router)
app.include_router(requisitions_router)
app.include_router(purchase_orders_router)
app.include_router(goods_receipts_router)
app.include_router(stock_ledger_router)
app.include_router(supplier_invoices_router)
app.include_router(stock_transfers_router)
app.include_router(dispensing_router)
app.include_router(traceability_router)
app.include_router(demo_router)
app.include_router(notifications_router)
app.include_router(qr_router)




@app.get("/", response_class=HTMLResponse)
def read_root(
    request: Request,
    acting_as_id: int | None = None,
    location_id: int | None = None,
    db: Session = Depends(get_db),
):
    context = header_context(db, request, acting_as_id=acting_as_id)
    active_user = context["acting_user"]
    if active_user is None:
        return RedirectResponse(url="/login", status_code=303)

    loc_ids = scoped_location_ids(db, active_user)

    branch_location = None
    if active_user.role == UserRole.BRANCH_STAFF and active_user.home_location_id:
        branch_location = db.get(Location, active_user.home_location_id)
    elif location_id is not None:
        branch_location = db.get(Location, location_id)
    if branch_location is None:
        branch_location = (
            db.query(Location)
            .filter(Location.type == LocationType.BRANCH)
            .order_by(Location.id)
            .first()
        )

    goods_receipt_po_ids = db.query(GoodsReceiptNote.po_id)
    po_query = db.query(PurchaseOrder).filter(
        PurchaseOrder.status.in_(
            [PurchaseOrderStatus.OPEN, PurchaseOrderStatus.PARTIALLY_RECEIVED]
        ),
        ~PurchaseOrder.id.in_(goods_receipt_po_ids),
    )
    if loc_ids is not None:
        po_query = po_query.filter(PurchaseOrder.delivery_location_id.in_(loc_ids))
    ready_purchase_orders = po_query.order_by(PurchaseOrder.id).all()

    req_query = db.query(Requisition).filter(
        Requisition.status == RequisitionStatus.SUBMITTED
    )
    if loc_ids is not None:
        req_query = req_query.filter(Requisition.location_id.in_(loc_ids))
    approval_requisitions = req_query.order_by(Requisition.id).all()

    recent_requisitions = []
    if branch_location is not None:
        rec_query = db.query(Requisition)
        if loc_ids is not None:
            rec_query = rec_query.filter(Requisition.location_id.in_(loc_ids))
        else:
            rec_query = rec_query.filter(Requisition.location_id == branch_location.id)
        recent_requisitions = rec_query.order_by(Requisition.id.desc()).limit(5).all()

    loc_query = db.query(Location).order_by(Location.id)
    if loc_ids is not None:
        loc_query = loc_query.filter(Location.id.in_(loc_ids))

    stock_summary = []
    for location in loc_query.all():
        stock_summary.append(
            {
                "location": location,
                "usable": computed_stock(
                    db, location_id=location.id, stock_status=StockStatus.USABLE
                ),
                "quarantined": computed_stock(
                    db, location_id=location.id, stock_status=StockStatus.QUARANTINED
                ),
            }
        )

    tot_req = db.query(Requisition)
    tot_po = db.query(PurchaseOrder)
    tot_grn = db.query(GoodsReceiptNote)
    if loc_ids is not None:
        tot_req = tot_req.filter(Requisition.location_id.in_(loc_ids))
        tot_po = tot_po.filter(PurchaseOrder.delivery_location_id.in_(loc_ids))
        tot_grn = tot_grn.join(PurchaseOrder).filter(PurchaseOrder.delivery_location_id.in_(loc_ids))

    context.update(
        {
            "active_user": active_user,
            "branch_location": branch_location,
            "approval_requisitions": approval_requisitions,
            "ready_purchase_orders": ready_purchase_orders,
            "recent_requisitions": recent_requisitions,
            "total_requisitions": tot_req.count(),
            "total_purchase_orders": tot_po.count(),
            "total_goods_receipts": tot_grn.count(),
            "stock_summary": stock_summary,
        }
    )
    return templates.TemplateResponse(
        request,
        "index.html",
        context,
    )


@app.get("/master-data", response_class=HTMLResponse)
def master_data(request: Request, db: Session = Depends(get_db)):
    context = header_context(db, request)
    context.update(
        {
            "products": db.query(Product).order_by(Product.id).all(),
            "suppliers": db.query(Supplier).order_by(Supplier.id).all(),
        }
    )
    return templates.TemplateResponse(request, "master_data.html", context)

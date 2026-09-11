from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.requests import Request
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine, get_db
from app.context import header_context, success_redirect
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
from app.routers.purchase_orders import router as purchase_orders_router
from app.routers.requisitions import router as requisitions_router
from app.routers.goods_receipts import router as goods_receipts_router
from app.routers.stock_ledger import router as stock_ledger_router
from app.routers.supplier_invoices import router as supplier_invoices_router
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
app.include_router(requisitions_router)
app.include_router(purchase_orders_router)
app.include_router(goods_receipts_router)
app.include_router(stock_ledger_router)
app.include_router(supplier_invoices_router)


@app.get("/", response_class=HTMLResponse)
def read_root(
    request: Request,
    acting_as_id: int | None = Query(default=None),
    location_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    active_user = (
        db.get(AppUser, acting_as_id)
        if acting_as_id is not None
        else db.query(AppUser).order_by(AppUser.id).first()
    )
    if active_user is None:
        raise HTTPException(status_code=500, detail="No application users configured")

    branch_location = None
    if location_id is not None:
        branch_location = db.get(Location, location_id)
    if branch_location is None:
        branch_location = (
            db.query(Location)
            .filter(Location.type == LocationType.BRANCH)
            .order_by(Location.id)
            .first()
        )

    goods_receipt_po_ids = db.query(GoodsReceiptNote.po_id)
    ready_purchase_orders = (
        db.query(PurchaseOrder)
        .filter(
            PurchaseOrder.status.in_(
                [PurchaseOrderStatus.OPEN, PurchaseOrderStatus.PARTIALLY_RECEIVED]
            ),
            ~PurchaseOrder.id.in_(goods_receipt_po_ids),
        )
        .order_by(PurchaseOrder.id)
        .all()
    )
    approval_requisitions = (
        db.query(Requisition)
        .filter(Requisition.status == RequisitionStatus.SUBMITTED)
        .order_by(Requisition.id)
        .all()
    )
    recent_requisitions = []
    if active_user.role == UserRole.BRANCH_STAFF and branch_location is not None:
        recent_requisitions = (
            db.query(Requisition)
            .filter(Requisition.location_id == branch_location.id)
            .order_by(Requisition.id.desc())
            .limit(5)
            .all()
        )

    stock_summary = []
    for location in db.query(Location).order_by(Location.id).all():
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

    context = header_context(db)
    context.update(
        {
            "active_user": active_user,
            "branch_location": branch_location,
            "approval_requisitions": approval_requisitions,
            "ready_purchase_orders": ready_purchase_orders,
            "recent_requisitions": recent_requisitions,
            "total_requisitions": db.query(Requisition).count(),
            "total_purchase_orders": db.query(PurchaseOrder).count(),
            "total_goods_receipts": db.query(GoodsReceiptNote).count(),
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
    context = header_context(db)
    context.update(
        {
            "products": db.query(Product).order_by(Product.id).all(),
            "suppliers": db.query(Supplier).order_by(Supplier.id).all(),
        }
    )
    return templates.TemplateResponse(request, "master_data.html", context)


@app.post("/demo/reset")
def reset_demo_data(db: Session = Depends(get_db)):
    for model in (
        StockLedgerEntry,
        SupplierInvoice,
        GrnCorrection,
        GoodsReceiptNote,
        PurchaseOrder,
        Requisition,
    ):
        db.query(model).delete(synchronize_session=False)
    db.commit()
    return RedirectResponse(
        url=success_redirect("/", "Demo data reset — starting fresh."),
        status_code=303,
    )

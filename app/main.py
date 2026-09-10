from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.requests import Request
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine, get_db
from app.context import header_context
from app.models import Product, Supplier
from app.routers.purchase_orders import router as purchase_orders_router
from app.routers.requisitions import router as requisitions_router
from app.routers.goods_receipts import router as goods_receipts_router
from app.routers.stock_ledger import router as stock_ledger_router
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


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "index.html",
        header_context(db),
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

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.requests import Request
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine, get_db
from app.models import AppUser, Location, Product, Supplier, UserRole
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


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "index.html",
        template_context(db),
    )


@app.get("/master-data", response_class=HTMLResponse)
def master_data(request: Request, db: Session = Depends(get_db)):
    context = template_context(db)
    context.update(
        {
            "products": db.query(Product).order_by(Product.id).all(),
            "suppliers": db.query(Supplier).order_by(Supplier.id).all(),
        }
    )
    return templates.TemplateResponse(request, "master_data.html", context)


def template_context(db: Session):
    return {
        "locations": db.query(Location).order_by(Location.id).all(),
        "app_users": db.query(AppUser).order_by(AppUser.id).all(),
        "user_roles": [
            (UserRole.BRANCH_STAFF, "Branch Staff"),
            (UserRole.CENTRAL_PURCHASING, "Central Purchasing"),
            (UserRole.RECEIVING_STAFF, "Receiving Staff"),
        ],
    }

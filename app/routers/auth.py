from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import create_session, delete_session, hash_password, verify_password
from app.context import header_context, success_redirect
from app.database import get_db
from app.models import AppUser, Company, Location, LocationType, UserRole

router = APIRouter(prefix="", tags=["auth"])
templates = Jinja2Templates(directory="templates")


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, db: Session = Depends(get_db)):
    context = header_context(db, request)
    context["error"] = None
    return templates.TemplateResponse(request, "login.html", context)


@router.post("/login")
def handle_login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    email_clean = email.strip().lower()
    user = db.query(AppUser).filter(AppUser.email == email_clean).first()
    
    if user is None or not verify_password(password, user.password_hash or ""):
        context = header_context(db, request)
        context["error"] = "Invalid email or password"
        context["email"] = email
        return templates.TemplateResponse(request, "login.html", context, status_code=401)

    response = RedirectResponse(url=success_redirect("/", f"Welcome back, {user.name}!"), status_code=303)
    create_session(db, user.id, response=response)
    return response


@router.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request, db: Session = Depends(get_db)):
    context = header_context(db, request)
    context["error"] = None
    context["companies"] = db.query(Company).order_by(Company.name).all()
    context["locations"] = db.query(Location).order_by(Location.name).all()
    return templates.TemplateResponse(request, "signup.html", context)


@router.post("/signup")
def handle_signup(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    role: str = Form(""),
    company_name: str = Form(""),
    branch_name: str = Form(""),
    db: Session = Depends(get_db),
):
    name_clean = name.strip()
    email_clean = email.strip().lower()
    password_clean = password.strip()
    company_clean = company_name.strip()
    branch_clean = branch_name.strip()

    errors = []
    if not name_clean:
        errors.append("Full name is required.")
    if not email_clean or "@" not in email_clean:
        errors.append("Valid email address is required.")
    if not password_clean or len(password_clean) < 6:
        errors.append("Password must be at least 6 characters long.")
    if role not in [r.value for r in UserRole]:
        errors.append("Invalid user role selected.")
    if not company_clean:
        errors.append("Company name is required.")

    if db.query(AppUser).filter(AppUser.email == email_clean).first():
        errors.append("An account with this email address already exists.")

    if errors:
        context = header_context(db, request)
        context["error"] = errors[0]
        context["form_data"] = {
            "name": name,
            "email": email,
            "role": role,
            "company_name": company_name,
            "branch_name": branch_name,
        }
        context["companies"] = db.query(Company).order_by(Company.name).all()
        context["locations"] = db.query(Location).order_by(Location.name).all()
        return templates.TemplateResponse(request, "signup.html", context, status_code=422)

    # 1. Get or create Company
    company = db.query(Company).filter(Company.name.ilike(company_clean)).first()
    if not company:
        base_code = "".join([c for c in company_clean if c.isalnum()]).upper()[:6] or "COMP"
        code = base_code
        counter = 1
        while db.query(Company).filter(Company.code == code).first():
            code = f"{base_code[:4]}{counter}"
            counter += 1
        company = Company(name=company_clean, code=code)
        db.add(company)
        db.flush()

    # 2. Get or create Branch Location for this company
    home_location_id = None
    if branch_clean:
        loc = (
            db.query(Location)
            .filter(Location.name.ilike(branch_clean), Location.company_id == company.id)
            .first()
        )
        if not loc:
            loc = Location(name=branch_clean, type=LocationType.BRANCH, company_id=company.id)
            db.add(loc)
            db.flush()
        home_location_id = loc.id

    # 3. Create AppUser
    hashed_pwd = hash_password(password_clean)
    user = AppUser(
        name=name_clean,
        email=email_clean,
        password_hash=hashed_pwd,
        role=UserRole(role),
        company_id=company.id,
        home_location_id=home_location_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    response = RedirectResponse(url=success_redirect("/", f"Account created! Welcome, {user.name}."), status_code=303)
    create_session(db, user.id, response=response)
    return response


@router.get("/logout")
@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    response = RedirectResponse(url="/login?success=Logged+out+successfully", status_code=303)
    delete_session(db, request, response=response)
    return response

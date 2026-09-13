from urllib.parse import quote_plus
from fastapi import Request
from sqlalchemy.orm import Session

from app.auth import get_user_from_session
from app.models import AppUser, Company, Location, UserRole


def get_acting_user(
    db: Session,
    request: Request | None = None,
    acting_as_id: int | None = None,
) -> AppUser | None:
    # 1. Check active cookie session
    if request is not None:
        session_user = get_user_from_session(db, request)
        if session_user is not None:
            return session_user

    # 2. Check explicitly supplied query param / arg (for simulation mode)
    user_id = acting_as_id
    if user_id is None and request is not None:
        val = request.query_params.get("acting_as_id")
        if val and val.isdigit():
            user_id = int(val)
    if user_id is not None:
        user = db.get(AppUser, user_id)
        if user is not None:
            return user

    # Default fallback to first AppUser
    return db.query(AppUser).order_by(AppUser.id).first()


def scoped_location_ids(
    db: Session,
    acting_as_user: AppUser | None,
) -> list[int] | None:
    """Returns list of allowed location IDs for acting_as_user based on their company and role.
    If the user has a company_id, access is strictly scoped to that company's locations.
    If the user has no company_id (unassigned legacy admin), returns None.
    """
    if acting_as_user is None:
        return None

    # 1. If BRANCH_STAFF with a specific home location, return only that branch
    if acting_as_user.role == UserRole.BRANCH_STAFF and acting_as_user.home_location_id:
        return [acting_as_user.home_location_id]

    # 2. If user belongs to a company, scope access strictly to locations of that company
    if acting_as_user.company_id:
        locs = (
            db.query(Location.id)
            .filter(Location.company_id == acting_as_user.company_id)
            .all()
        )
        return [loc_id for (loc_id,) in locs]

    # 3. Unassigned legacy fallback
    return None


def header_context(
    db: Session,
    request: Request | None = None,
    acting_as_id: int | None = None,
):
    acting_user = get_acting_user(db, request, acting_as_id)
    company = None
    locations_query = db.query(Location)
    users_query = db.query(AppUser)

    if acting_user and acting_user.company_id:
        company = db.get(Company, acting_user.company_id)
        locations_query = locations_query.filter(Location.company_id == acting_user.company_id)
        users_query = users_query.filter(AppUser.company_id == acting_user.company_id)

    return {
        "locations": locations_query.order_by(Location.id).all(),
        "app_users": users_query.order_by(AppUser.id).all(),
        "companies": db.query(Company).order_by(Company.id).all(),
        "user_roles": [
            (UserRole.BRANCH_STAFF, "Branch Staff"),
            (UserRole.CENTRAL_PURCHASING, "Central Purchasing"),
            (UserRole.RECEIVING_STAFF, "Receiving Staff"),
            (UserRole.COMPANY_ADMIN, "Company Admin"),
        ],
        "acting_user": acting_user,
        "company": company,
    }


def success_redirect(path: str, message: str):
    separator = "&" if "?" in path else "?"
    return f"{path}{separator}success={quote_plus(message)}"

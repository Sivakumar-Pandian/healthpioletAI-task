from urllib.parse import quote_plus
from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AppUser, Location, UserRole


def get_acting_user(
    db: Session,
    request: Request | None = None,
    acting_as_id: int | None = None,
) -> AppUser | None:
    user_id = acting_as_id
    if user_id is None and request is not None:
        val = request.query_params.get("acting_as_id")
        if val and val.isdigit():
            user_id = int(val)
    if user_id is not None:
        user = db.get(AppUser, user_id)
        if user is not None:
            return user
    # Default fallback to first AppUser (Anita Rao)
    return db.query(AppUser).order_by(AppUser.id).first()


def scoped_location_ids(
    db: Session,
    acting_as_user: AppUser | None,
) -> list[int] | None:
    """Returns None for unrestricted access (CENTRAL_PURCHASING / RECEIVING_STAFF),
    or [user.home_location_id] for BRANCH_STAFF.
    """
    if acting_as_user is None:
        return None
    if acting_as_user.role in (UserRole.CENTRAL_PURCHASING, UserRole.RECEIVING_STAFF):
        return None
    if acting_as_user.role == UserRole.BRANCH_STAFF and acting_as_user.home_location_id:
        return [acting_as_user.home_location_id]
    return None


def header_context(
    db: Session,
    request: Request | None = None,
    acting_as_id: int | None = None,
):
    acting_user = get_acting_user(db, request, acting_as_id)
    return {
        "locations": db.query(Location).order_by(Location.id).all(),
        "app_users": db.query(AppUser).order_by(AppUser.id).all(),
        "user_roles": [
            (UserRole.BRANCH_STAFF, "Branch Staff"),
            (UserRole.CENTRAL_PURCHASING, "Central Purchasing"),
            (UserRole.RECEIVING_STAFF, "Receiving Staff"),
        ],
        "acting_user": acting_user,
    }


def success_redirect(path: str, message: str):
    separator = "&" if "?" in path else "?"
    return f"{path}{separator}success={quote_plus(message)}"

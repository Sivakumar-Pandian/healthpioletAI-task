from urllib.parse import quote_plus
from fastapi import Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import get_user_from_session
from app.models import AppUser, Company, Location, Notification, UserRole


def create_notification(
    db: Session,
    title: str,
    message: str,
    link: str | None = None,
    user_id: int | None = None,
    target_role: UserRole | None = None,
    target_location_id: int | None = None,
    company_id: int | None = None,
    icon_type: str = "bell",
):
    notification = Notification(
        company_id=company_id,
        user_id=user_id,
        target_role=target_role,
        target_location_id=target_location_id,
        title=title,
        message=message,
        link=link,
        icon_type=icon_type,
        is_read=False,
    )
    db.add(notification)
    db.commit()
    return notification


def get_user_notifications(db: Session, acting_user: AppUser | None, limit: int = 10):
    if not acting_user:
        return []

    user_match = Notification.user_id == acting_user.id

    if acting_user.home_location_id:
        loc_cond = or_(
            Notification.target_location_id == acting_user.home_location_id,
            Notification.target_location_id.is_(None),
        )
    else:
        loc_cond = Notification.target_location_id.is_(None)

    if acting_user.role:
        role_cond = or_(
            Notification.target_role == acting_user.role,
            Notification.target_role.is_(None),
        )
    else:
        role_cond = Notification.target_role.is_(None)

    broadcast = (
        Notification.user_id.is_(None)
        & loc_cond
        & role_cond
        & ~((Notification.target_location_id.is_(None)) & (Notification.target_role.is_(None)))
    )

    query = db.query(Notification).filter(or_(user_match, broadcast))

    if acting_user.company_id:
        query = query.filter(
            or_(Notification.company_id == acting_user.company_id, Notification.company_id.is_(None))
        )

    return query.order_by(Notification.created_at.desc()).limit(limit).all()


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

    notifications = get_user_notifications(db, acting_user, limit=15)
    unread_count = sum(1 for n in notifications if not n.is_read)

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
        "notifications": notifications,
        "unread_notification_count": unread_count,
    }


def success_redirect(path: str, message: str):
    separator = "&" if "?" in path else "?"
    return f"{path}{separator}success={quote_plus(message)}"


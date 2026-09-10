from sqlalchemy.orm import Session

from app.models import AppUser, Location, UserRole


def header_context(db: Session):
    return {
        "locations": db.query(Location).order_by(Location.id).all(),
        "app_users": db.query(AppUser).order_by(AppUser.id).all(),
        "user_roles": [
            (UserRole.BRANCH_STAFF, "Branch Staff"),
            (UserRole.CENTRAL_PURCHASING, "Central Purchasing"),
            (UserRole.RECEIVING_STAFF, "Receiving Staff"),
        ],
    }

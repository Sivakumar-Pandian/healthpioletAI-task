from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.context import get_acting_user, get_user_notifications
from app.database import get_db
from app.models import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.api_route("/{notification_id}/read", methods=["GET", "POST"])
def mark_notification_read(
    notification_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    acting_user = get_acting_user(db, request)
    notification = db.get(Notification, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    notification.is_read = True
    db.commit()

    # If request wants JSON
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"status": "success"})

    redirect_url = notification.link or request.headers.get("referer") or "/"
    return RedirectResponse(url=redirect_url, status_code=303)



@router.post("/read-all")
def mark_all_notifications_read(
    request: Request,
    db: Session = Depends(get_db),
):
    acting_user = get_acting_user(db, request)
    if acting_user:
        notifications = get_user_notifications(db, acting_user, limit=50)
        for n in notifications:
            n.is_read = True
        db.commit()

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"status": "success"})

    redirect_url = request.headers.get("referer") or "/"
    return RedirectResponse(url=redirect_url, status_code=303)


@router.get("/api")
def get_notifications_api(
    request: Request,
    db: Session = Depends(get_db),
):
    acting_user = get_acting_user(db, request)
    if not acting_user:
        return JSONResponse({"unread_count": 0, "notifications": []})

    notifications = get_user_notifications(db, acting_user, limit=15)
    unread_count = sum(1 for n in notifications if not n.is_read)

    data = []
    for n in notifications:
        data.append(
            {
                "id": n.id,
                "title": n.title,
                "message": n.message,
                "link": n.link,
                "icon_type": n.icon_type,
                "is_read": n.is_read,
                "created_at": n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else "",
            }
        )

    return JSONResponse(
        {
            "unread_count": unread_count,
            "notifications": data,
        }
    )

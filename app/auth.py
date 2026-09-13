import datetime
import uuid
from fastapi import Request, Response
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.models import AppUser, UserSession

# Use pbkdf2_sha256 for standard, reliable, zero-compatibility-issue password hashing
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
SESSION_COOKIE_NAME = "session_token"
SESSION_DURATION_HOURS = 24 * 7  # 7 days


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    return pwd_context.verify(plain_password, hashed_password)


def create_session(db: Session, user_id: int, response: Response | None = None) -> str:
    token = str(uuid.uuid4())
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=SESSION_DURATION_HOURS)
    session = UserSession(
        session_token=token,
        user_id=user_id,
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()

    if response is not None:
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            httponly=True,
            max_age=SESSION_DURATION_HOURS * 3600,
            samesite="lax",
        )
    return token


def get_user_from_session(db: Session, request: Request) -> AppUser | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None

    session = (
        db.query(UserSession)
        .filter(
            UserSession.session_token == token,
            UserSession.expires_at > datetime.datetime.utcnow(),
        )
        .first()
    )
    if session and session.user:
        return session.user
    return None


def delete_session(db: Session, request: Request, response: Response | None = None):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        db.query(UserSession).filter(UserSession.session_token == token).delete()
        db.commit()
    if response is not None:
        response.delete_cookie(key=SESSION_COOKIE_NAME)

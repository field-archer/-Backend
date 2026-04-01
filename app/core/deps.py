from typing import Optional

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import decode_token_sub
from app.database import get_db
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if not creds or creds.scheme.lower() != "bearer":
        raise ApiError(40100, "未授权或令牌无效", http_status=401)
    try:
        user_id = decode_token_sub(creds.credentials)
    except ValueError:
        raise ApiError(40100, "未授权或令牌无效", http_status=401) from None
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(40100, "未授权或令牌无效", http_status=401)
    return user

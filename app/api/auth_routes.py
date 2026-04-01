from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.config import config
from app.core.deps import get_current_user
from app.core.errors import ApiError
from app.core.security import create_access_token, hash_password, verify_password
from app.database import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginBody,
    LoginResponseData,
    RegisterBody,
    RegisterResponseData,
    UserPublic,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
def register(body: RegisterBody, db: Session = Depends(get_db)) -> dict:
    existing = db.scalars(
        select(User).where(User.username == body.username)
    ).first()
    if existing is not None:
        raise ApiError(40000, "用户名已存在")
    user = User(username=body.username, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    data = RegisterResponseData(
        user=UserPublic(id=user.id, username=user.username)
    )
    return {"code": 20000, "message": "成功", "data": data.model_dump()}


@router.post("/login")
def login(body: LoginBody, db: Session = Depends(get_db)) -> dict:
    user = db.scalars(select(User).where(User.username == body.username)).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise ApiError(40100, "用户名或密码错误", http_status=401)
    token = create_access_token(user.id)
    data = LoginResponseData(
        access_token=token,
        expires_in=config.JWT_EXPIRE_SECONDS,
        user=UserPublic(id=user.id, username=user.username),
    )
    return {"code": 20000, "message": "成功", "data": data.model_dump()}


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {
        "code": 20000,
        "message": "成功",
        "data": UserPublic(id=user.id, username=user.username).model_dump(),
    }

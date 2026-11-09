
import os
from datetime import datetime, timedelta, timezone

import jwt

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
)
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from pydantic import BaseModel, Field
from pwdlib import PasswordHash


AUTH_ENABLED = (
    os.getenv("AUTH_ENABLED", "false").lower() == "true"
)

JWT_SECRET = os.getenv("JWT_SECRET_DEV", "")
JWT_ALGORITHM = "HS256"
TOKEN_MINUTES = 60

password_hasher = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)

router = APIRouter(
    prefix="/api/auth",
    tags=["Autenticacao"],
)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1)


def check_auth_configuration():
    if AUTH_ENABLED and len(JWT_SECRET) < 32:
        raise RuntimeError(
            "JWT_SECRET_DEV deve ter pelo menos "
            "32 caracteres."
        )


check_auth_configuration()


async def user_from_token(pool, token: str):
    if not AUTH_ENABLED:
        return {
            "username": "legacy",
            "role": "admin",
        }

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            issuer="smart-factory-dev",
            options={
                "require": ["sub", "exp", "iss"]
            },
        )

        username = payload["sub"]

        if not isinstance(username, str):
            raise ValueError("Usuario invalido")

    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise HTTPException(
            status_code=401,
            detail="Sessao invalida ou expirada",
        )

    async with pool.acquire() as connection:
        user = await connection.fetchrow(
            """
            SELECT username, role, active
            FROM app_users
            WHERE username = $1
            """,
            username,
        )

    if user is None or not user["active"]:
        raise HTTPException(
            status_code=401,
            detail="Usuario nao autorizado",
        )

    return {
        "username": user["username"],
        "role": user["role"],
    }


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = (
        Depends(bearer)
    ),
):
    if not AUTH_ENABLED:
        return {
            "username": "legacy",
            "role": "admin",
        }

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Login necessario",
        )

    return await user_from_token(
        request.app.state.db_pool,
        credentials.credentials,
    )


def require_roles(*allowed_roles):
    async def verify_role(
        user=Depends(get_current_user),
    ):
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail="Permissao insuficiente",
            )

        return user

    return verify_role


@router.post("/login")
async def login(data: LoginRequest, request: Request):
    if not AUTH_ENABLED:
        raise HTTPException(
            status_code=404,
            detail="Autenticacao nao habilitada",
        )

    async with request.app.state.db_pool.acquire() as conn:
        user = await conn.fetchrow(
            """
            SELECT username, password_hash, role, active
            FROM app_users
            WHERE username = $1
            """,
            data.username,
        )

    if (
        user is None
        or not user["active"]
        or not password_hasher.verify(
            data.password,
            user["password_hash"],
        )
    ):
        raise HTTPException(
            status_code=401,
            detail="Usuario ou senha incorretos",
        )

    now = datetime.now(timezone.utc)

    token = jwt.encode(
        {
            "sub": user["username"],
            "iss": "smart-factory-dev",
            "iat": now,
            "exp": now + timedelta(
                minutes=TOKEN_MINUTES
            ),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user["role"],
        "username": user["username"],
    }


@router.get("/me")
async def my_profile(
    user=Depends(get_current_user),
):
    return user


async def authorize_websocket(websocket: WebSocket):
    if not AUTH_ENABLED:
        return True

    token = websocket.query_params.get("token")

    if not token:
        await websocket.close(code=1008)
        return False

    try:
        await user_from_token(
            websocket.app.state.db_pool,
            token,
        )
        return True
    except HTTPException:
        await websocket.close(code=1008)
        return False

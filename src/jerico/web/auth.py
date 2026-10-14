from typing import Annotated

from fastapi import Header, HTTPException

from jerico.crm import repo
from jerico.crm.model import Role, User
from jerico.web.context import get_web_context


async def get_current_web_user(
    x_user_id: Annotated[str | None, Header(alias="X-User-ID")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="missing_user_id")
    try:
        user_id = int(x_user_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid_user_id") from None

    ctx = get_web_context()
    with ctx.db.read() as conn:
        user = repo.get_user(conn, user_id)

    if user is None:
        raise HTTPException(status_code=401, detail="user_not_found")
    if not user.active:
        raise HTTPException(status_code=403, detail="user_deactivated")
    if user.role not in (Role.CTO, Role.COMMERCIAL, Role.LAWYER):
        raise HTTPException(status_code=403, detail="role_not_allowed")
    return user

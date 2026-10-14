from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse
from loguru import logger
from pydantic import BaseModel, Field

from jerico.crm import gate, leads, repo
from jerico.crm.assistant import SYSTEM_PROMPTS, lead_context, pipeline_context
from jerico.crm.model import (
    AuditAction,
    AuditOutcome,
    Proposal,
    ProposalStatus,
    User,
)
from jerico.crm.pseudonym import Redactor
from jerico.crm.timeutil import local_date, to_iso
from jerico.web.auth import get_current_web_user
from jerico.web.context import get_web_context

web_router = APIRouter(tags=["pwa-web"])


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=5000)
    lead_id: int | None = None


class ChatResponse(BaseModel):
    answer: str
    input_tokens: int
    output_tokens: int


@web_router.get("/manifest.json")
async def get_manifest() -> JSONResponse:
    manifest_data = {
        "name": "Jericó AI-OS",
        "short_name": "Jericó",
        "description": "Asistente comercial y operativo autónomo de Kaisen AI",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f172a",
        "theme_color": "#2563eb",
        "icons": [
            {
                "src": "/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
            }
        ],
    }
    return JSONResponse(content=manifest_data, media_type="application/manifest+json")


@web_router.get("/sw.js")
async def get_service_worker() -> Response:
    sw_code = """
const CACHE_NAME = 'jerico-pwa-v1';
const ASSETS = ['/', '/manifest.json'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)));
});

self.addEventListener('fetch', (e) => {
  e.respondWith(
    caches.match(e.request).then((res) => res || fetch(e.request))
  );
});
"""
    return Response(content=sw_code.strip(), media_type="application/javascript")


@web_router.get("/", response_class=HTMLResponse)
async def get_pwa_shell() -> str:
    return """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="manifest" href="/manifest.json">
  <title>Jericó PWA — Kaisen AI</title>
  <style>
    body { font-family: -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; }
    header { background: #1e293b; padding: 1rem; border-bottom: 1px solid #334155; }
    nav { display: flex; gap: 1rem; margin-top: 0.5rem; }
    nav a { color: #38bdf8; text-decoration: none; font-weight: 500; }
    main { padding: 1.5rem; max-width: 800px; margin: 0 auto; }
  </style>
</head>
<body>
  <header>
    <h1>Jericó PWA</h1>
    <nav>
      <a href="#chat">Chat</a>
      <a href="#leads">Leads</a>
      <a href="#approvals">Aprobaciones</a>
      <a href="#consumption">Consumo</a>
    </nav>
  </header>
  <main>
    <p>Consola comercial y operativa de Kaisen AI lista para operar.</p>
  </main>
  <script>
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js');
    }
  </script>
</body>
</html>"""


@web_router.post("/api/v1/web/chat", response_model=ChatResponse)
async def web_chat(
    req: ChatRequest,
    user: Annotated[User, Depends(get_current_web_user)],
) -> ChatResponse:
    ctx = get_web_context()
    now = ctx.clock()

    with ctx.db.tx() as tx:
        decision = ctx.budget.check(tx, user.id, now)
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail=decision.reason or "daily_cap",
            )

        lead = None
        if req.lead_id is not None:
            lead = repo.get_lead(tx, req.lead_id)
            if lead is None:
                raise HTTPException(status_code=404, detail="lead_not_found")
            red = Redactor.for_lead(lead)
            context = lead_context(
                tx, lead, red, now, include_notes=ctx.settings.assistant_include_notes
            )
        else:
            red = Redactor(values=(), parts=())
            context = pipeline_context(tx, user, now)

    scrubbed_prompt = red.scrub(req.prompt.strip())
    session_id = f"crm:user:{user.id}:web_chat"
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)

    memory_ready = False
    if ctx.memory is not None:
        try:
            ctx.memory.get_or_create_session(
                session_id=session_id,
                user_id=user.id,
                role=role_str,
                system_prompt=SYSTEM_PROMPTS["pregunta"],
                model=ctx.settings.openai_model,
            )
            memory_ready = True
        except Exception:
            memory_ready = False

    if ctx.client is None:
        raise HTTPException(status_code=503, detail="llm_unavailable")

    user_text = f"{context}\n\nPregunta: {scrubbed_prompt}"
    result = await ctx.client.complete(
        system=SYSTEM_PROMPTS["pregunta"],
        user=user_text,
        max_output_tokens=ctx.settings.assistant_max_output_tokens,
    )

    with ctx.db.tx() as tx:
        ctx.budget.record(tx, user.id, now, result)
        repo.audit(
            tx,
            actor=f"user:{user.id}",
            action=AuditAction.LLM_CALL,
            outcome=AuditOutcome.OK,
            at=now,
            lead_id=req.lead_id,
        )

    if memory_ready and ctx.memory is not None:
        try:
            ctx.memory.record_turn(
                session_id=session_id,
                user_id=user.id,
                role=role_str,
                user_prompt=user_text,
                assistant_response=result.text,
                model=ctx.settings.openai_model,
                prompt_tokens=result.input_tokens,
                completion_tokens=result.output_tokens,
            )
        except Exception as exc:
            logger.debug(f"assistant memory record_turn failed: {exc}")

    restored_text = red.restore(result.text)
    return ChatResponse(
        answer=restored_text,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )


@web_router.get("/api/v1/web/leads")
async def web_leads(
    user: Annotated[User, Depends(get_current_web_user)],
) -> dict[str, list[dict[str, Any]]]:
    ctx = get_web_context()
    with ctx.db.read() as conn:
        visible = leads.visible_leads(conn, user)
        res = [
            {
                "id": lead_item.id,
                "name": lead_item.name,
                "company": lead_item.company,
                "email": lead_item.email,
                "phone_e164": lead_item.phone_e164,
                "phone": lead_item.phone_e164,
                "state": (
                    lead_item.state.value
                    if hasattr(lead_item.state, "value")
                    else str(lead_item.state)
                ),
                "assigned_user_id": lead_item.assigned_user_id,
                "assigned_to": lead_item.assigned_user_id,
            }
            for lead_item in visible
        ]
    return {"leads": res}


@web_router.get("/api/v1/web/approvals")
async def web_approvals(
    user: Annotated[User, Depends(get_current_web_user)],
) -> dict[str, list[dict[str, Any]]]:
    ctx = get_web_context()
    now = ctx.clock()
    with ctx.db.read() as conn:
        rows = conn.execute(
            """SELECT * FROM crm_proposals
            WHERE status = 'pending' AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY expires_at, id""",
            (to_iso(now),),
        ).fetchall()
        pending = [Proposal(**dict(r)) for r in rows]
        allowed = [p for p in pending if gate.may_decide(user, p)]
        res = [
            {
                "id": p.id,
                "lead_id": p.lead_id,
                "kind": p.kind,
                "step": p.step,
                "expires_at": p.expires_at,
            }
            for p in allowed
        ]
    return {"approvals": res}


@web_router.post("/api/v1/web/approvals/{proposal_id}/approve")
async def web_approve_proposal(
    proposal_id: int,
    user: Annotated[User, Depends(get_current_web_user)],
) -> dict[str, Any]:
    ctx = get_web_context()
    now = ctx.clock()
    with ctx.db.tx() as tx:
        proposal = repo.get_proposal(tx, proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="proposal_not_found")
        if not gate.may_decide(user, proposal):
            raise HTTPException(status_code=403, detail="forbidden")
        repo.update_proposal(
            tx,
            proposal_id,
            status=ProposalStatus.APPROVED,
            resolved_at=now,
            resolved_by=user.id,
        )
        repo.audit(
            tx,
            actor=f"user:{user.id}",
            action=AuditAction.LEAD_UPDATED,
            outcome=AuditOutcome.OK,
            at=now,
            lead_id=proposal.lead_id,
        )
    return {"status": "approved", "proposal_id": proposal_id}


@web_router.post("/api/v1/web/approvals/{proposal_id}/reject")
async def web_reject_proposal(
    proposal_id: int,
    user: Annotated[User, Depends(get_current_web_user)],
) -> dict[str, Any]:
    ctx = get_web_context()
    now = ctx.clock()
    with ctx.db.tx() as tx:
        proposal = repo.get_proposal(tx, proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="proposal_not_found")
        if not gate.may_decide(user, proposal):
            raise HTTPException(status_code=403, detail="forbidden")
        repo.update_proposal(
            tx,
            proposal_id,
            status=ProposalStatus.CANCELLED,
            resolved_at=now,
            resolved_by=user.id,
        )
        repo.audit(
            tx,
            actor=f"user:{user.id}",
            action=AuditAction.LEAD_UPDATED,
            outcome=AuditOutcome.OK,
            at=now,
            lead_id=proposal.lead_id,
        )
    return {"status": "rejected", "proposal_id": proposal_id}


@web_router.get("/api/v1/web/consumption")
async def web_consumption(
    user: Annotated[User, Depends(get_current_web_user)],
) -> dict[str, Any]:
    ctx = get_web_context()
    now = ctx.clock()
    day = local_date(now).isoformat()
    with ctx.db.read() as conn:
        tokens_val = repo.get_meta(conn, f"llm:tokens:{day}")
        tokens_today = int(tokens_val) if tokens_val else 0
        calls_val = repo.get_meta(conn, f"llm:calls:{day}:{user.id}")
        calls_today = int(calls_val) if calls_val else 0
    return {
        "daily_token_cap": ctx.settings.assistant_daily_token_cap,
        "tokens_used_today": tokens_today,
        "user_daily_calls": ctx.settings.assistant_user_daily_calls,
        "calls_today": calls_today,
    }

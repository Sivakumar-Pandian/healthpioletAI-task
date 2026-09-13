from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.context import header_context, scoped_location_ids
from app.database import get_db
from app.models import Requisition
from app.traceability import build_chain, build_narrative

router = APIRouter(prefix="/traceability", tags=["traceability"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
def traceability_list(request: Request, db: Session = Depends(get_db)):
    ctx = header_context(db, request)
    acting_user = ctx["acting_user"]
    loc_ids = scoped_location_ids(db, acting_user)
    query = db.query(Requisition).order_by(Requisition.id.desc())
    if loc_ids is not None:
        query = query.filter(Requisition.location_id.in_(loc_ids))
    ctx["requisitions"] = query.all()
    return templates.TemplateResponse(request, "traceability_list.html", ctx)


@router.get("/{requisition_id}", response_class=HTMLResponse)
def traceability_detail(
    requisition_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    req = db.get(Requisition, requisition_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Requisition not found")

    ctx = header_context(db, request)
    acting_user = ctx["acting_user"]
    loc_ids = scoped_location_ids(db, acting_user)
    if loc_ids is not None and req.location_id not in loc_ids:
        raise HTTPException(
            status_code=403, detail="Forbidden: You do not have access to this requisition"
        )

    chain_steps = build_chain(db, requisition_id)
    narrative = build_narrative(db, requisition_id)

    ctx.update(
        {
            "requisition": req,
            "chain_steps": chain_steps,
            "chain_compact": False,  # expanded pills on the dedicated page
            "narrative": narrative,
        }
    )
    return templates.TemplateResponse(request, "traceability_detail.html", ctx)

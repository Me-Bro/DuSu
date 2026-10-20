"""Job Interview Practice - the learner's interviews as exact lines for DuSu ("DuSu knows your data", life.EXTRA_LINES).

So "how did my last interview go?" is answered from the real numbers instead of an invented one. SCORES AND ROLE TITLES ONLY: these lines flow into
other modes' prompts, so no resume text, no job text, no answers ever appear here. The provider checks the switch for THIS learner first - an
account without the feature must see no change in any chat.
"""

from __future__ import annotations

import datetime as dt

from .. import db, life
from . import service as svc

_LABEL = {"relevance": "answering the question", "specificity": "specific examples", "structure": "structure", "language": "language", "delivery": "delivery"}


def format_lines(d: dict, today: dt.date | None = None) -> list[str]:
    """Pure: the data from service.life_data -> up to three short lines (empty when there is nothing honest to say)."""
    out: list[str] = []
    if not d or (not d.get("last") and not d.get("active")):
        return out
    last = d.get("last")
    if last:
        when = ""
        fa = last.get("finished_at")
        if isinstance(fa, dt.datetime):
            days = ((today or db._ist_now().date()) - fa.astimezone(db._IST).date()).days          # the app's day is the IST day everywhere
            when = "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"
        # a finished interview with no judged answer (the model was down) has NO score: say so, never "0/100"
        scored = (f"{last.get('overall')}/100 over {last.get('answers')} answers" if last.get("overall") is not None
                  else f"not scored ({last.get('answers')} answers, the feedback was unavailable)")
        line = (f"Job Interview Practice (mock interviews built from the learner's own resume and a job description): {d.get('finished', 1)} finished; "
                f"the last was {life._clean(last.get('title'), 60) or 'a job'} - {scored}")
        if when:
            line += f", {when}"
        if last.get("delta") is not None:
            line += f"; {last['delta']:+d} points against their previous interview for the same job"
        if last.get("weakest"):
            line += f"; weakest area: {_LABEL.get(last['weakest'], last['weakest'])}"
        if last.get("focus"):
            line += "; the improvement points DuSu gave them for next time: " + ", ".join(life._clean(x, 60) for x in last["focus"][:3])
        out.append(line + ".")
    act = d.get("active")
    if act:
        out.append(f"A Job Interview Practice is in progress: {life._clean(act.get('title'), 60) or 'a job'}, {act.get('answers', 0)} answers so far.")
    return out


async def resume_interview_lines(uid: str, email: str = "") -> list[str]:
    from .. import main as M          # lazy: main.py imports this module
    if not await M.resume_interview_enabled(email):
        return []
    return format_lines(await svc.life_data(uid))


def register() -> None:
    if resume_interview_lines not in life.EXTRA_LINES:
        life.EXTRA_LINES.append(resume_interview_lines)

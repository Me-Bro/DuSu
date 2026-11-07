"""Insights - first-run funnel counters + "Reserve my plan" (built 2026-10-30 from the product / UI audit, P1-10 and P0-2).

    models.py   ev_milestones, ev_days, plan_interest - all NEW tables (create_all adds them, nothing is altered)
    service.py  milestone() / touch_day() (idempotent, never raise), reserve_plan(), funnel() for the owner, delete_rows() for data rights
    api.py      POST /ev (a screen beacon - always a quiet 204), POST + GET /plans/interest

The owner's `GET /admin/funnel` and the `settings.insights` kill switch live in main.py with the other admin routes. What is stored, and what is not, is in service.py's docstring
and in privacy.html.
"""

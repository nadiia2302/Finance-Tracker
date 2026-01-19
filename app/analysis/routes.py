from datetime import datetime
import os

from flask import render_template, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func

import cohere

from ..extensions import db
from ..models import Income, Expense
from . import analysis_bp


# =========================
# Cohere client (.env)
# =========================
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
if not COHERE_API_KEY:
    raise RuntimeError("COHERE_API_KEY is missing. Check your .env")

COHERE_MODEL = os.getenv("COHERE_MODEL", "command-r-08-2024")
co = cohere.Client(COHERE_API_KEY)


def _parse_date(s: str | None):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


@analysis_bp.route("/", methods=["GET"])
@login_required
def index():
    start_str = request.args.get("start")
    end_str = request.args.get("end")
    start_dt = _parse_date(start_str)
    end_dt = _parse_date(end_str)

    # ===== Income total =====
    iq = (
        db.session.query(func.coalesce(func.sum(Income.amount), 0.0))
        .filter(Income.user_id == current_user.id)
    )
    if start_dt:
        iq = iq.filter(Income.date >= start_dt)
    if end_dt:
        iq = iq.filter(Income.date <= end_dt)
    total_income = float(iq.scalar() or 0.0)

    # ===== Expense total =====
    eq = (
        db.session.query(func.coalesce(func.sum(func.abs(Expense.amount)), 0.0))
        .filter(Expense.user_id == current_user.id)
    )
    if start_dt:
        eq = eq.filter(Expense.date >= start_dt)
    if end_dt:
        eq = eq.filter(Expense.date <= end_dt)
    total_expense_abs = float(eq.scalar() or 0.0)

    net_total = total_income - total_expense_abs
    net_total_abs = abs(net_total)

    # ===== Net by day =====
    inc_by_day = (
        db.session.query(
            Income.date.label("d"),
            func.sum(Income.amount).label("s"),
        )
        .filter(Income.user_id == current_user.id)
    )

    exp_by_day = (
        db.session.query(
            Expense.date.label("d"),
            func.sum(func.abs(Expense.amount)).label("s"),
        )
        .filter(Expense.user_id == current_user.id)
    )

    if start_dt:
        inc_by_day = inc_by_day.filter(Income.date >= start_dt)
        exp_by_day = exp_by_day.filter(Expense.date >= start_dt)
    if end_dt:
        inc_by_day = inc_by_day.filter(Income.date <= end_dt)
        exp_by_day = exp_by_day.filter(Expense.date <= end_dt)

    inc_rows = dict(inc_by_day.group_by(Income.date).all())
    exp_rows = dict(exp_by_day.group_by(Expense.date).all())

    all_days = sorted(set(inc_rows.keys()) | set(exp_rows.keys()))
    day_labels = [d.strftime("%Y-%m-%d") for d in all_days]
    day_net_signed = [
        float(inc_rows.get(d, 0) or 0) - float(exp_rows.get(d, 0) or 0)
        for d in all_days
    ]

    total_expense_signed = -total_expense_abs

    return render_template(
        "analysis/index.html",
        start_str=start_str,
        end_str=end_str,
        total_income=total_income,
        total_expense_abs=total_expense_abs,
        total_expense_signed=total_expense_signed,
        net_total=net_total,
        net_total_abs=net_total_abs,
        day_labels=day_labels,
        day_net_signed=day_net_signed,
    )


@analysis_bp.route("/ai", methods=["POST"])
@login_required
def ai():
    """
    Expects JSON: { "message": "...", "context": {...} }
    Returns JSON: { "reply": "..." }
    """
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    context = payload.get("context") or {}

    if not message:
        return jsonify({"error": "Empty message"}), 400

    # -----------------------------
    # Period from context (Analysis page filter)
    # -----------------------------
    period = (context.get("period") or {})
    start_str = period.get("start") or None
    end_str = period.get("end") or None
    start_dt = _parse_date(start_str)
    end_dt = _parse_date(end_str)

    if not start_dt and not end_dt:
        start_str = "all time"
        end_str = "all time"

    # Helper: month key in SQLite
    # If you use Postgres/MySQL, you need different month extraction.
    month_key = func.strftime("%Y-%m", Income.date)

    # -----------------------------
    # DB: Income by month (ALL income)
    # -----------------------------
    income_by_month = []
    try:
        qi = (
            db.session.query(
                month_key.label("month"),
                func.sum(Income.amount).label("total")
            )
            .filter(Income.user_id == current_user.id)
        )
        if start_dt:
            qi = qi.filter(Income.date >= start_dt)
        if end_dt:
            qi = qi.filter(Income.date <= end_dt)

        rows = (
            qi.group_by("month")
              .order_by("month")
              .all()
        )

        income_by_month = [{"month": r.month, "total": float(r.total or 0)} for r in rows]
    except Exception:
        income_by_month = []

    # -----------------------------
    # DB: Salary by month (if Income has source/category)
    # We will treat records with source/category containing 'salary' as salary.
    # -----------------------------
    salary_by_month = []
    salary_field = None
    if hasattr(Income, "source"):
        salary_field = Income.source
    elif hasattr(Income, "category"):
        salary_field = Income.category

    if salary_field is not None:
        try:
            qs = (
                db.session.query(
                    month_key.label("month"),
                    func.sum(Income.amount).label("total")
                )
                .filter(Income.user_id == current_user.id)
                .filter(func.lower(salary_field).like("%salary%"))
            )
            if start_dt:
                qs = qs.filter(Income.date >= start_dt)
            if end_dt:
                qs = qs.filter(Income.date <= end_dt)

            rows_s = (
                qs.group_by("month")
                  .order_by("month")
                  .all()
            )

            salary_by_month = [{"month": r.month, "total": float(r.total or 0)} for r in rows_s]
        except Exception:
            salary_by_month = []

    # -----------------------------
    # DB: Top expense categories (optional; works if Expense.category exists)
    # -----------------------------
    top_expenses_by_category = []
    try:
        q = (
            db.session.query(
                Expense.category.label("category"),
                func.sum(func.abs(Expense.amount)).label("total")
            )
            .filter(Expense.user_id == current_user.id)
        )
        if start_dt:
            q = q.filter(Expense.date >= start_dt)
        if end_dt:
            q = q.filter(Expense.date <= end_dt)

        rows = (
            q.group_by(Expense.category)
             .order_by(func.sum(func.abs(Expense.amount)).desc())
             .limit(6)
             .all()
        )
        top_expenses_by_category = [
            {"category": (r.category or "Uncategorized"), "total": float(r.total or 0)}
            for r in rows
        ]
    except Exception:
        top_expenses_by_category = []

    # -----------------------------
    # DB: Biggest expenses (top 5)
    # -----------------------------
    biggest_expenses = []
    qe = Expense.query.filter_by(user_id=current_user.id)
    if start_dt:
        qe = qe.filter(Expense.date >= start_dt)
    if end_dt:
        qe = qe.filter(Expense.date <= end_dt)

    for e in qe.order_by(func.abs(Expense.amount).desc()).limit(5).all():
        biggest_expenses.append({
            "date": e.date.isoformat() if getattr(e, "date", None) else None,
            "amountAbs": float(abs(e.amount)) if e.amount is not None else 0.0,
            "category": getattr(e, "category", None) or "Uncategorized",
            "note": getattr(e, "note", None) or getattr(e, "description", None) or ""
        })

    # -----------------------------
    # Prompt (strict: answer the question, no long summaries)
    # -----------------------------
    system_prompt = (
        "You are a finance assistant inside a finance tracker.\n"
        "RULES:\n"
        "1) Answer ONLY the user's question. Do not write a full report unless asked.\n"
        "2) Use ONLY the provided data blocks. Never invent numbers.\n"
        "3) If the question is about December vs January salary:\n"
        "   - Prefer 'Salary by month' if present.\n"
        "   - If salary data is missing, say you can't compute it and explain what to add.\n"
        "4) Keep the reply short: max 6 bullet points.\n"
        "Output format:\n"
        "- Answer:\n"
        "- Evidence (numbers used):\n"
        "- Missing data (if any):"
    )

    user_prompt = f"""
Analysis filter period:
start={start_str}
end={end_str}

Totals (from Analysis page):
{context.get("totals")}

Income by month (DB):
{income_by_month}

Salary by month (DB, if available):
{salary_by_month}

Top expenses by category (DB):
{top_expenses_by_category}

Biggest expenses (DB):
{biggest_expenses}

User question:
{message}
""".strip()

    try:
        resp = co.chat(
            model=COHERE_MODEL,
            message=user_prompt,
            preamble=system_prompt,
            temperature=0.2,
            max_tokens=240,
        )

        reply = (resp.text or "").strip()
        if not reply:
            reply = "I couldn't generate a reply. Try rephrasing your question."
        return jsonify({"reply": reply})

    except Exception:
        return jsonify({"error": "AI service error (Cohere). Check COHERE_MODEL/API key and server logs."}), 500

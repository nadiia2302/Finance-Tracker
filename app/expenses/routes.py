import csv
import io
import os
import re
import tempfile
from datetime import datetime, date

from flask import render_template, request, Response, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func

from mindee import ClientV2, InferenceParameters, PathInput

from ..extensions import db
from ..models import Expense
from . import expenses_bp




CATEGORIES = [
    "Food",
    "Transport",
    "Housing",
    "Bills",
    "Health",
    "Subscriptions",
    "Entertainment",
    "Shopping",
    "Education",
    "Travel",
    "Savings",
    "Debt",
    "Other",
]

def map_mindee_category(mindee_cat: str | None) -> str:
    if not mindee_cat:
        return "Other"

    m = str(mindee_cat).strip().lower()

    mapping = {
        "food": "Food",
        "restaurant": "Food",
        "groceries": "Food",

        "transport": "Transport",

        "housing": "Housing",
        "rent": "Housing",

        "bills": "Bills",
        "utilities": "Bills",

        "health": "Health",

        "subscriptions": "Subscriptions",

        "entertainment": "Entertainment",

        "shopping": "Shopping",

        "education": "Education",

        "travel": "Travel",

        "savings": "Savings",
        "debt": "Debt",
    }

    return mapping.get(m, "Other")


def parse_date_or_none(value: str | None):
    """Parse YYYY-MM-DD -> date or None."""
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_amount_from_any(value):
    """
    Extract first number from a string like:
    "12.30", "12,30", "12.30 PLN", "PLN 12,30", etc.
    """
    if value is None:
        return None
    s = str(value)
    m = re.search(r"\d+(?:[.,]\d+)?", s)
    if not m:
        return None
    return float(m.group(0).replace(",", "."))


@expenses_bp.route("/", methods=["GET"])
@login_required
def index():
    start_str = request.args.get("start")
    end_str = request.args.get("end")
    selected_category = request.args.get("category", "")

    start_dt = parse_date_or_none(start_str)
    end_dt = parse_date_or_none(end_str)

    q = Expense.query.filter_by(user_id=current_user.id)

    if start_dt:
        q = q.filter(Expense.date >= start_dt)
    if end_dt:
        q = q.filter(Expense.date <= end_dt)
    if selected_category:
        q = q.filter(Expense.category == selected_category)

    expenses = q.order_by(Expense.date.desc(), Expense.id.desc()).all()
    total = round(sum(float(e.amount) for e in expenses), 2)

    # --- charts: by category ---
    cat_q = db.session.query(Expense.category, func.sum(Expense.amount)) \
        .filter(Expense.user_id == current_user.id)

    if start_dt:
        cat_q = cat_q.filter(Expense.date >= start_dt)
    if end_dt:
        cat_q = cat_q.filter(Expense.date <= end_dt)
    if selected_category:
        cat_q = cat_q.filter(Expense.category == selected_category)

    cat_rows = cat_q.group_by(Expense.category).all()
    cat_labels = [c for c, _ in cat_rows]
    cat_values = [round(float(s or 0), 2) for _, s in cat_rows]

    # --- charts: spending over time (by day) ---
    day_q = db.session.query(Expense.date, func.sum(Expense.amount)) \
        .filter(Expense.user_id == current_user.id)

    if start_dt:
        day_q = day_q.filter(Expense.date >= start_dt)
    if end_dt:
        day_q = day_q.filter(Expense.date <= end_dt)
    if selected_category:
        day_q = day_q.filter(Expense.category == selected_category)

    day_rows = day_q.group_by(Expense.date).order_by(Expense.date).all()
    day_labels = [d.strftime("%Y-%m-%d") for d, _ in day_rows]
    day_values = [round(float(s or 0), 2) for _, s in day_rows]

    return render_template(
        "expenses/index.html",
        expenses=expenses,
        total=total,
        start_str=start_str,
        end_str=end_str,
        selected_category=selected_category,
        categories=CATEGORIES,
        today=date.today().strftime("%Y-%m-%d"),
        cat_labels=cat_labels,
        cat_values=cat_values,
        day_labels=day_labels,
        day_values=day_values,
    )


@expenses_bp.route("/add", methods=["POST"])
@login_required
def add():
    description = (request.form.get("description") or "").strip()
    amount_raw = (request.form.get("amount") or "").strip()
    category = (request.form.get("category") or "").strip()
    date_raw = (request.form.get("date") or "").strip()

    if not description or not amount_raw or not category:
        flash("Please fill description, amount and category", "error")
        return redirect(url_for("expenses.index"))

    try:
        amount = float(amount_raw)
        if amount <= 0:
            raise ValueError
    except ValueError:
        flash("Amount must be a positive number", "error")
        return redirect(url_for("expenses.index"))

    d = parse_date_or_none(date_raw) or date.today()

    exp = Expense(
        user_id=current_user.id,
        description=description,
        category=category,
        amount=amount,
        date=d,
    )
    db.session.add(exp)
    db.session.commit()

    flash("Expense added", "success")
    return redirect(url_for("expenses.index"))


@expenses_bp.route("/export_csv", methods=["GET"])
@login_required
def export_csv():
    start = request.args.get("start")
    end = request.args.get("end")
    category = request.args.get("category")

    start_dt = parse_date_or_none(start)
    end_dt = parse_date_or_none(end)

    q = Expense.query.filter_by(user_id=current_user.id)

    if start_dt:
        q = q.filter(Expense.date >= start_dt)
    if end_dt:
        q = q.filter(Expense.date <= end_dt)
    if category:
        q = q.filter(Expense.category == category)

    rows = q.order_by(Expense.date.desc(), Expense.id.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "description", "category", "amount"])

    for e in rows:
        writer.writerow([
            e.date.strftime("%Y-%m-%d"),
            e.description,
            e.category,
            f"{float(e.amount):.2f}"
        ])

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=expenses.csv"},
    )


@expenses_bp.route("/upload_receipt", methods=["POST"])
@login_required
def upload_receipt():
    # перечитываем env при каждом запросе (на случай, если меняла .env)
    api_key = os.getenv("MINDEE_API_KEY")
    model_uuid = os.getenv("MINDEE_MODEL_UUID")


    file = request.files.get("receipt")
    if not file or file.filename == "":
        flash("No file selected", "error")
        return redirect(url_for("expenses.index"))

    if not api_key or not model_uuid:
        flash("Mindee API key or model UUID missing", "error")
        return redirect(url_for("expenses.index"))

    tmp_path = None
    try:
        suffix = os.path.splitext(file.filename)[1] or ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            tmp.write(file.read())

        client = ClientV2(api_key=api_key)
        params = InferenceParameters(model_id=model_uuid)

        response = client.enqueue_and_get_inference(PathInput(tmp_path), params)

        fields = response.inference.result.fields

        def get_value(field_key: str):
            f = fields.get(field_key)
            return getattr(f, "value", None) if f is not None else None

        amount = get_value("total_amount")
        date_str = get_value("date")
        merchant = get_value("supplier_name") or "Receipt"
        mindee_cat = get_value("purchase_category")      # например: "shopping"
        mindee_sub = get_value("purchase_subcategory") 

        if amount is None or date_str is None:
            flash("Mindee parsed response but can't extract total/date", "error")
            return redirect(url_for("expenses.index"))

        amount = float(amount)

        try:
            d = datetime.strptime(str(date_str), "%Y-%m-%d").date()
        except Exception:
            d = date.today()

        exp = Expense(
            user_id=current_user.id,
            description=f"{merchant} ({mindee_sub})" if mindee_sub else f"{merchant} (receipt)",
            category=map_mindee_category(mindee_cat),
            amount=amount,
            date=d,
        )
        db.session.add(exp)
        db.session.commit()

        flash(f"Added expense from receipt: {amount:.2f}", "success")
        return redirect(url_for("expenses.index"))

    except Exception as e:
        flash(f"Mindee request failed: {e}", "error")
        return redirect(url_for("expenses.index"))

    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


@expenses_bp.route("/<int:expense_id>/edit", methods=["GET", "POST"])
@login_required
def edit(expense_id: int):
    exp = Expense.query.filter_by(id=expense_id, user_id=current_user.id).first_or_404()

    if request.method == "GET":
        return render_template("expenses/edit.html", expense=exp, categories=CATEGORIES)

    description = (request.form.get("description") or "").strip()
    amount_raw = (request.form.get("amount") or "").strip()
    category = (request.form.get("category") or "").strip()
    date_raw = (request.form.get("date") or "").strip()

    if not description or not amount_raw or not category:
        flash("Please fill all fields", "error")
        return redirect(url_for("expenses.edit", expense_id=expense_id))

    try:
        amount = float(amount_raw)
        if amount <= 0:
            raise ValueError
    except ValueError:
        flash("Amount must be a positive number", "error")
        return redirect(url_for("expenses.edit", expense_id=expense_id))

    d = parse_date_or_none(date_raw) or exp.date

    exp.description = description
    exp.amount = amount
    exp.category = category
    exp.date = d

    db.session.commit()
    flash("Expense updated", "success")
    return redirect(url_for("expenses.index"))


@expenses_bp.route("/<int:expense_id>/delete", methods=["POST"])
@login_required
def delete(expense_id: int):
    exp = Expense.query.filter_by(id=expense_id, user_id=current_user.id).first_or_404()
    db.session.delete(exp)
    db.session.commit()
    flash("Expense deleted", "success")
    return redirect(url_for("expenses.index"))

from datetime import date, datetime

from flask import render_template, request, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from sqlalchemy import func

from . import incomes_bp
from ..extensions import db
from ..models import Income
from ..utils import parse_date_or_none

INCOME_CATEGORIES = ["Salary", "Freelance", "Gift", "Investment", "Other"]

@incomes_bp.route("/")
@login_required
def index():
    start_str = (request.args.get("start") or "").strip()
    end_str = (request.args.get("end") or "").strip()
    selected_category = (request.args.get("category") or "").strip()

    start_date = parse_date_or_none(start_str)
    end_date = parse_date_or_none(end_str)

    q = Income.query.filter(Income.user_id == current_user.id)

    if start_date:
        q = q.filter(Income.date >= start_date)
    if end_date:
        q = q.filter(Income.date <= end_date)
    if selected_category:
        q = q.filter(Income.category == selected_category)

    incomes = q.order_by(Income.date.desc(), Income.id.desc()).all()
    total = round(sum(i.amount for i in incomes), 2)

    # график по категориям
    cat_q = db.session.query(Income.category, func.sum(Income.amount))\
        .filter(Income.user_id == current_user.id)

    if start_date:
        cat_q = cat_q.filter(Income.date >= start_date)
    if end_date:
        cat_q = cat_q.filter(Income.date <= end_date)
    if selected_category:
        cat_q = cat_q.filter(Income.category == selected_category)

    cat_rows = cat_q.group_by(Income.category).all()
    cat_labels = [c for c, _ in cat_rows]
    cat_values = [round(float(s or 0), 2) for _, s in cat_rows]

    # график по дням
    day_q = db.session.query(Income.date, func.sum(Income.amount))\
        .filter(Income.user_id == current_user.id)

    if start_date:
        day_q = day_q.filter(Income.date >= start_date)
    if end_date:
        day_q = day_q.filter(Income.date <= end_date)
    if selected_category:
        day_q = day_q.filter(Income.category == selected_category)

    day_rows = day_q.group_by(Income.date).order_by(Income.date).all()
    day_labels = [d.isoformat() for d, _ in day_rows]
    day_values = [round(float(s or 0), 2) for _, s in day_rows]

    return render_template(
        "incomes/index.html",
        categories=INCOME_CATEGORIES,
        today=date.today().isoformat(),
        incomes=incomes,
        total=total,
        start_str=start_str,
        end_str=end_str,
        selected_category=selected_category,
        cat_labels=cat_labels,
        cat_values=cat_values,
        day_labels=day_labels,
        day_values=day_values,
    )

@incomes_bp.route("/add", methods=["POST"])
@login_required
def add():
    source = (request.form.get("source") or "").strip()
    amount_str = (request.form.get("amount") or "").strip()
    category = (request.form.get("category") or "").strip()
    date_str = (request.form.get("date") or "").strip()

    if not source or not amount_str or not category:
        flash("Please fill source, amount, and category", "error")
        return redirect(url_for("incomes.index"))

    try:
        amount = float(amount_str)
        if amount <= 0:
            raise ValueError
    except ValueError:
        flash("Amount must be a positive number", "error")
        return redirect(url_for("incomes.index"))

    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()
    except ValueError:
        d = date.today()

    i = Income(source=source, amount=amount, category=category, date=d, user_id=current_user.id)
    db.session.add(i)
    db.session.commit()

    flash("Income added", "success")
    return redirect(url_for("incomes.index"))


@incomes_bp.route("/delete/<int:income_id>", methods=["POST"])
@login_required
def delete(income_id):
    i = Income.query.filter_by(id=income_id, user_id=current_user.id).first_or_404()
    db.session.delete(i)
    db.session.commit()
    flash("Income deleted", "success")
    return redirect(url_for("incomes.index"))
@incomes_bp.route("/edit/<int:income_id>", methods=["GET"])
@login_required
def edit(income_id):
    income = Income.query.filter_by(
        id=income_id,
        user_id=current_user.id
    ).first_or_404()

    return render_template(
        "incomes/edit.html",
        income=income,
        categories=INCOME_CATEGORIES
    )


@incomes_bp.route("/edit/<int:income_id>", methods=["POST"])
@login_required
def edit_post(income_id):
    income = Income.query.filter_by(
        id=income_id,
        user_id=current_user.id
    ).first_or_404()

    source = (request.form.get("source") or "").strip()
    amount_str = (request.form.get("amount") or "").strip()
    category = (request.form.get("category") or "").strip()
    date_str = (request.form.get("date") or "").strip()

    if not source or not amount_str or not category:
        flash("Please fill all fields", "error")
        return redirect(url_for("incomes.edit", income_id=income_id))

    try:
        amount = float(amount_str)
        if amount <= 0:
            raise ValueError
    except ValueError:
        flash("Amount must be a positive number", "error")
        return redirect(url_for("incomes.edit", income_id=income_id))

    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else income.date
    except ValueError:
        d = income.date

    income.source = source
    income.amount = amount
    income.category = category
    income.date = d

    db.session.commit()
    flash("Income updated", "success")
    return redirect(url_for("incomes.index"))


@incomes_bp.route("/export.csv")
@login_required
def export_csv():
    start_str = (request.args.get("start") or "").strip()
    end_str = (request.args.get("end") or "").strip()
    selected_category = (request.args.get("category") or "").strip()

    start_date = parse_date_or_none(start_str)
    end_date = parse_date_or_none(end_str)

    q = Income.query.filter(Income.user_id == current_user.id)
    if start_date:
        q = q.filter(Income.date >= start_date)
    if end_date:
        q = q.filter(Income.date <= end_date)
    if selected_category:
        q = q.filter(Income.category == selected_category)

    incomes = q.order_by(Income.date, Income.id).all()

    lines = ["date,source,category,amount"]
    for i in incomes:
        lines.append(f"{i.date.isoformat()},{i.source},{i.category},{i.amount:.2f}")

    csv_data = "\n".join(lines)
    filename = "incomes.csv"

    return Response(
        csv_data,
        headers={
            "Content-Type": "text/csv",
            "Content-Disposition": f"attachment; filename={filename}",
        },
    )

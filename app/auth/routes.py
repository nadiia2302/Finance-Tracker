import re
from urllib.parse import urlparse

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_user, login_required, current_user, logout_user
from sqlalchemy.exc import IntegrityError

from . import auth_bp
from ..extensions import db
from ..models import User

def _is_safe_local_path(target: str) -> bool:
    if not target:
        return False
    parts = urlparse(target)
    return parts.scheme == "" and parts.netloc == "" and target.startswith("/")

@auth_bp.route("/")
def index():
    # Главная — можно оставить welcome страницу
    return render_template("auth/index.html")

@auth_bp.route("/dashboard")
@login_required
def dashboard():
    return render_template("auth/dashboard.html")

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    errors = []
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        if not (3 <= len(username) <= 80):
            errors.append("Username must be between 3 and 80 characters")

        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            errors.append("Please enter a valid email address")

        if len(password) < 6:
            errors.append("Password needs to be at least 6 characters")

        if password != confirm:
            errors.append("Passwords don't match")

        if not errors:
            try:
                user = User(username=username, email=email)
                user.set_password(password)
                db.session.add(user)
                db.session.commit()
                flash("Account created successfully! Please login", "success")
                return redirect(url_for("auth.login"))
            except IntegrityError:
                db.session.rollback()
                errors.append("That username or email is already registered")

    return render_template("auth/register.html", errors=errors)

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    errors = []
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        remember_flag = request.form.get("remember") == "1"

        if not email:
            errors.append("Email is required")
        if not password:
            errors.append("Password is required")

        if not errors:
            user = User.query.filter_by(email=email).first()
            if not user or not user.check_password(password):
                errors.append("Invalid email or password")
            else:
                login_user(user, remember=remember_flag)
                flash(f"Welcome back {user.username}", "success")

                next_url = request.form.get("next") or request.args.get("next") or ""
                if _is_safe_local_path(next_url):
                    return redirect(next_url)

                
                return redirect(url_for("expenses.index"))

    return render_template("auth/login.html", errors=errors)

@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out", "success")
    return redirect(url_for("auth.index"))

@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    errors = []
    if request.method == "POST":
        current_pw = request.form.get("current_password") or ""
        new_pw = request.form.get("new_password") or ""
        confirm_pw = request.form.get("confirm_password") or ""

        if not current_user.check_password(current_pw):
            errors.append("Current password is incorrect")

        if len(new_pw) < 6:
            errors.append("New password needs to be at least 6 characters")

        if new_pw != confirm_pw:
            errors.append("New passwords and confirmation do not match")

        if not errors:
            current_user.set_password(new_pw)
            db.session.commit()
            flash("Your password has been updated", "success")
            return redirect(url_for("auth.dashboard"))

    return render_template("auth/change_password.html", errors=errors)

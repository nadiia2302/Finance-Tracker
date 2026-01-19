from datetime import date
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from .extensions import db

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    expenses = db.relationship("Expense", backref="user", lazy=True, cascade="all, delete-orphan")
    incomes = db.relationship("Income", backref="user", lazy=True, cascade="all, delete-orphan")


    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

class Income(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(120), nullable=False)   # откуда доход (зарплата/фриланс)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False, default="Salary")
    date = db.Column(db.Date, nullable=False, default=date.today)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


from flask import Blueprint

incomes_bp = Blueprint("incomes", __name__, url_prefix="/incomes", template_folder="../templates/incomes")

from . import routes
import os
from dotenv import load_dotenv
from flask import Flask

from .extensions import db, login_manager
from .models import User


def create_app():
    app = Flask(__name__, instance_relative_config=True)

    
    # app.root_path = .../finance-app/app
    env_path = os.path.join(app.root_path, "..", ".env")
    load_dotenv(env_path)

    # config
    app.config["SECRET_KEY"] = "dev-secret-key"

    # Upload settings
    app.config["UPLOAD_EXTENSIONS"] = {".jpg", ".jpeg", ".png", ".webp"}
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB

    # DB
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///app.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # MINDEE
    # MINDEE (SDK + UUID)
    app.config["MINDEE_API_KEY"] = os.getenv("MINDEE_API_KEY")
    app.config["MINDEE_MODEL_UUID"] = os.getenv("MINDEE_MODEL_UUID")

    if not app.config["MINDEE_API_KEY"]:
        raise RuntimeError("MINDEE_API_KEY is not set. Check your .env file.")
    if not app.config["MINDEE_MODEL_UUID"]:
        raise RuntimeError("MINDEE_MODEL_UUID is not set. Check your .env file.")


    # init extensions
    db.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    
    from .auth.routes import auth_bp
    from .expenses import expenses_bp
    from .incomes import incomes_bp
    from .analysis import analysis_bp
    from .home import home_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(incomes_bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(home_bp)

    with app.app_context():
        db.create_all()

    return app

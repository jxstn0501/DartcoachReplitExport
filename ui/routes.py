from flask import render_template
from . import ui_bp

@ui_bp.route("/")
def index():
    return render_template("ui/index.html")

@ui_bp.route("/import")
def import_page():
    return render_template("ui/import.html")

@ui_bp.route("/dashboard")
def dashboard():
    return render_template("ui/dashboard.html")

@ui_bp.route("/training")
def training():
    return render_template("ui/training.html")

@ui_bp.route("/stats")
def stats():
    return render_template("ui/stats.html")

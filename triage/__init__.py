from flask import Blueprint

triage_bp = Blueprint('triage', __name__, url_prefix='/triage')

from . import routes

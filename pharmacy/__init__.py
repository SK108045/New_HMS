from flask import Blueprint

pharmacy_bp = Blueprint('pharmacy', __name__, url_prefix='/pharmacy')

from . import routes

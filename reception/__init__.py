from flask import Blueprint

reception_bp = Blueprint(
    'reception', 
    __name__, 
    url_prefix='/reception',
    template_folder='../templates'
)

from . import routes

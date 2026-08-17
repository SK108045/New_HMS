from flask import Blueprint

auth_bp = Blueprint(
    'auth',
    __name__,
    url_prefix='',
    template_folder='../templates'
)

from . import routes

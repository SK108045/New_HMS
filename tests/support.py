import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from config import Config
from app import create_app
from models import db, Patient, User, SecuritySetting
from datetime import date


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='hms-test-')
        path = Path(self.directory.name)
        class TestConfig(Config):
            TESTING = True
            SECRET_KEY = 'isolated-test-secret-never-used-in-production'
            SQLALCHEMY_DATABASE_URI = 'sqlite:///' + str(path / 'test.sqlite')
            PRIVATE_UPLOAD_FOLDER = str(path / 'private')
            UPLOAD_FOLDER = str(path / 'private' / 'photos')
            WTF_CSRF_ENABLED = False
            AUTO_INIT_DB = True
            SEED_DEMO_DATA = False
            DEMO_LOGIN_ENABLED = False
            ENVIRONMENT = 'testing'
        self.network = patch('socket.socket.connect', side_effect=AssertionError('Tests cannot contact external services'))
        self.network.start()
        self.app = create_app(TestConfig)
        self.context = self.app.app_context()
        self.context.push()
        settings = SecuritySetting.get_settings()
        settings.require_2fa_for_admin_doctor = False
        settings.require_2fa_for_all = False
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        self.network.stop()
        self.directory.cleanup()

    def patient(self, suffix='1'):
        p = Patient(hospital_id='TEST-' + suffix, first_name='Test', last_name='Patient', full_name='Test Patient',
                    date_of_birth=date(1990, 1, 1), gender='Other', phone='+254700000001',
                    next_of_kin_name='Kin', next_of_kin_phone='+254700000002', next_of_kin_relation='Sibling')
        db.session.add(p)
        db.session.commit()
        return p

    def user(self, role='admin', portal='all', name='tester'):
        u = User(username=name, full_name='Test Staff', role=role, portal=portal, staff_id='TEST-' + name,
                 status='active', department='Testing', force_password_change=False)
        u.set_password('Test!Password123', force_change=False)
        db.session.add(u)
        db.session.commit()
        return u

    def sign_in(self, user):
        from auth.decorators import login_user
        with self.app.test_request_context():
            login_user(user)
            db.session.commit()
            from flask import session
            values = dict(session)
        with self.client.session_transaction() as session:
            session.update(values)


def authenticate(client, app, user):
    """Establish a real session without relying on detached fixture attributes."""
    from sqlalchemy import inspect
    identity = inspect(user).identity[0]
    from auth.decorators import login_user
    from flask import session
    with app.test_request_context():
        user = db.session.get(User, identity)
        login_user(user)
        db.session.commit()
        values = dict(session)
    with client.session_transaction() as session:
        session.update(values)

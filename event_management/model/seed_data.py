import datetime

import reflex as rx
from sqlmodel import Session

from event_management.model.user import User


# engine = rx.utils.get_db_engine()
# engine = rx.utils.get_engine()


def make_users():
    with rx.session() as session:
        existing_data = session.exec(User.select()).first()
        if existing_data:
            print(f"already data, pass: {existing_data}")
            return
        else:
            test_user = User(name="Test User", email="test.user@mail.com", date_of_birth=datetime.date.today(),
                             password="blerb", username="test data user", phone_number="12345")

            session.add(test_user)
            session.commit()


def make_all():
    make_users()

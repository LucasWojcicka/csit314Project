import datetime

import reflex as rx
from sqlmodel import Field


class User(rx.Model, table=True):
    name: str
    email: str
    id: int = Field(primary_key=True)
    date_of_birth: datetime.date
    password: str
    username: str
    phone_number: str

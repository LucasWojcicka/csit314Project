import reflex as rx

from model.event import Event
from model.user import User

from typing import List


class Attendee(rx.Model, table=True):
    user: User
    events_attending: List[Event]


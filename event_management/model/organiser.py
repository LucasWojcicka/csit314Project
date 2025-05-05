import reflex as rx

from event_management.model.event import Event
from event_management.model.user import User
from typing import List


class Organiser(rx.Model, table=True):
    events: List[Event]
    user: User


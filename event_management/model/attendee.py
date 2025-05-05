import reflex as rx

from event_management.model.event import Event
from event_management.model.user import User

from typing import List


class Attendee(rx.Model, table=True):
    user: User
    events_attending: List[Event]


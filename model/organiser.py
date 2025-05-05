import reflex as rx

from model.event import Event
from model.user import User


class Organiser(rx.Model, table=True):
    events: List[Event]
    user: User


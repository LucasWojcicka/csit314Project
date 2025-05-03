import reflex as rx

from model.user import User


class Attendee(rx.Model, table=True):
    # events_attending: events[]
    user: User


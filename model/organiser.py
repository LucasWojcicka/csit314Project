import reflex as rx

from model.user import User


class Organiser(rx.Model, table=True):
    events: Event[]
    user: User


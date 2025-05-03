import reflex as rx


class User(rx.Model, table=True):
    name: str
    email: str
    id: int
    date_of_birth: Date
    password: str
    username: str
    phone_number: int

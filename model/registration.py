import reflex as rx


class Registration(rx.Model, table=True):
    registration_type: str
    registration_type_perks: perks[]
    description: str
    id: int
    price: int
    approved: bool

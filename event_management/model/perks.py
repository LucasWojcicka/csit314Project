import reflex as rx


class Perks(rx.Model, table=True):
    name: str
    price: int
    description: str
    age_range: str
    duration: int
    available_slots: int

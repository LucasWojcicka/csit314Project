import reflex as rx

from event_management.model.perks import Perks
from typing import List


class Registration(rx.Model, table=True):
    registration_type: str
    registration_type_perks: List[Perks]
    description: str
    id: int
    price: int
    approved: bool

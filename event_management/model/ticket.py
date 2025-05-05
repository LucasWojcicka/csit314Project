import datetime

import reflex as rx
from datetime import date, datetime, time, timedelta


class Ticket(rx.Model, table=True):
    ticket_type: str
    event_id: int
    price_paid: int
    date: datetime.date
    location: str
    ticket_id: int
    paid: bool
    amount_paid: int
    user_id: int
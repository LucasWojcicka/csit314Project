import reflex as rx
from datetime import date, datetime, time, timedelta

class Refund(rx.Model, table=True):
    event_id: int
    user_id: int
    date_started: datetime.date
    date_refunded: datetime.date
    refunded: bool
    reason_description: str
    amount: int
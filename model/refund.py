import reflex as rx


class Refund(rx.Model, table=True):
    event_id: int
    user_id: int
    date_started: Date
    date_refunded: Date
    refunded: bool
    reason_description: str
    amount: int
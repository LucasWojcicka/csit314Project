import reflex as rx


class Ticket(rx.Model, table=True):
    ticket_type: str
    event_id: int
    price_paid: int
    date: Date
    location: str
    ticket_id: int
    paid: bool
    amount_paid: int
    user_id: int
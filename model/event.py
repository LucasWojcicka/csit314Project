import reflex as rx

from model.attendee import Attendee
from model.event_type import EventType


class Event(rx.Model, table=True):
    name: str
    duration: int
    event_type: EventType
    date: date
    location: str
    price_range_lowest: int
    price_range_highest: int
    description: str
    age_range: str
    event_id: int
    attendees_num: int
    attendees: Attendee[]
    # registration_types: reg[]
    available_perks: perks[]
    status: str
    capacity: int
    occupied_capacity: int
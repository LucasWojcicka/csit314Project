import reflex as rx

from model.attendee import Attendee
from model.event_status import EventStatus
from model.event_type import EventType

from typing import List

from model.perks import Perks
from model.registration import Registration


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
    attendees: List[Attendee]
    registration_types: List[Registration]
    available_perks: List[Perks]
    status: EventStatus
    capacity: int
    occupied_capacity: int
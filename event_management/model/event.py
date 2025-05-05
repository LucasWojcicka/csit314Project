import reflex as rx

from event_management.model.attendee import Attendee
from event_management.model.event_status import EventStatus
from event_management.model.event_type import EventType

from typing import List

from event_management.model.perks import Perks
from event_management.model.registration import Registration
from datetime import datetime


class Event(rx.Model, table=True):
    name: str
    duration: int
    event_type: EventType
    date: datetime.date
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
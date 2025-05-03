from enum import Enum
class NotificationCategory(Enum):
    REMINDER = "reminder"
    EVENT_CANCELLED = "event cancelled"
    DATE_CHANGED = "date changed"
    VENUE_CHANGED = "venue changed"
    INFORMATION = "information"

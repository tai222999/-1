import pytz

AVAILABLE_TIMEZONES = [
    'Asia/Taipei',
    'Asia/Tokyo',
    'Asia/Shanghai',
    'Asia/Hong_Kong',
    'Asia/Singapore',
    'Asia/Seoul',
    'Asia/Bangkok',
    'Asia/Kolkata',
    'Asia/Dubai',
    'Europe/London',
    'Europe/Paris',
    'Europe/Berlin',
    'Europe/Moscow',
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'America/Toronto',
    'America/Sao_Paulo',
    'Australia/Sydney',
    'Pacific/Auckland',
    'UTC',
]

class Config:
    def get_all_timezones(self):
        return AVAILABLE_TIMEZONES

    def is_valid_timezone(self, tz_str):
        try:
            pytz.timezone(tz_str)
            return True
        except pytz.UnknownTimeZoneError:
            return False

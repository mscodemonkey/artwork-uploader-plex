import uuid
from typing import Optional
from datetime import datetime, timedelta

class BulkSchedule:
    def __init__(
            self,
            id: Optional[str] = None,
            file: str = "",
            time: Optional[str] = None,
            interval_value: Optional[int] = None,
            interval_unit: Optional[str] = None,
            last_run: Optional[str] = None,
            next_run: Optional[str] = None,
            **kwargs
        ) -> None:
        self.id = id or str(uuid.uuid4())
        self.file = file
        self.time = time
        self.interval_value = interval_value
        self.interval_unit = interval_unit
        self.last_run = last_run
        self.next_run = next_run

    def compute_next_run(self):
        """ Helper function to compute the next run time for any schedule """

        if not self.time and not (self.interval_value and self.interval_unit):
            return None

        interval_value = self.interval_value or 1
        interval_unit = self.interval_unit or "days"

        now = datetime.now().replace(microsecond=0)
        next_run_at: Optional[datetime] = None

        if self.last_run: # If there's a recorded last run, next run time is calculated based on the interval and units (days=1 for daily schedules)
            last_run_at = datetime.fromisoformat(self.last_run)
            next_run_at = last_run_at + timedelta(**{interval_unit: interval_value})

        elif self.time: # If not and it's a daily schedule, set the next run to the defined time
            hour, minute = (int(part) for part in self.time.split(":"))
            next_run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        elif self.interval_value:
            next_run_at = now + timedelta(**{interval_unit: interval_value})

        if next_run_at is None:
            return None

        while next_run_at < now:
            next_run_at += timedelta(**{interval_unit: interval_value})

        self.next_run = next_run_at.isoformat()
        return self.next_run
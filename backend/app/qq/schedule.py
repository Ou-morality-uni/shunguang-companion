from datetime import datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8))


def at(day, clock):
    hour, minute = map(int, clock.split(':'))
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def next_due(policy, now):
    if policy.schedule == 'off':
        return None
    if policy.schedule == 'interval':
        return now + policy.interval_hours * 3600
    day = datetime.fromtimestamp(now, BEIJING)
    due = at(day, policy.daily_time)
    if due.timestamp() <= now:
        due += timedelta(days=1)
    return due.timestamp()


def window(policy, due, cursor):
    if policy.window == 'incremental':
        return cursor, due
    end = at(datetime.fromtimestamp(due, BEIJING), policy.window_end)
    if end.timestamp() > due:
        end -= timedelta(days=1)
    start = at(end, policy.window_start)
    if start >= end:
        start -= timedelta(days=1)
    return start.timestamp(), end.timestamp()

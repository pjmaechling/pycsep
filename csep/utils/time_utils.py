import calendar
import datetime
import re
import warnings
from csep.utils.constants import SECONDS_PER_ASTRONOMICAL_YEAR, SECONDS_PER_DAY

def epoch_time_to_utc_datetime(epoch_time_milli):
    """
    Accepts an epoch_time in milliseconds the UTC timezone and returns a python datetime object.

    See https://docs.python.org/3/library/datetime.html#datetime.datetime.fromtimestamp for information
    about how timezones are handled with this function.

    :param epoch_time: epoch_time in UTC timezone in milliseconds
    :type epoch_time: float
    """
    if epoch_time_milli is None:
        return epoch_time_milli
    epoch_time = epoch_time_milli / 1000
    dt = datetime.datetime.fromtimestamp(epoch_time, datetime.timezone.utc)
    return dt

def datetime_to_utc_epoch(dt):
    """
    Converts python datetime.datetime into epoch_time in milliseconds.


    Args:
        dt (datetime.datetime): python datetime object, should be naive.
    """
    if dt is None:
        return dt

    if dt.tzinfo is None:
        dt=dt.replace(tzinfo=datetime.timezone.utc)

    if str(dt.tzinfo) != 'UTC':
        raise ValueError(f"Timezone info must be UTC. tzinfo={dt.tzinfo}")

    epoch = datetime.datetime(1970, 1, 1, 0, 0, 0, 0).replace(tzinfo=datetime.timezone.utc)
    epoch_time_seconds = (dt - epoch).total_seconds()
    return int(1000.0 * epoch_time_seconds)

def millis_to_days(millis):
    return millis / SECONDS_PER_DAY / 1000

def days_to_millis(days):
    return days * SECONDS_PER_DAY * 1000

def strptime_to_utc_epoch(time_string, format="%Y-%m-%d %H:%M:%S.%f"):
    dt=strptime_to_utc_datetime(time_string, format)
    return datetime_to_utc_epoch(dt)

def timedelta_from_years(time_in_years):
    """
    Returns python datetime.timedelta object based on the astronomical year in seconds.

    :params time_in_years: positive fraction of years 0 <= time_in_years
    :type time_in_years: float
    """
    if time_in_years < 0:
        raise ValueError("time_in_years must be greater than zero.")

    seconds = SECONDS_PER_ASTRONOMICAL_YEAR * time_in_years
    time_delta = datetime.timedelta(seconds=seconds)
    return time_delta

def strptime_to_utc_datetime(time_string, format="%Y-%m-%d %H:%M:%S.%f"):
    """
    Converts time_string with format into time-zone aware datetime object in the UTC timezone.

    Note:
        If the time_string is not in UTC time, it will be converted into UTC timezone.

    Args:
        time_string (str): string representation of datetime
        format (str): format of time_string

    Returns:
        datetime.datetime: timezone aware (utc) object from time_string
    """
    dt = datetime.datetime.strptime(time_string, format).replace(tzinfo=datetime.timezone.utc)
    return dt

def utc_now_datetime():
    return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

def utc_now_epoch():
    return datetime_to_utc_epoch(datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc))

def create_utc_datetime(datetime):
    """Creates TZAware UTC datetime object from unaware object."""
    assert datetime.tzinfo is None
    return datetime.replace(tzinfo=datetime.timezone.utc)

def parse_string_format(time_string):
    """ Fixes some difficulties with different time formats """
    format = "%Y-%m-%d %H:%M:%S"
    if '.' in time_string:
        format = "%Y-%m-%d %H:%M:%S.%f"
    if time_string[-6] == '+':
        format = format + "%z"
    return format

class Specifier(str):
    """Model %Y and such in `strftime`'s format string."""
    def __new__(cls, *args):
        self = super(Specifier, cls).__new__(cls, *args)
        assert self.startswith('%')
        assert len(self) == 2
        self._regex = re.compile(r'(%*{0})'.format(str(self)))
        return self

    def ispresent_in(self, format):
        m = self._regex.search(format)
        return m and m.group(1).count('%') & 1  # odd number of '%'

    def replace_in(self, format, by):
        def repl(m):
            n = m.group(1).count('%')
            if n & 1:  # odd number of '%'
                prefix = '%' * (n - 1) if n > 0 else ''
                return prefix + str(by)  # replace format
            else:
                return m.group(0)  # leave unchanged
        return self._regex.sub(repl, format)

class HistoricTime(datetime.datetime):

    def strftime(self, format):
        year = self.year
        if year >= 1900:
            return super(HistoricTime, self).strftime(format)
        assert year < 1900
        factor = (1900 - year - 1) // 400 + 1
        future_year = year + factor * 400
        assert future_year > 1900

        format = Specifier('%Y').replace_in(format, year)
        result = self.replace(year=future_year).strftime(format)
        if any(f.ispresent_in(format) for f in map(Specifier, ['%c', '%x'])):
            msg = "'%c', '%x' produce unreliable results for year < 1900"
            warnings.warn(msg)
            result = result.replace(str(future_year), str(year))
        assert (future_year % 100) == (year %
                                       100)  # last two digits are the same
        return result


def decimal_year(test_date):
    """ Convert given test date to the decimal year representation.

    Repurposed from CSEP1 Author: Masha Liukis

        Args:
            test_date (datetime.datetime)
    """

    if test_date is None:
        return None

    # This implementation is based on the Matlab version of the 'decyear'
    # function that was inherited from RELM project
    hours_per_day = 24.0
    mins_per_day = hours_per_day * 60.0
    secs_per_day = mins_per_day * 60.0

    # Get number of days in the year of specified test date
    num_days_per_year = 365.0
    if calendar.isleap(test_date.year):
        num_days_per_year = 366.0

    # Compute number of days in months preceding the test date
    # (excluding the month of the test date)
    num_days = sum([calendar.monthrange(test_date.year, i)[1] for i in range(1, test_date.month)])

    dec_year = test_date.year + (num_days + (test_date.day - 1) +
                                 test_date.hour / hours_per_day +
                                 test_date.minute / mins_per_day +
                                 (test_date.second + test_date.microsecond * 1e-6) / secs_per_day) / num_days_per_year
    return dec_year
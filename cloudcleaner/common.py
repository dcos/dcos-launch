import abc
import os
import re
from datetime import timedelta

CI_OWNER = 'cloudcleaner'
EXPIRE_WARNING_MINUTES = 10
EXPIRE_WARNING_TIME = timedelta(minutes=EXPIRE_WARNING_MINUTES)


class UnsafeWithoutEnvVar(Exception):
    """Thrown when cloudlceaner aborts because not all safety checks have been satisfied."""
    pass


def check_test():
    """Validate that dangerous APIs aren't called unless we explicitly approve that this is not a test.

    This keeps us from doing things like getting real ec2 instances to act on when we mean to be testing.
    The envrionment variable is THIS_IS_NOT_A_TEST
    """
    if not os.environ.get('THIS_IS_NOT_A_TEST'):
        raise UnsafeWithoutEnvVar()


def delta_to_str(delta):
    """Convert a timedelta to a string format which is reversable.
    Takes a datetime.timedelta object and converts it into a string
    that is parseable by parse_delta
    """
    # NOTE: Rounds up to nearest minute)
    units = [('m', 60), ('h', 60), ('d', 24), ('w', 7)]

    remaining = delta.total_seconds()

    delta_str = ''

    negative = remaining < 0

    def add_negative():
        return '-' + delta_str if negative else delta_str

    # Only handle things in the future for simplicity in testing.
    if negative:
        remaining = -remaining

    # Print 0 minutes as the base case.
    if remaining == 0:
        return '0m'

    for i in range(0, len(units)):
        unit, count = units[i]

        remainder = int(remaining % count)
        remaining = int(remaining // count)

        # Round up the first unit (seconds) into minutes.
        if i == 0:
            if remainder > 0:
                remaining += 1
        else:
            assert i > 0
            if remainder != 0:
                delta_str = "{}{}{}".format(remainder, units[i - 1][0], delta_str)

        # No need to go further / captured it all, so long as we've printed at
        # least minutes.
        if remaining == 0 and i > 0:
            return add_negative()

    # Print the last unit with all the remaining count.
    delta_str = "{}{}{}".format(remaining, units[-1][0], delta_str)

    return add_negative()


def parse_delta(delta):
    """Parse a timedelta string format into a python timedelta object.
    Takes a delta string like that constructed in delta_to_str and converts
    it into a datetime.timedelta object
    """
    assert delta != 'never'
    possible_args = ['weeks', 'days', 'hours', 'minutes']

    # Find all the <count> <unit> patterns, expand the count + units to build a timedelta.
    chunk_regex = r'(\d+)\s*(\D+)\s*'
    kwargs = {}
    for count, unit in re.findall(chunk_regex, delta, re.I):
        unit = unit.strip()
        int_count = int(count)
        found_unit = False
        # match so that units can be given as single letters instead of whole words
        for arg in possible_args:
            if arg.startswith(unit):
                kwargs[arg] = int_count
                found_unit = True
                break

        if not found_unit:
            raise ValueError("Unknown unit '{}' when parsing '{}'".format(unit, delta))

    return timedelta(**kwargs)


class AbstractCleaner(metaclass=abc.ABCMeta):
    """Simple wrapper for storing state between cleaning steps
    as well as defining a standard interface for all providers
    """
    def __init__(self, now):
        self.now = now

    @abc.abstractmethod
    def collect_resources(self, users):
        pass

    @abc.abstractmethod
    def clean_resources(self, dry_run, match_str):
        pass

    @abc.abstractmethod
    def make_report(self):
        pass


class MockCleaner(AbstractCleaner):
    def collect_resources(self, users, name='Mock'):
        pass

    def clean_resources(self, dry_run, match_str):
        pass

    def make_report(self):
        return {}

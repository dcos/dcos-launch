from datetime import datetime, timedelta, timezone

import cloudcleaner

now = datetime(2016, 1, 8, 1, 20, 30, 14, timezone.utc)


def test_delta_to_str():
    """Test converting a timedelta to a string notation for it."""
    def check(delta_str, delta):
        assert cloudcleaner.common.delta_to_str(delta) == delta_str

    check('0m', timedelta())
    # Round up to one minute for seconds less than a minute
    check('1m', timedelta(seconds=10))
    check('1m', timedelta(minutes=1))
    check('2m', timedelta(minutes=1, seconds=5))
    check('1h', timedelta(minutes=60))
    check('1h5m', timedelta(minutes=65))
    check('1d', timedelta(days=1))
    check('1d2m', timedelta(days=1, minutes=2))
    check('1d23h59m', timedelta(days=1, hours=23, minutes=59))
    check('2w', timedelta(weeks=2))
    check('2w1m', timedelta(weeks=2, seconds=10))
    check('-2w1m', -timedelta(weeks=2, seconds=10))
    check('-1d23h59m', -timedelta(days=1, hours=23, minutes=59))


def test_parse_delta():
    """Test parsing a timedelta string produces the expected timedelta."""
    parse = cloudcleaner.common.parse_delta
    assert parse('') == timedelta()
    assert parse('8hours') == timedelta(hours=8)
    assert parse('1m') == timedelta(minutes=1)
    assert parse(' 23 h ') == timedelta(hours=23)
    assert parse('2 d ') == timedelta(days=2)
    assert parse(' 987 w') == timedelta(weeks=987)
    assert parse('5h2m') == timedelta(hours=5, minutes=2)
    assert parse('1w2d13m') == timedelta(weeks=1, days=2, minutes=13)
    assert parse('13m1w') == timedelta(weeks=1, minutes=13)
    assert parse("5days2hours") == timedelta(days=5, hours=2)
    assert parse("24hours15minutes") == timedelta(hours=24, minutes=15)
    assert parse("5weeks3hours") == timedelta(weeks=5, hours=3)

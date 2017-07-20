"""Test the overall behavior of cloudcleaner."""
import copy
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

import cloudcleaner
import cloudcleaner.aws
import cloudcleaner.azure
import cloudcleaner.common
import cloudcleaner.main

from cloudcleaner.azure import resource_group_to_json

pytestmark = [pytest.mark.usefixtures('mocked_aws')]

now = datetime(2016, 1, 8, 1, 20, 30, 14, timezone.utc)


@pytest.fixture
def mocked_aws(monkeypatch):
    monkeypatch.setattr(cloudcleaner.aws, 'AwsCleaner', cloudcleaner.common.MockCleaner)


class _MockResourceGroup:
    def __init__(self, tags: dict, name: str='ResourceGroupTestFooBar'):
        self.tags = tags
        self.name = name
        self.location = 'West US'
        self.provisioning_state = 'Succeeded'

    @property
    def properties(self):
        return self


def dump_time(dt):
    """ Timestamps must be dumped without TZinfo so that isoformat
    doesn't add an a +HH:MM which will not be parseable
    """
    return dt.replace(tzinfo=None).isoformat()


def test_categorize():
    def check(categories: set, tags: dict):
        users = ['testuser', 'foo', cloudcleaner.common.CI_OWNER]
        assert set(cloudcleaner.azure.categorize_resource_group(
            _MockResourceGroup(tags), now, users)) == categories

    new = {'no_owner', 'needs_expiration', 'needs_creation_time'}
    check(new, None)
    check(new, {})

    check(new, {'do_not_delete': True})

    check({'invalid_owner', 'needs_creation_time', 'needs_expiration'}, {'owner': 'someone-who-isnt-real'})

    check({'needs_creation_time', 'needs_expiration'}, {'owner': 'testuser'})

    check({'never_expire', 'needs_creation_time'}, {'owner': 'testuser', 'expiration': 'never'})

    check({'invalid_expiration', 'needs_creation_time'}, {'owner': 'testuser', 'expiration': 'foobar'})
    check({'invalid_expiration', 'needs_creation_time'}, {'owner': 'testuser', 'expiration': 'tomorrow'})
    check({'invalid_expiration', 'needs_creation_time'}, {'owner': 'testuser', 'expiration': 'three days'})

    check({'needs_creation_time'}, {'owner': 'testuser', 'expiration': '2w'})
    check({'needs_creation_time'}, {'owner': 'testuser', 'expiration': '3days'})
    check({'needs_creation_time'}, {'owner': 'testuser', 'expiration': '99hours'})
    check({'needs_creation_time'}, {'owner': 'testuser', 'expiration': '99 hours'})
    check({'needs_creation_time'}, {'owner': 'testuser', 'expiration': '2 day 99 hours'})

    check({'invalid_creation_time'}, {'owner': 'testuser', 'expiration': '99hours', 'creation_time': 'foobar'})
    check({'invalid_creation_time'}, {'owner': 'testuser', 'expiration': '99hours', 'creation_time': '12-25-2015'})

    expiration_str = '99hours'
    exact_expiration_dt = now - timedelta(hours=99)  # this is the time of exact expiration
    expire_not_soon_dt = exact_expiration_dt + (cloudcleaner.common.EXPIRE_WARNING_TIME + timedelta(minutes=1))
    check({'ok'}, {
        'owner': 'testuser',
        'expiration': expiration_str,
        'creation_time': dump_time(expire_not_soon_dt)})

    expire_soon_dt = exact_expiration_dt + (cloudcleaner.common.EXPIRE_WARNING_TIME - timedelta(minutes=1))
    check({'expire_soon'}, {
        'owner': 'testuser',
        'expiration': '99hours',
        'creation_time': dump_time(expire_soon_dt)})

    expired_dt = exact_expiration_dt - timedelta(minutes=1)
    check({'expired'}, {
        'owner': 'testuser',
        'expiration': expiration_str,
        'creation_time': dump_time(expired_dt)})


class MockRmc:
    def __init__(self, group_list=None):
        self.group_list = group_list if group_list is not None else None

    @property
    def resource_groups(self):
        """ rmc is only called to access resource_groups so just map it back
        to this object to avoid creating an extra useless object
        """
        return self

    def patch(self, name: str, tags: dict, raw=True):
        pass

    def list(self):
        return self.group_list


def mock_delete_resource_group(mock_rmc, resource_group_name):
    if mock_rmc.group_list is None:
        return
    for i in range(len(mock_rmc.group_list)):
        if mock_rmc.group_list[i].name == resource_group_name:
            del mock_rmc.group_list[i]
            return
    raise Exception('Group {} cannot be deleted because it cannot be found'.format(resource_group_name))


@pytest.fixture
def mocked_rmc(monkeypatch):
    monkeypatch.setattr(cloudcleaner.azure, 'get_resource_mgmt_client', lambda: MockRmc())
    monkeypatch.setattr(cloudcleaner.azure, 'delete_resource_group', mock_delete_resource_group)


def test_take_resource_group_action(monkeypatch, mocked_rmc):
    """Test taking actions given a category + instance. Both dry run and not."""
    monkeypatch.setattr(
        cloudcleaner.azure, 'tag_creation_time',
        lambda rg: rg.tags.update({'creation_time': dump_time(now - timedelta(days=30))}))

    def check(category,
              action,
              tags,
              expected_tags=dict()):

        resource_group = _MockResourceGroup(tags)
        assert cloudcleaner.azure.take_resource_group_action(
            MockRmc(), category, resource_group) == action
        assert cloudcleaner.azure.take_resource_group_action(
            MockRmc(), category, resource_group) == action

        # Check that tags match expected
        if len(expected_tags) > 0:
            for key, value in expected_tags.items():
                assert resource_group.tags[key] == value

    check('no_owner', 'owned_by_cloudcleaner',
          {}, expected_tags={'owner': cloudcleaner.common.CI_OWNER})
    check('invalid_owner', 'owned_by_cloudcleaner',
          {'owner': 'foobar'}, expected_tags={'owner': cloudcleaner.common.CI_OWNER,
                                              'error_message': 'invalid owner was set'})
    check('error', 'noop', {})

    check('needs_expiration', 'add_expiration', {}, expected_tags={'expiration': '2h'})
    check('invalid_expiration', 'add_expiration', {'expiration': 'foobar'}, expected_tags={'expiration': '2h'})
    check('invalid_expiration', 'add_expiration',
          {'expiration': 'foobar', 'owner': 'test_user', 'creation_time': dump_time(now)},
          expected_tags={'expiration': '2h'})

    check('needs_creation_time', 'add_creation_time', {},
          expected_tags={'creation_time': dump_time(now - timedelta(days=30))})
    check('invalid_creation_time', 'add_creation_time', {'creation_time': 'foobar'},
          expected_tags={'creation_time': dump_time(now - timedelta(days=30))})

    check('expired', 'deleted', {'owner': 'test_user', 'creation_time': dump_time(now)})


def test_advance_states(tmpdir, monkeypatch, mocked_rmc):
    monkeypatch.setattr(
        cloudcleaner.azure, 'tag_creation_time',
        lambda rg: rg.tags.update({'creation_time': dump_time(now)}))
    with tmpdir.as_cwd():
        do_test_advance_states(monkeypatch)


def do_test_advance_states(monkeypatch):
    """make a number of resource groups with different tags and step through them
    """
    anonymous = _MockResourceGroup({}, name='anonymous')  # should be deleted in 2h
    invalid_user = _MockResourceGroup({'owner': 'foo'}, name='invalid_user')  # should be deleted in 2h
    valid_user = _MockResourceGroup({'owner': 'test_user'}, name='valid_user')  # should be deleted in 2h
    # gone in 2h
    invalid_expiration = _MockResourceGroup({
        'expiration': 'next week',
        'owner': 'test_user',
        'creation_time': dump_time(now)}, name='invalid_expiration')
    # will be deleted 12h in
    ok_group = _MockResourceGroup({
        'owner': 'test_user',
        'creation_time': dump_time(now - timedelta(hours=36)),
        'expiration': '2days'}, name='ok_group')
    # will be deleted 1h in
    ci_group = _MockResourceGroup({
        'owner': cloudcleaner.common.CI_OWNER,
        'creation_time': dump_time(now - timedelta(hours=3)),
        'expiration': '4h'}, name='ci_group')
    # will never expire
    never_expire = _MockResourceGroup({'expiration': 'never'}, name='never_expire')

    resource_group_pool = [anonymous, invalid_user, valid_user, ok_group, ci_group, invalid_expiration, never_expire]

    expected_states = [
        (
            timedelta(minutes=0),
            {
                'never_expire': ['never_expire'],
                'no_owner': ['anonymous', 'never_expire'],
                'invalid_owner': ['invalid_user'],
                'needs_creation_time': ['anonymous', 'valid_user', 'invalid_user', 'never_expire'],
                'needs_expiration': ['anonymous', 'valid_user', 'invalid_user'],
                'ok': ['ok_group', 'ci_group']
            },
            {
                'owned_by_cloudcleaner': ['anonymous', 'invalid_user', 'never_expire'],
                'add_expiration': ['anonymous', 'valid_user', 'invalid_user', 'invalid_expiration'],
                'add_creation_time': ['anonymous', 'valid_user', 'invalid_user', 'never_expire'],
            },
        ),
        (
            timedelta(hours=1) - cloudcleaner.common.EXPIRE_WARNING_TIME,
            {
                'never_expire': ['never_expire'],
                'ok': ['ok_group', 'anonymous', 'invalid_user',
                       'valid_user', 'invalid_expiration'],
                'expire_soon': ['ci_group']
            },
            {}
        ),
        (
            timedelta(hours=1),
            {
                'never_expire': ['never_expire'],
                'ok': ['ok_group', 'anonymous', 'invalid_user',
                       'valid_user', 'invalid_expiration'],
                'expired': ['ci_group']
            },
            {
                'deleted': ['ci_group']
            },
            {}
        ),
        (
            timedelta(hours=2) - cloudcleaner.common.EXPIRE_WARNING_TIME,
            {
                'never_expire': ['never_expire'],
                'ok': ['ok_group'],
                'expire_soon': ['invalid_expiration', 'valid_user', 'invalid_user', 'anonymous']
            },
            {}
        ),
        (
            timedelta(hours=2),
            {
                'never_expire': ['never_expire'],
                'ok': ['ok_group'],
                'expired': ['invalid_expiration', 'anonymous', 'invalid_user', 'valid_user']
            },
            {
                'deleted': ['anonymous', 'invalid_expiration', 'valid_user', 'invalid_user']
            },
            {}
        ),
        (
            timedelta(hours=12) - cloudcleaner.common.EXPIRE_WARNING_TIME,
            {
                'never_expire': ['never_expire'],
                'expire_soon': ['ok_group']
            },
            {}
        ),
        (
            timedelta(hours=12),
            {
                'never_expire': ['never_expire'],
                'expired': ['ok_group']
            },
            {
                'deleted': ['ok_group']
            },
        ),
        (
            timedelta(hours=20),
            {
                'never_expire': ['never_expire'],
            },
            {}
        )
    ]

    # State tracking
    clock = copy.copy(now)
    time_passed = timedelta()
    step_duration = cloudcleaner.common.EXPIRE_WARNING_TIME
    # step_duration = timedelta(minutes=30)

    mock_rmc = MockRmc(group_list=resource_group_pool)
    # Make it so do_main is running in the sandbox we've prepared, clock and all.
    monkeypatch.setattr('cloudcleaner.get_users', lambda: ['test_user'])
    monkeypatch.setattr('cloudcleaner.get_time', lambda: clock)
    monkeypatch.setattr(cloudcleaner.azure, 'get_resource_mgmt_client', lambda: mock_rmc)
    monkeypatch.setattr(cloudcleaner.azure, 'resource_group_to_json', lambda rg, now: rg.name)

    # Make sure the build directory is clean so we only get output from the
    # current run of do_main
    assert not os.path.exists('cloudcleaner.html')
    assert not os.path.exists('report.json')

    expected_state = expected_states.pop(0)

    while True:

        cloudcleaner.main.do_main(['--be-ruthless'])

        report = json.load(open('report.json'))['azure']
        # Sorted to ensure stable results
        if time_passed >= expected_state[0]:
            for k, v in expected_state[1].items():
                found_groups = report['categorized_resource_groups'][k]
                expected_groups = expected_state[1][k]
                assert set(found_groups) == set(expected_groups), 'T={}. {}: found {} but expected {}'.format(
                    time_passed, k, found_groups, expected_groups)
            for k, v in expected_state[2].items():
                found_groups = report['resource_group_actions'][k]
                expected_groups = v
                assert set(found_groups) == set(expected_groups), 'T={}. {}: found {} but expected {}'.format(
                    time_passed, k, found_groups, expected_groups)

            # Now reset for the next state
            if len(expected_states) == 0:
                break
            expected_state = expected_states.pop(0)

        # Make sure the html report exists
        assert os.path.exists('cloudcleaner.html')

        # Advance in time
        clock += step_duration
        time_passed += step_duration

        # Stop after simulating 30 hours.
        if time_passed >= timedelta(hours=30):
            break


def test_resource_group_to_json(mocked_rmc):
    assert resource_group_to_json(
        _MockResourceGroup({}, name='foobar'), now) == {
            'name': 'foobar',
            'state': 'Succeeded',
            'creation_time': 'unset',
            'expiration': 'unset',
            'owner': 'unset'}
    assert resource_group_to_json(
        _MockResourceGroup({'owner': 'foobar'}, name='baz'), now) == {
            'name': 'baz',
            'state': 'Succeeded',
            'creation_time': 'unset',
            'expiration': 'unset',
            'owner': 'foobar'}
    assert resource_group_to_json(
        _MockResourceGroup({'expiration': 'never'}, name='abc'), now) == {
            'name': 'abc',
            'state': 'Succeeded',
            'creation_time': 'unset',
            'owner': 'unset',
            'expiration': 'never'}
    assert resource_group_to_json(
        _MockResourceGroup({'creation_time': dump_time(now)}, name='xyz'), now) == {
            'name': 'xyz',
            'creation_time': dump_time(now),
            'state': 'Succeeded',
            'owner': 'unset',
            'expiration': 'unset',
            'uptime': '0m'}

"""Test the overall behavior of cloudcleaner."""
import json
import logging
import os.path
from copy import copy
from datetime import datetime, timedelta, timezone

import pytest

import cloudcleaner
import cloudcleaner.aws
import cloudcleaner.azure
import cloudcleaner.main

pytestmark = [pytest.mark.usefixtures('mocked_azure')]

now = datetime(2016, 1, 8, 1, 20, 30, 14, timezone.utc)
instance_id = 0


@pytest.fixture
def mocked_azure(monkeypatch):
    monkeypatch.setattr(cloudcleaner.azure, 'AzureCleaner', cloudcleaner.common.MockCleaner)


class _MockInstance():
    """Mock AWS EC2 instance for testing with subset of boto3 api."""

    def __init__(self, instance_id, state, tags, launch_time):
        assert isinstance(state, str)
        assert isinstance(tags, dict)

        self.instance_id = instance_id
        self.launch_time = launch_time
        self.__tags = tags
        self.__state = state
        self.actions_taken = []
        self.accessed_properties = set()
        self.instance_type = "m3.testing"

    def create_tags(self, Tags, DryRun):  # noqa: N803, copying AWS API
        new_tags = dict()
        for tag_dict in Tags:
            new_tags[tag_dict['Key']] = tag_dict['Value']

        if DryRun:
            return

        self.__tags.update(new_tags)

        self.actions_taken.append(('create_tags', new_tags))

    @property
    def tags(self):
        self.accessed_properties.add('tags')
        tags_list = []
        for k, v in self.__tags.items():
            tags_list.append({'Key': k, 'Value': v})
        return tags_list

    @property
    def state(self):
        self.accessed_properties.add('state')
        return {
            'Name': self.__state
        }

    # DryRun is a mandatory arg to try to help enforce that we always pass it
    # through.
    def terminate(self, DryRun):  # noqa: N803, copying AWS API
        if DryRun:
            return
        self.actions_taken.append(('terminated', DryRun))
        self.__state = 'terminated'

    # DryRun is a mandatory arg to try to help enforce that we always pass it
    # through.
    def stop(self, DryRun):  # noqa: N803, copying AWS API
        if DryRun:
            return
        self.actions_taken.append(('stop', DryRun))
        self.__state = 'stopped'

    def __str__(self):
        return str(self.instance_id)

    def __repr__(self):
        return "<test_cloudcleaner._MockInstance {}>".format(self.instance_id)

    def __lt__(self, that):
        return self.instance_id < that.instance_id


class _MockKeyPair:
    def __init__(self, name):
        self.key_name = name

    def delete(self):
        pass


class _MockStack:
    def __init__(self, name):
        self.stack_name = name


def make_instance(state='running', tags=dict(), launch_delta=timedelta(minutes=45)):
    """Create a mock instance with the given time since launch."""
    global instance_id
    instance_id += 1
    return _MockInstance(
        instance_id=instance_id,
        tags=tags,
        state=state,
        launch_time=now - launch_delta)


def test_categorize():
    """Make sure instances in specific states fall into the expected categories."""
    def check(category, **instance_args):
        users = ['cody', 'foo', 'owner']
        instance = make_instance(**instance_args)
        assert cloudcleaner.aws.categorize_instance(instance, now, users) == category

        # Categorizing an instance shouldn't take any actions
        assert instance.actions_taken == []

    def check_run_stop(category, **instance_args):
        check(category, state='running', **instance_args)
        check(category, state='stopped', **instance_args)

    def check_owned(category, **instance_args):
        tags = instance_args.get('tags', dict())
        tags['owner'] = 'cody'
        instance_args['tags'] = tags
        check_run_stop(category, **instance_args)

    # Check the different categories other than running are handled as expected
    check('terminated', state='terminated')
    check('terminated', state='terminated', launch_delta=timedelta(minutes=0))
    check('terminated', state='terminated', launch_delta=timedelta(minutes=100))

    check('changing_state', state='pending')
    check('changing_state', state='shutting-down')
    check('no_owner', state='stopped')  # stopped instance which has been up longer
    # than 30 minutes means no owner, instance will be deleted.

    check('unknown_state', state='some-new-state')

    # Test Running, stopped where expiration is the key.
    check_run_stop('new', launch_delta=timedelta(minutes=0))
    check_run_stop('new', launch_delta=timedelta(minutes=15))
    check_run_stop('new', launch_delta=timedelta(minutes=30))
    # Instances younger than 30 minutes are always new.
    check_owned('new', launch_delta=timedelta(minutes=30), tags={'expiration': '30m'})
    check_run_stop('no_owner', launch_delta=timedelta(minutes=31))
    check_run_stop('no_owner')

    # CCM tagged instances are out of scope
    check_run_stop('ccm', tags={'aws:cloudformation:stack-id': 'foo'})

    # Running or stopped with owner + expiration info
    check_run_stop('needs_expiration', tags={'owner': 'cody'})
    check_owned('needs_expiration')
    check_run_stop('needs_expiration', tags={'owner': 'foo'})
    check_run_stop('no_owner', tags={'ower': 'owner'})
    check_run_stop('no_owner', tags={'ower': 'cody'})

    # Not in users -> invalid_owner
    check_run_stop('invalid_owner', tags={'owner': 'test'})

    check_owned('invalid_expiration', tags={'expiration': '30hrs'})
    check_owned('invalid_expiration', tags={'expiration': 'foo'})
    check_owned('invalid_expiration', tags={'expiration': 'foo5123'})

    check_owned('never_expire', tags={'expiration': 'never'})
    check_owned('expired', launch_delta=timedelta(minutes=31), tags={'expiration': '30m'})
    check_owned('expired', launch_delta=timedelta(minutes=100), tags={'expiration': '30m'})
    check_owned('expired', launch_delta=timedelta(minutes=100), tags={'expiration': '1h'})

    check_owned('ok', launch_delta=timedelta(minutes=31), tags={'expiration': '50m'})
    check_owned('expire_soon', launch_delta=timedelta(minutes=40), tags={'expiration': '50m'})
    check_owned('expire_soon', launch_delta=timedelta(minutes=40), tags={'expiration': '45m'})
    check_owned('expire_soon', launch_delta=timedelta(minutes=40), tags={'expiration': '41m'})
    check_owned('expired', launch_delta=timedelta(minutes=40), tags={'expiration': '40m'})

    check_owned('ok', launch_delta=timedelta(hours=1), tags={'expiration': '2h'})
    check_owned('ok', launch_delta=timedelta(hours=1), tags={'expiration': '1h15m'})
    check_owned('ok', launch_delta=timedelta(hours=2), tags={'expiration': '300m'})


def test_instance_to_json():
    """Check converting an instance from python object to json works."""
    assert cloudcleaner.aws.instance_to_json(_MockInstance('asdf', 'running', dict(), now), now) == {
        'id': 'asdf',
        'state': 'running',
        'tags': {},
        'launch_time': '2016-01-08T01:20:30.000014+00:00',
        'uptime': '0m',
        'owner': None,
        'expiration': None,
        'instance_type': 'm3.testing'
    }

    assert cloudcleaner.aws.instance_to_json(_MockInstance(
        'asdf', 'stopped', {'owner': 'cody', 'expiration': '1m'}, now - timedelta(hours=1)), now) == {
            'id': 'asdf',
            'state': 'stopped',
            'tags': {'owner': 'cody', 'expiration': '1m'},
            'launch_time': '2016-01-08T00:20:30.000014+00:00',
            'uptime': '1h',
            'owner': 'cody',
            'expiration': '1m',
            'instance_type': 'm3.testing'}

    assert cloudcleaner.aws.instance_to_json(_MockInstance(
        'asdf', 'stopped', {'expiration': '30d2h5m'}, now - timedelta(days=10)), now) == {
            'id': 'asdf',
            'state': 'stopped',
            'tags': {'expiration': '30d2h5m'},
            'launch_time': '2015-12-29T01:20:30.000014+00:00',
            'uptime': '1w3d',
            'owner': None,
            'expiration': '30d2h5m',
            'instance_type': 'm3.testing'}


def test_take_instance_action():
    """Test taking actions given a category + instance. Both dry run and not."""
    def check(category,
              action,
              actions_taken=list(),
              launch_delta=timedelta(minutes=0),
              accessed_properties=set(),
              skip_first=False,
              **instance_args):

        instance_args['launch_delta'] = launch_delta
        instance = make_instance(**instance_args)
        assert cloudcleaner.aws.take_instance_action(category, instance, now, True) == action

        # Taking an action shouldn't read out properties / act on them.
        assert instance.accessed_properties == accessed_properties
        # In dry run no actions should be taken
        assert instance.actions_taken == []
        assert cloudcleaner.aws.take_instance_action(category, instance, now, False) == action
        assert instance.actions_taken == actions_taken

    # All the no-op cases
    check('ccm', 'noop')
    check('changing_state', 'noop')
    check('new', 'noop')
    check('terminated', 'noop')
    check('unknown_state', 'noop')

    # If categorize puts out a bad / unexpected category
    check('foo', 'unknown_category')

    # TODO(cmaloney): Test with creation time not equal to the present, should
    # add however much time has already elapsed to the expiration.
    check('no_owner', 'stop', [('stop', False), ('create_tags', {'expiration': '1d'})])
    check('needs_expiration', 'add_expire', [('create_tags', {'expiration': '50m'})])
    check('no_owner', 'stop', [('stop', False), ('create_tags', {'expiration': '1d20m'})],
          launch_delta=timedelta(minutes=20))
    check('needs_expiration', 'add_expire', [('create_tags', {'expiration': '1h20m'})],
          launch_delta=timedelta(minutes=30))

    # Invalid owner (like no_owner but one additional tag.
    invalid_owner_tag = ('create_tags', {'message': 'Owner does not exist in slack as a username'})
    check('invalid_owner', 'stop', [('stop', False), ('create_tags', {'expiration': '1d'}), invalid_owner_tag])
    check('invalid_owner', 'stop', [('stop', False), ('create_tags', {'expiration': '1d20m'}), invalid_owner_tag],
          launch_delta=timedelta(minutes=20))

    # Terminate an instance
    check('expired', 'terminated', [('terminated', False)])
    check('expired',
          'terminated',
          [('terminated', False)],
          tags={'owner': 'cody'})


def test_advance_states(monkeypatch, tmpdir):
    """Take an instance, and trace how the state changes over time.

    This makes sure that event chains happen properly (starting -> no_owner/stop -> terminate).
    """
    # Move to a tmpdir so report.json and cleanup.html don't litter the source tree.
    with tmpdir.as_cwd():
        do_test_advance_states(monkeypatch)


def _check_instance_state(instance,
                          expected_state,
                          report,
                          is_start_of_state,
                          elapsed_time):
    # Should always find a state for the instance
    assert expected_state is not None
    assert expected_state.keys() <= {'action', 'actions_taken', 'category', 'state'}
    assert expected_state.keys() >= {'action', 'category'}

    action = expected_state['action']
    if is_start_of_state:
        if expected_state['action'] == 'noop':
            assert instance.actions_taken == []
            assert 'actions_taken' not in expected_state
        else:
            assert instance.actions_taken == expected_state['actions_taken']
    else:
        assert instance.actions_taken == []

    # Check to make sure the instance state matches the expected for the time window.
    assert instance.state['Name'] == expected_state.get('state', 'running')

    # Check the instance was labelled in the report as expected.
    id_str = str(instance.instance_id)

    def check_labelled_properly(section, label):
        found = False
        for instance in report[section].get(label, []):
            if instance['id'] == id_str:
                found = True
                break

        assert found, "{} was not labelled in section {} as expected. Should have been: {}.\nReport: {}".format(
            id_str,
            section,
            label,
            json.dumps(report[section], sort_keys=True, indent=4, separators=(',', ': ')))

    # Category is correctoin
    check_labelled_properly('categorized_instances', expected_state['category'])

    # Action is correct. Note actions are only taken on state transition. Rest of state is no-op.
    # That is accounted for when we set action earlier.
    check_labelled_properly('instance_actions', action)


def do_test_advance_states(monkeypatch):
    """Check that advancing instances through time results in the expected states at the right times."""
    def get_users():
        return {'cody'}

    def make_instance_tags(instance_id, tags=dict()):
        return _MockInstance(instance_id=instance_id, launch_time=now, tags=tags, state='running')

    expected_steps = dict()

    # General instance expiring
    normal_instance = make_instance_tags('id-normal', {'expiration': '4h', 'owner': 'cody'})
    expected_steps[normal_instance] = [
        ('0m', {'category': 'new', 'action': 'noop'}),
        ('32m', {'category': 'ok', 'action': 'noop'}),
        ('3h50m', {'category': 'expire_soon', 'action': 'noop'}),
        ('4h', {
            'category': 'expired',
            'action': 'terminated',
            'actions_taken': [('terminated', False)],
            'state': 'terminated',
        }),
        ('4h2m', {
            'category': 'terminated',
            'action': 'noop',
            'state': 'terminated'})]

    # No owner
    no_owner_instance = make_instance_tags('id-no_owner')
    expected_steps[no_owner_instance] = [
        ('0m', {'category': 'new', 'action': 'noop'}),
        ('32m', {
            'category': 'no_owner',
            'action': 'stop',
            'actions_taken': [('stop', False), ('create_tags', {'expiration': '1d32m'})],
            'state': 'stopped'}),
        ('34m', {
            'category': 'no_owner_stopped',
            'action': 'noop',
            'state': 'stopped'}),
        ('1d32m', {
            'category': 'expired',
            'state': 'terminated',
            'action': 'terminated',
            'actions_taken': [('terminated', False)]
        }),
        ('1d34m', {
            'category': 'terminated',
            'state': 'terminated',
            'action': 'noop'
        })]

    # TODO(cmaloney): No owner gets owner after stopped, and is started again by user.

    # TODO(cmaloney): No owner, gets started after stopped

    # No expiration
    no_expiration_instance = make_instance_tags('id-no_expiration', {'owner': 'cody'})
    expected_steps[no_expiration_instance] = [
        ('0m', {'category': 'new', 'action': 'noop'}),
        ('32m', {
            'category': 'needs_expiration',
            'action': 'add_expire',
            'actions_taken': [('create_tags', {'expiration': '1h22m'})]}),
        ('34m', {'category': 'ok', 'action': 'noop'}),
        ('1h12m', {'category': 'expire_soon', 'action': 'noop'}),
        ('1h22m', {
            'category': 'expired',
            'action': 'terminated',
            'actions_taken': [('terminated', False)],
            'state': 'terminated'}),
        ('1h24m', {'category': 'terminated', 'action': 'noop', 'state': 'terminated'})]

    # CCM instance
    ccm_instance = make_instance_tags('id-ccm', {'aws:cloudformation:stack-id': 'something'})
    expected_steps[ccm_instance] = [('0m', {'category': 'ccm', 'action': 'noop'})]

    def get_instances():
        return list(expected_steps.keys())

    # Check all step timelines start at 0 (Critical for the step finding later)
    for instance, steps in expected_steps.items():
        assert steps[0][0] == '0m'

    # State tracking
    clock = copy(now)
    time_passed = timedelta()
    step_duration = timedelta(minutes=2)  # We're running at 2 minute intervals in production.

    # Make it so do_main is running in the sandbox we've prepared, clock and all.
    monkeypatch.setattr('cloudcleaner.get_users', get_users)
    monkeypatch.setattr('cloudcleaner.aws.get_instances', get_instances)
    monkeypatch.setattr('cloudcleaner.aws.get_keypairs', lambda: [])
    monkeypatch.setattr('cloudcleaner.aws.get_stacks', lambda: [])
    monkeypatch.setattr('cloudcleaner.get_time', lambda: clock)

    # For sanity since we're running CC a lot of times, and each prints a lot of lines...
    logging.basicConfig(level=logging.WARNING)

    # Make sure the build directory is clean so we only get output from the
    # current run of do_main
    assert not os.path.exists('cloudcleaner.html')
    assert not os.path.exists('report.json')

    while True:

        # Reset instance actions_taken so that we can see what happens in this run
        for instance in get_instances():
            instance.actions_taken = []

        # Check a dry run doesn't change the state store or mutate instance state.
        cloudcleaner.main.do_main([])

        for instance in get_instances():
            assert instance.actions_taken == []

        # Expect actual run to advance all instances. All instances should be in
        # the most recent step they passed.
        cloudcleaner.main.do_main(['--be-ruthless', '--key-match', 'my-ci'])

        report = json.load(open('report.json'))['aws']
        # Sorted to ensure stable results
        for instance in sorted(get_instances()):

            # Find the current step
            cur_state = None
            state_start_time = None
            for time, state in expected_steps[instance]:
                state_time = cloudcleaner.common.parse_delta(time)

                # If not enough time to reach the state has passed the last state is
                # the right one
                if time_passed < state_time:
                    break

                cur_state = state
                state_start_time = state_time

            # TODO(cmaloney): Make a better mechanism to spy / introspect this.
            _check_instance_state(
                instance=instance,
                expected_state=cur_state,
                report=report,
                is_start_of_state=time_passed == state_start_time,
                elapsed_time=cloudcleaner.common.delta_to_str(time_passed))

        # Make sure the html report exists
        assert os.path.exists('cloudcleaner.html')

        # Advance in time
        clock += step_duration
        time_passed += step_duration

        # Stop after simulating 30 hours.
        if time_passed >= timedelta(hours=30):
            break

    # TODO(cmaloney): Add test that all instances are in their end state


def test_take_keypair_action(monkeypatch, tmpdir):
    """Check that taking an action on a keypair acts as expected."""
    expired_key = _MockKeyPair('test-from-my-ci-yesterday')
    live_key = _MockKeyPair('test-from-my-ci-today')
    untracked_key = _MockKeyPair('foo')

    test_stack = _MockStack(live_key.key_name)

    monkeypatch.setattr('cloudcleaner.get_users', lambda: [])
    monkeypatch.setattr('cloudcleaner.aws.get_instances', lambda: [])
    monkeypatch.setattr('cloudcleaner.aws.get_keypairs', lambda: [expired_key, live_key, untracked_key])
    monkeypatch.setattr('cloudcleaner.aws.get_stacks', lambda: [test_stack])
    with tmpdir.as_cwd():
        cloudcleaner.main.do_main(['--be-ruthless', '--key-match', 'my-ci'])

        report = json.load(open('report.json'))['aws']

    assert report['keypair_actions']['delete'] == [expired_key.key_name]
    assert sorted(report['keypair_actions']['noop']) == sorted([live_key.key_name, untracked_key.key_name])

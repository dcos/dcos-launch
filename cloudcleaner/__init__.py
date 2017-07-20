"""Tool for automatically cleaning up AWS resources no one claims or that aren't in use."""
import os
from datetime import datetime, timezone

from slacker import Slacker

import cloudcleaner
import cloudcleaner.aws
import cloudcleaner.azure
import cloudcleaner.common


def get_slack():
    """Get a Slack API object."""
    cloudcleaner.common.check_test()
    return Slacker(token=os.environ['SLACK_TOKEN'])


def get_users():
    """Get all the users who could take ownership of resources."""
    cloudcleaner.common.check_test()

    slack = get_slack()
    users = []
    for user in slack.users.list().body['members']:
        users.append(user['name'])

    return users


def get_time():
    """Get the current time.

    This is an extra function here to make getting the time be easily monkeypatched out.
    """
    return datetime.now(timezone.utc)


def run(dry_run, match_str):
    """Run cloudcleaner and return a JSON report of the actions."""
    now = get_time()
    report = {
        'now': now.isoformat(),
        'aws': {'categorized_instances': {}, 'instance_actions': {}, 'keypair_actions': {}},
        'azure': {'resource_group_actions': {}, 'categorized_resource_groups': {}}}
    for Cleaner in (cloudcleaner.aws.AwsCleaner, cloudcleaner.azure.AzureCleaner):
        try:
            this_cleaner = Cleaner(now)
            this_cleaner.collect_resources(get_users())
            this_cleaner.clean_resources(dry_run, match_str)
            report.update(this_cleaner.make_report())
        except Exception as ex:
            # If Unsafe then immediately raise
            if isinstance(ex, cloudcleaner.common.UnsafeWithoutEnvVar):
                raise
            report.update({'error': repr(ex)})
    return report

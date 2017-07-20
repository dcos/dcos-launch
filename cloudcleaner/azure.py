import collections
import logging
import os
from datetime import datetime, timedelta, timezone

from azure.common.credentials import ServicePrincipalCredentials
from azure.mgmt.resource.resources import ResourceManagementClient
from azure.mgmt.resource.resources.v2017_05_10.models.resource_group import ResourceGroup
from azure.monitor import MonitorClient

from cloudcleaner.common import (
    AbstractCleaner,
    CI_OWNER,
    delta_to_str,
    EXPIRE_WARNING_TIME,
    parse_delta)


def get_resource_mgmt_client():
    return ResourceManagementClient(ServicePrincipalCredentials(
        client_id=os.environ['AZURE_CLIENT_ID'],
        secret=os.environ['AZURE_CLIENT_SECRET'],
        tenant=os.environ['AZURE_TENANT_ID']), os.environ['AZURE_SUBSCRIPTION_ID'])


def get_monitor_client():
    return MonitorClient(ServicePrincipalCredentials(
        client_id=os.environ['AZURE_CLIENT_ID'],
        secret=os.environ['AZURE_CLIENT_SECRET'],
        tenant=os.environ['AZURE_TENANT_ID']), os.environ['AZURE_SUBSCRIPTION_ID'])


def tag_creation_time(resource_group: ResourceGroup):
    """Creation time is not natively tracked by azure, so look through the event log and find the
    farthest back time that shows the resource group being created (may potentially be the last
    time the resource group was updated). If no such time is found, then creation time is assumed
    to be the furthest bound of the log search (30 days ago)
    """
    logging.info('creation_time tag not found; scanning logs for {} creation'.format(resource_group.name))
    oldest_log_time = datetime.now(timezone.utc) - timedelta(days=30)  # logs can only be queried a month back
    log_filter = " and ".join([
        'eventTimestamp ge {}'.format(oldest_log_time.isoformat()),
        'eventChannels eq Operation',
        'resourceGroupName eq {}'.format(resource_group.name)])
    select = ','.join([
        'operationName',
        'eventTimestamp',
        'subStatus'])
    creation_time = None
    for event in get_monitor_client().activity_logs.list(filter=log_filter, select=select):
        if 'Update resource group' != event.operation_name.localized_value:
            continue
        if event.sub_status.value == 'Created':
            logging.info('Creation time found at {}'.format(event.event_timestamp.isoformat()))
            if creation_time is None or event.event_timestamp < creation_time:
                creation_time = event.event_timestamp
    if creation_time is None:
        creation_time = oldest_log_time
    logging.info('No creation time found in logs; setting creation time to {}'.format(creation_time.isoformat()))
    update_tags(get_resource_mgmt_client(), resource_group,
                {'creation_time': creation_time.replace(tzinfo=None).isoformat()})


def update_tags(rmc, resource_group: ResourceGroup, tags):
    """when a resource group is patched, is completely deletes
    all existing tags, thus read tags first
    """
    if resource_group.tags is None:
        resource_group.tags = dict()
    resource_group.tags.update(tags)
    rmc.resource_groups.patch(resource_group.name, {
        'tags': resource_group.tags,
        'location': resource_group.location}, raw=True)


def get_creation_time(resource_group: ResourceGroup):
    """ Extracts datetime object from creation_time tag within ResourceGoup"""
    try:
        return datetime.strptime(
            resource_group.tags['creation_time'], '%Y-%m-%dT%H:%M:%S.%f').replace(tzinfo=timezone.utc)
    except Exception as ex:
        raise ValueError('creation_time could not be parsed') from ex


def categorize_resource_group(resource_group: ResourceGroup, now, users):
    """ Puts resource groups into the following categories
    """
    categories = set()
    tags = resource_group.tags
    if tags is None:
        tags = {}

    if 'creation_time' not in tags:
        categories.add('needs_creation_time')
    else:
        try:
            uptime = now - get_creation_time(resource_group)
        except ValueError:
            categories.add('invalid_creation_time')

    if 'owner' in tags:
        if tags['owner'] not in users + [CI_OWNER]:
            categories.add('invalid_owner')
    else:
        categories.add('no_owner')

    # Check if tagged with an expiration. If not, mark to have one added
    if 'expiration' not in tags:
        categories.add('needs_expiration')
        return categories

    expiration_str = tags['expiration']
    if expiration_str == 'never':
        categories.add('never_expire')
        return categories

    # Has expiration passed?
    try:
        expiration = parse_delta(expiration_str)
    except ValueError:
        categories.add('invalid_expiration')
        return categories

    # expiration of zero minutes is probably invalid / unintentional.
    if expiration == timedelta():
        categories.add('invalid_expiration')
        return categories

    # need uptime here after, so return early
    if 'needs_creation_time' in categories or 'invalid_creation_time' in categories:
        return categories

    if uptime >= expiration:
        categories.add('expired')
    elif expiration - uptime <= EXPIRE_WARNING_TIME:
        categories.add('expire_soon')

    if len(categories) == 0:
        return {'ok'}

    return categories


def get_categorized_resource_groups(rmc, now, users):
    categorized = collections.defaultdict(list)

    for resource_group in rmc.resource_groups.list():
        try:
            categories = categorize_resource_group(resource_group, now, users)
        except Exception:
            logging.exception('Got an exception categorizing resource_group %s', resource_group.name)
            categories = ['error']
        for category in categories:
            categorized[category].append(resource_group)
        logging.info('Categorized {} as {}'.format(resource_group.name, str(categories)))

    return categorized


def take_resource_group_action(rmc, category, resource_group):
    """Azure does not instantaneously validate that operations can be performed,
    thus if a user does not have the authorization to delete a resource, that will not be
    reported until the poller completes
    """
    if category == 'error':
        return 'noop'

    if category in ['no_owner', 'invalid_owner']:
        add_tags = {'owner': CI_OWNER}
        if category == 'invalid_owner':
            # tag so that in case the owner gets feed back if the wrong handle was provided
            add_tags.update({'error_message': 'invalid owner was set'})
        update_tags(rmc, resource_group, add_tags)
        return 'owned_by_cloudcleaner'

    if category in ['needs_expiration', 'invalid_expiration']:
        update_tags(rmc, resource_group, {'expiration': '2h'})
        if category == 'invalid_expiration':
            update_tags(rmc, resource_group, {'message': 'Invalid / unparseable expiration. Reset to default.'})
        return 'add_expiration'

    if category in ['needs_creation_time', 'invalid_creation_time']:
        tag_creation_time(resource_group)
        return 'add_creation_time'

    if category == 'expired':
        delete_resource_group(rmc, resource_group.name)
        return 'deleted'

    return 'unknown_category'


def delete_resource_group(rmc, resource_group_name):
    """ Seperate function for threading and easy mocking
    """
    rmc.resource_groups.delete(resource_group_name, raw=True)


def perform_resource_group_actions(rmc, categorized_resource_groups):
    actions = collections.defaultdict(list)
    for category, resource_group_list in categorized_resource_groups.items():
        for resource_group in resource_group_list:
            try:
                taken = take_resource_group_action(
                    rmc=rmc,
                    category=category,
                    resource_group=resource_group)
            except Exception:
                logging.exception(
                    'Got an exception taking action for category %s on resource_group %s', category, resource_group)
                taken = 'error'
            actions[taken].append(resource_group)

    return actions


def resource_group_to_json(resource_group, now):
    """Convert an resource group to a json repot about it."""
    out = {
        'name': resource_group.name,
        'state': resource_group.properties.provisioning_state,
    }
    if resource_group.tags is not None:
        out.update({
            'creation_time': resource_group.tags.get('creation_time', 'unset'),
            'owner': resource_group.tags.get('owner', 'unset'),
            'expiration': resource_group.tags.get('expiration', 'unset')})
        if out['creation_time'] != 'unset':
            creation_datetime = get_creation_time(resource_group)
            out.update({'uptime': delta_to_str(now - creation_datetime)})
    return out


def make_json_report(now, categorized_resource_groups, resource_group_actions):
    """ Generate a json report which will get stored for future data analysis.
    Args:
        now: datetime.datetime object
        categorized_resource_groups: dict(str, list(ResourceGroup))
        resource_group_actions: dict(str, list(ResourceGroup))
    """
    json_report = {}

    json_report['categorized_resource_groups'] = {}
    for category, resource_group_list in categorized_resource_groups.items():
        json_report['categorized_resource_groups'][category] = [
            resource_group_to_json(rg, now) for rg in resource_group_list]

    json_report['resource_group_actions'] = {}
    for category, resource_group_list in resource_group_actions.items():
        json_report['resource_group_actions'][category] = [
            resource_group_to_json(rg, now) for rg in resource_group_list]

    return {'azure': json_report}


class AzureCleaner(AbstractCleaner):
    def __init__(self, now):
        super().__init__(now)
        self.rmc = get_resource_mgmt_client()

    def collect_resources(self, users):
        self.categorized_resource_groups = get_categorized_resource_groups(
            self.rmc, self.now, users)

    def clean_resources(self, dry_run, match_str):
        self.actions = perform_resource_group_actions(
            self.rmc, self.categorized_resource_groups)

    def make_report(self):
        return make_json_report(self.now, self.categorized_resource_groups, self.actions)

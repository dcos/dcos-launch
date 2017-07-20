import collections
import logging
from datetime import timedelta

import boto3
import botocore.exceptions

from cloudcleaner.common import (
    AbstractCleaner,
    check_test,
    delta_to_str,
    EXPIRE_WARNING_TIME,
    parse_delta)


aws_region_names = [
    {
        'name': 'US West (N. California)',
        'id': 'us-west-1'
    },
    {
        'name': 'US West (Oregon)',
        'id': 'us-west-2'
    },
    {
        'name': 'US East (N. Virginia)',
        'id': 'us-east-1'
    },
    {
        'name': 'South America (Sao Paulo)',
        'id': 'sa-east-1'
    },
    {
        'name': 'EU (Ireland)',
        'id': 'eu-west-1'
    },
    {
        'name': 'EU (Frankfurt)',
        'id': 'eu-central-1'
    },
    {
        'name': 'Asia Pacific (Tokyo)',
        'id': 'ap-northeast-1'
    },
    {
        'name': 'Asia Pacific (Singapore)',
        'id': 'ap-southeast-1'
    },
    {
        'name': 'Asia Pacific (Sydney)',
        'id': 'ap-southeast-2'
    },
    {
        'name': 'Asia Pacific (Seoul)',
        'id': 'ap-northeast-2'
    },
    {
        'name': 'Asia Pacific (Mumbai)',
        'id': 'ap-south-1'
    },
    {
        'name': 'US East (Ohio)',
        'id': 'us-east-2'
    }]


def get_service_resources(service, resource):
    """Return resources in every region for the given boto3 service and resource type."""
    check_test()

    for acct in [boto3.session.Session()]:
        for region in aws_region_names:
            for instance in getattr(acct.resource(service, region_name=region['id']), resource).all():
                yield instance


def get_instances():
    """Get all EC2 instances in all regions."""
    yield from get_service_resources('ec2', 'instances')


def get_keypairs():
    """Get all EC2 key pairs in all regions."""
    yield from get_service_resources('ec2', 'key_pairs')


def get_stacks():
    """Get all AWS CloudFormation stacks in all regions."""
    yield from get_service_resources('cloudformation', 'stacks')


def has_tag(instance, tag):
    """Find if an ec2 instance has a particular tag."""
    if instance.tags is None:
        return False
    return any(d['Key'] == tag for d in instance.tags)


def get_tag(instance, tag, default=None):
    """Get the tag by the current name from the ec2 tags, returning a defaul if not found."""
    if instance.tags is None:
        return False
    for d in instance.tags:
        if tag == d['Key']:
            return d['Value']
    return default


def add_tag(instance, tag, value, dry_run):
    """Add a tag to the given ec2 instance."""
    catch_aws_dryrun(instance.create_tags, Tags=[{'Key': tag, 'Value': value}], DryRun=dry_run)


def categorize_instance(instance, now, users):
    """Categorize an ec2 instance based on it's attributes."""
    state = instance.state['Name']

    if state == 'terminated':
        return 'terminated'

    # Ignore instances which are just starting or that are already stopping.
    if state in ['pending', 'shutting-down', 'stopping']:
        return 'changing_state'

    if state not in ['running', 'stopped']:
        return 'unknown_state'

    # Skip all ccm instances
    if has_tag(instance, 'aws:cloudformation:stack-id'):
        return 'ccm'

    # Ignore all instances less than 30 minutes old if they don't have an owner
    # and expiration. Not being tagged is just people not getting to it yet.
    # Billed by the hour for AWS anyways.
    uptime = now - instance.launch_time

    # While instances less than 30 minutes old may have owner, expiration we're
    # still going to consider them in the grace period, since a user could still
    # be editing typos post-launch.
    if uptime <= timedelta(minutes=30):
        return 'new'

    # Check if tagged with launcher. If not, kill with prejudice.
    if has_tag(instance, 'owner'):
        if get_tag(instance, 'owner') not in users:
            return 'invalid_owner'
    else:
        # Ownerless instances with an expiration that are stopped we let sit around
        # (they cost nothing) As a grace period.
        if not (state == 'stopped' and has_tag(instance, 'expiration')):
            return 'no_owner'

    # Check if tagged with an expiration. If not, mark to have one added
    if not has_tag(instance, 'expiration'):
        return 'needs_expiration'

    expiration_str = get_tag(instance, 'expiration')
    if expiration_str == 'never':
        return 'never_expire'

    # Has expiration passed?
    try:
        expiration = parse_delta(expiration_str)
    except ValueError:
        return 'invalid_expiration'

    # 0 minutes before expiration is probably invalid / unintentional.
    if expiration == timedelta():
        return 'invalid_expiration'

    if uptime >= expiration:
        return 'expired'

    if expiration - uptime <= EXPIRE_WARNING_TIME:
        if not has_tag(instance, 'owner'):
            return 'no_owner_stopped'
        else:
            return 'expire_soon'

    if not has_tag(instance, 'owner'):
        return 'no_owner_stopped'
    else:
        return 'ok'


def get_categorized_instances(now, users):
    """Categorize all ec2 instances using the given now timestamp and user list."""
    categorized = collections.defaultdict(list)

    for instance in get_instances():
        try:
            category = categorize_instance(instance, now, users)
        except Exception:
            logging.exception('Got an exception categorizing instance %s', instance)
            category = 'error'
        categorized[category].append(instance)
        print("Categorized", instance, "as", category)

    return categorized


def catch_aws_dryrun(func, *args, **kwargs):
    """TODO(cmaloney): This is a great big hack because AWS endpoints with boto3 when passed 'DryRun'.

    throw an exception which we need to catch and passify for proper operation. Should really make an
    "instance" class and EC2 is one implementation of it. Azure GCE should be alternate
    implementations of it.
    """
    if kwargs.get('DryRun') is not True:
        func(*args, **kwargs)
        return

    try:
        func(*args, **kwargs)
    except botocore.exceptions.ClientError as ex:
        if ex.response['Error'].get('Code') == "DryRunOperation":
            return
        raise


def set_expiration(instance, now, delta, dry_run):
    """Set an expiration time on an instance baed on how long it's already been running."""
    expiration_str = delta_to_str(now - instance.launch_time + delta)
    add_tag(instance, 'expiration', expiration_str, dry_run)


def take_instance_action(category, instance, now, dry_run):
    """Given a categoized instance, take some measurable action on it (terminate it, tag it, etc.)."""
    if category in ['error', 'ok', 'ccm', 'changing_state', 'new', 'terminated', 'unknown_state', 'no_owner_stopped',
                    'expire_soon']:
        return 'noop'
    if category in ['no_owner', 'invalid_owner']:
        # Stop and add a 23  hour 50 minute expiration from current time.
        catch_aws_dryrun(instance.stop, DryRun=dry_run)
        set_expiration(instance, now, timedelta(hours=24), dry_run)

        # For invalid owner also set a "message" tag to invalid_owner
        if category == 'invalid_owner':
            add_tag(instance, 'message', 'Owner does not exist in slack as a username', dry_run)

        return 'stop'

    if category in ['needs_expiration', 'invalid_expiration']:
        # Add a 50 min expiration from current time
        set_expiration(instance, now, timedelta(minutes=50), dry_run)

        if category == 'invalid_expiration':
            add_tag(instance, 'message', 'Invalid / unparseable expiration. Reset to default.', dry_run)

        return 'add_expire'

    if category == 'expired':
        catch_aws_dryrun(instance.terminate, DryRun=dry_run)
        return 'terminated'

    return 'unknown_category'


def take_keypair_action(keypair, match_str, stack_list, dry_run):
    """Take an action on a keypair and report what happened."""
    name = keypair.key_name
    if match_str and match_str in name and name not in stack_list:
        if not dry_run:
            keypair.delete()
        return 'delete'
    return 'noop'


def perform_keypair_actions(match_str, dry_run):
    """Categorize and take action on all keypairs in the AWS account.

    For all keypairs, if keypair name contains match_str
    and there is no such stack, then delete the keypair.
    """
    all_stacks = [stack.stack_name for stack in get_stacks()]
    actions = collections.defaultdict(list)
    for keypair in get_keypairs():
        try:
            taken = take_keypair_action(keypair, match_str, all_stacks, dry_run)
        except Exception:
            logging.exception('Got an exception while checking keypair %s', keypair)
            taken = 'error'
        actions[taken].append(keypair)

    return actions


def perform_instance_actions(categorized_instances, now, dry_run):
    """Take the categoized instances, and perform the currently needed actions on them."""
    actions = collections.defaultdict(list)
    for category, instance_list in categorized_instances.items():
        for instance in instance_list:
            try:
                taken = take_instance_action(
                    category=category,
                    instance=instance,
                    now=now,
                    dry_run=dry_run)
            except Exception:
                logging.exception('Got an exception taking action for category %s on instance %s', category, instance)
                taken = 'error'
            actions[taken].append(instance)

    return actions


def instance_to_json(instance, now):
    """Convert an ec2 instance to a json repot about it."""
    return {
        'id': instance.instance_id,
        'state': instance.state['Name'],
        'tags': dict(((tag['Key'], tag['Value']) for tag in instance.tags) if instance.tags else {}),
        'launch_time': instance.launch_time.isoformat(),
        'uptime': delta_to_str(now - instance.launch_time),
        'owner': get_tag(instance, 'owner'),
        'expiration': get_tag(instance, 'expiration') if has_tag(instance, 'expiration') else None,
        'instance_type': instance.instance_type
    }


def make_json_report(now, categorized_instances, instance_actions, keypair_actions):
    """ Generate a json report which will get stored for future data analysis.
    Args:
        now: datetime.datetime object
        categorized_instances: dict(str, list(ec2.Instance))
        instance_actions: dict(str, list(ec2.Instance))
        keypair_actions: dict(str, list(ec2.KeyPairInfo))
    """
    json_report = {}

    json_report['categorized_instances'] = {}
    for category, instance_list in categorized_instances.items():
        json_report['categorized_instances'][category] = [instance_to_json(i, now) for i in instance_list]

    json_report['instance_actions'] = {}
    for category, instance_list in instance_actions.items():
        json_report['instance_actions'][category] = [instance_to_json(i, now) for i in instance_list]

    json_report['keypair_actions'] = {}
    for category, key_list in keypair_actions.items():
        json_report['keypair_actions'][category] = [k.key_name for k in key_list]

    return {'aws': json_report}


class AwsCleaner(AbstractCleaner):

    def collect_resources(self, users):
        self.categorized_instances = get_categorized_instances(self.now, users)

    def clean_resources(self, dry_run, match_str):
        self.instance_actions = perform_instance_actions(
            self.categorized_instances, self.now, dry_run)
        self.keypair_actions = perform_keypair_actions(match_str, dry_run)

    def make_report(self):
        return make_json_report(
            self.now, self.categorized_instances, self.instance_actions, self.keypair_actions)

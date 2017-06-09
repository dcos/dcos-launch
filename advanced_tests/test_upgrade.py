"""

WARNGING: This is a destructive process and you cannot go back

=========================================================
This test has 4 input parameters (set in the environment)
=========================================================
Required:
  TEST_LAUNCH_CONFIG_PATH: path to a dcos-launch config for the cluster that will be upgraded.
      This cluster may or may not exist yet
  TEST_UPGRADE_INSTALLER_URL: The installer pulled from this URL will upgrade the aforementioned cluster.
Optional
  TEST_CREATE_CLUSTER: if set to `true`, a cluster will be created. Otherwise it will be assumed
      the provided launch config is a dcos-launch artifact
  TEST_UPGRADE_CONFIG_PATH: path to a YAML file for injecting parameters into the config to be
      used in generating the upgrade script
"""
import copy
import logging
import os
import pprint
import uuid

import pkg_resources

import dcos_test_utils.dcos_api_session
from dcos_test_utils import enterprise, helpers, upgrade
import pytest
import retrying
import yaml

log = logging.getLogger(__name__)

TEST_APP_NAME_FMT = 'upgrade-{}'


@pytest.fixture(scope='session')
def viplisten_app():
    return {
        "id": '/' + TEST_APP_NAME_FMT.format('viplisten-' + uuid.uuid4().hex),
        "cmd": '/usr/bin/nc -l -p $PORT0',
        "cpus": 0.1,
        "mem": 32,
        "instances": 1,
        "container": {
            "type": "MESOS",
            "docker": {
              "image": "alpine:3.5"
            }
        },
        'portDefinitions': [{
            'labels': {
                'VIP_0': '/viplisten:5000'
            }
        }],
        "healthChecks": [{
            "protocol": "COMMAND",
            "command": {
                "value": "/usr/bin/nslookup viplisten.marathon.l4lb.thisdcos.directory && pgrep -x /usr/bin/nc"
            },
            "gracePeriodSeconds": 300,
            "intervalSeconds": 60,
            "timeoutSeconds": 20,
            "maxConsecutiveFailures": 10
        }]
    }


@pytest.fixture(scope='session')
def viptalk_app():
    return {
        "id": '/' + TEST_APP_NAME_FMT.format('viptalk-' + uuid.uuid4().hex),
        "cmd": "/usr/bin/nc viplisten.marathon.l4lb.thisdcos.directory 5000 < /dev/zero",
        "cpus": 0.1,
        "mem": 32,
        "instances": 1,
        "container": {
            "type": "MESOS",
            "docker": {
              "image": "alpine:3.5"
            }
        },
        "healthChecks": [{
            "protocol": "COMMAND",
            "command": {
                "value": "pgrep -x /usr/bin/nc && sleep 5 && pgrep -x /usr/bin/nc"
            },
            "gracePeriodSeconds": 300,
            "intervalSeconds": 60,
            "timeoutSeconds": 20,
            "maxConsecutiveFailures": 10
        }]
    }


@pytest.fixture(scope='session')
def healthcheck_app():
    # HTTP healthcheck app to make sure tasks are reachable during the upgrade.
    # If a task fails its healthcheck, Marathon will terminate it and we'll
    # notice it was killed when we check tasks on exit.
    return {
        "id": '/' + TEST_APP_NAME_FMT.format('healthcheck-' + uuid.uuid4().hex),
        "cmd": "python3 -m http.server 8080",
        "cpus": 0.5,
        "mem": 32.0,
        "instances": 1,
        "container": {
            "type": "DOCKER",
            "docker": {
                "image": "python:3",
                "network": "BRIDGE",
                "portMappings": [
                    {"containerPort": 8080, "hostPort": 0}
                ]
            }
        },
        "healthChecks": [
            {
                "protocol": "HTTP",
                "path": "/",
                "portIndex": 0,
                "gracePeriodSeconds": 5,
                "intervalSeconds": 1,
                "timeoutSeconds": 5,
                "maxConsecutiveFailures": 1
            }
        ],
    }


@pytest.fixture(scope='session')
def dns_app(healthcheck_app):
    # DNS resolution app to make sure DNS is available during the upgrade.
    # Periodically resolves the healthcheck app's domain name and logs whether
    # it succeeded to a file in the Mesos sandbox.
    healthcheck_app_id = healthcheck_app['id'].lstrip('/')
    return {
        "id": '/' + TEST_APP_NAME_FMT.format('dns-' + uuid.uuid4().hex),
        "cmd": """
while true
do
    printf "%s " $(date --utc -Iseconds) >> $MESOS_SANDBOX/$DNS_LOG_FILENAME
    if host -W $TIMEOUT_SECONDS $RESOLVE_NAME
    then
        echo SUCCESS >> $MESOS_SANDBOX/$DNS_LOG_FILENAME
    else
        echo FAILURE >> $MESOS_SANDBOX/$DNS_LOG_FILENAME
    fi
    sleep $INTERVAL_SECONDS
done
""",
        "env": {
            'RESOLVE_NAME': helpers.marathon_app_id_to_mesos_dns_subdomain(healthcheck_app_id) + '.marathon.mesos',
            'DNS_LOG_FILENAME': 'dns_resolve_log.txt',
            'INTERVAL_SECONDS': '1',
            'TIMEOUT_SECONDS': '1',
        },
        "cpus": 0.5,
        "mem": 32.0,
        "instances": 1,
        "container": {
            "type": "DOCKER",
            "docker": {
                "image": "branden/bind-utils",
                "network": "BRIDGE",
            }
        },
        "dependencies": [healthcheck_app_id],
    }


@pytest.fixture(scope='session')
def onprem_cluster(launcher):
    if launcher.config['provider'] != 'onprem':
        pytest.skip('Only onprem provider is supported for upgrades!')
    return launcher.get_onprem_cluster()


@pytest.fixture(scope='session')
def is_enterprise():
    return os.getenv('TEST_UPGRADE_ENTERPRISE', 'false') == 'true'


@pytest.fixture(scope='session')
def dcos_api_session(onprem_cluster, launcher, is_enterprise):
    """ The API session for the cluster at the beginning of the upgrade
    This will be used to start tasks and poll the metrics snapshot endpoint
    """
    return make_dcos_api_session(
        onprem_cluster, launcher, is_enterprise, launcher.config['dcos_config'].get('security'))


def make_dcos_api_session(onprem_cluster, launcher, is_enterprise: bool=False, security_mode=None):
    ssl_enabled = security_mode in ('strict', 'permissive')
    args = {
        'dcos_url': 'http://' + onprem_cluster.masters[0].public_ip,
        'masters': [m.public_ip for m in onprem_cluster.masters],
        'slaves': [m.public_ip for m in onprem_cluster.private_agents],
        'public_slaves': [m.public_ip for m in onprem_cluster.public_agents],
        'default_os_user': 'root',
        'auth_user': dcos_test_utils.dcos_api_session.DcosUser(helpers.CI_CREDENTIALS),
        'exhibitor_admin_password': launcher.config['dcos_config'].get('exhibitor_admin_password')}

    if is_enterprise:
        api_class = enterprise.EnterpriseApiSession
        args['auth_user'] = enterprise.EnterpriseUser(
            os.getenv('DCOS_LOGIN_UNAME', 'testadmin'),
            os.getenv('DCOS_LOGIN_PW', 'testpassword'))
        if ssl_enabled:
            args['dcos_url'] = args['dcos_url'].replace('http', 'https')
        if security_mode == 'strict':
            args['default_os_user'] = 'nobody'
    else:
        api_class = dcos_test_utils.dcos_api_session.DcosApiSession

    return api_class(**args)


@retrying.retry(
    wait_fixed=(1 * 1000),
    stop_max_delay=(120 * 1000),
    retry_on_result=lambda x: not x)
def wait_for_dns(dcos_api, hostname):
    """Return True if Mesos-DNS has at least one entry for hostname."""
    hosts = dcos_api.get('/mesos_dns/v1/hosts/' + hostname).json()
    return any(h['host'] != '' and h['ip'] != '' for h in hosts)


def get_master_task_state(dcos_api, task_id):
    """Returns the JSON blob associated with the task from /master/state."""
    response = dcos_api.get('/mesos/master/state')
    response.raise_for_status()
    master_state = response.json()

    for framework in master_state['frameworks']:
        for task in framework['tasks']:
            if task_id in task['id']:
                return task


def app_task_ids(dcos_api, app_id):
    """Return a list of Mesos task IDs for app_id's running tasks."""
    assert app_id.startswith('/')
    response = dcos_api.marathon.get('/v2/apps' + app_id + '/tasks')
    response.raise_for_status()
    tasks = response.json()['tasks']
    return [task['id'] for task in tasks]


def parse_dns_log(dns_log_content):
    """Return a list of (timestamp, status) tuples from dns_log_content."""
    dns_log = [line.strip().split(' ') for line in dns_log_content.strip().split('\n')]
    if any(len(entry) != 2 or entry[1] not in ['SUCCESS', 'FAILURE'] for entry in dns_log):
        message = 'Malformed DNS log.'
        log.debug(message + ' DNS log content:\n' + dns_log_content)
        raise Exception(message)
    return dns_log


@pytest.fixture(scope='session')
def setup_workload(dcos_api_session, viptalk_app, viplisten_app, healthcheck_app, dns_app):
    if dcos_api_session.default_url.scheme == 'https':
        dcos_api_session.set_ca_cert()
    dcos_api_session.wait_for_dcos()
    # TODO(branden): We ought to be able to deploy these apps concurrently. See
    # https://mesosphere.atlassian.net/browse/DCOS-13360.
    dcos_api_session.marathon.deploy_app(viplisten_app)
    dcos_api_session.marathon.ensure_deployments_complete()
    # viptalk app depends on VIP from viplisten app, which may still fail
    # the first try immediately after ensure_deployments_complete
    dcos_api_session.marathon.deploy_app(viptalk_app, ignore_failed_tasks=True)
    dcos_api_session.marathon.ensure_deployments_complete()

    dcos_api_session.marathon.deploy_app(healthcheck_app)
    dcos_api_session.marathon.ensure_deployments_complete()
    # This is a hack to make sure we don't deploy dns_app before the name it's
    # trying to resolve is available.
    wait_for_dns(dcos_api_session, dns_app['env']['RESOLVE_NAME'])
    dcos_api_session.marathon.deploy_app(dns_app, check_health=False)
    dcos_api_session.marathon.ensure_deployments_complete()

    test_apps = [healthcheck_app, dns_app, viplisten_app, viptalk_app]
    test_app_ids = [app['id'] for app in test_apps]

    tasks_start = {app_id: sorted(app_task_ids(dcos_api_session, app_id)) for app_id in test_app_ids}
    log.debug('Test app tasks at start:\n' + pprint.pformat(tasks_start))

    for app in test_apps:
        assert app['instances'] == len(tasks_start[app['id']])

    # Save the master's state of the task to compare with
    # the master's view after the upgrade.
    # See this issue for why we check for a difference:
    # https://issues.apache.org/jira/browse/MESOS-1718
    task_state_start = get_master_task_state(dcos_api_session, tasks_start[test_app_ids[0]][0])
    return test_app_ids, tasks_start, task_state_start


@pytest.fixture(scope='session')
def upgraded_dcos(dcos_api_session, launcher, setup_workload, onprem_cluster, is_enterprise):
    """ This test is intended to test upgrades between versions so use
    the same config as the original launch
    """
    # Check for previous installation artifacts first
    bootstrap_host = onprem_cluster.bootstrap_host.public_ip
    upgrade.reset_bootstrap_host(onprem_cluster.ssh_client, bootstrap_host)

    upgrade_config_overrides = dict()
    if 'TEST_UPGRADE_CONFIG_PATH' in os.environ:
        with open(os.environ['TEST_UPGRADE_CONFIG_PATH'], 'r') as f:
            upgrade_config_overrides = yaml.load(f.read())

    upgrade_config = copy.copy(launcher.config['dcos_config'])

    upgrade_config.update({
        'cluster_name': 'My Upgraded DC/OS',
        'ssh_user': onprem_cluster.ssh_client.user,  # can probably drop this field
        'bootstrap_url': 'http://' + onprem_cluster.bootstrap_host.private_ip,
        'master_list': [h.private_ip for h in onprem_cluster.masters],
        'agent_list': [h.private_ip for h in onprem_cluster.private_agents],
        'public_agent_list': [h.private_ip for h in onprem_cluster.public_agents]})
    upgrade_config.update(upgrade_config_overrides)
    # if it was a ZK-backed install, make sure ZK is still running
    if upgrade_config.get('exhibitor_storage_backend') == 'zookeeper':
        upgrade_config['exhibitor_zk_hosts'] = onprem_cluster.start_bootstrap_zk()
    # if IP detect public was not present, go ahead an inject it
    if 'ip_detect_public_contents' not in upgrade_config:
        upgrade_config['ip_detect_public_contents'] = yaml.dump(pkg_resources.resource_string(
            'dcos_test_utils', 'ip-detect/aws_public.sh').decode())

    bootstrap_home = onprem_cluster.ssh_client.get_home_dir(bootstrap_host)
    genconf_dir = os.path.join(bootstrap_home, 'genconf')
    with onprem_cluster.ssh_client.tunnel(bootstrap_host) as tunnel:
        log.info('Setting up upgrade config on bootstrap host')
        tunnel.command(['mkdir', genconf_dir])
        # transfer the config file
        tunnel.copy_file(
            helpers.session_tempfile(yaml.dump(upgrade_config).encode()),
            os.path.join(bootstrap_home, 'genconf/config.yaml'))
        # FIXME: we dont need the ssh key when the upgrade isnt being orchestratd
        tunnel.copy_file(
            helpers.session_tempfile(onprem_cluster.ssh_client.key.encode()),
            os.path.join(bootstrap_home, 'genconf/ssh_key'))
        tunnel.command(['chmod', '600', os.path.join(bootstrap_home, 'genconf/ssh_key')])
        # Move the ip-detect script to the expected default path
        # FIXME: can we just send the contents in the config and skip this?
        tunnel.copy_file(
            pkg_resources.resource_filename('dcos_test_utils', 'ip-detect/aws.sh'),
            os.path.join(bootstrap_home, 'genconf/ip-detect'))

    # API object may need to be updated
    upgrade_session = make_dcos_api_session(
        onprem_cluster,
        launcher,
        is_enterprise,
        upgrade_config_overrides.get('security'))

    # use the Auth session from the previous API session
    upgrade_session.session.auth = dcos_api_session.session.auth

    # do the actual upgrade
    upgrade.upgrade_dcos(
        upgrade_session,
        onprem_cluster,
        dcos_api_session.get_version(),
        os.environ['TEST_UPGRADE_INSTALLER_URL'])

    # this can be set after the fact because the upgrade metrics snapshot
    # endpoint is polled with verify=False
    if upgrade_session.default_url.scheme == 'https':
        upgrade_session.set_ca_cert()

    # Now Re-auth with the new session
    upgrade_session.wait_for_dcos()
    return upgrade_session


@pytest.mark.skipif(
    'TEST_UPGRADE_INSTALLER_URL' not in os.environ,
    reason='TEST_UPGRADE_INSTALLER_URL must be set in env to upgrade a cluster')
class TestUpgrade:
    @pytest.mark.xfail
    def test_marathon_app_tasks_survive(self, upgraded_dcos, setup_workload):
        test_app_ids, tasks_start, _ = setup_workload
        tasks_end = {app_id: sorted(app_task_ids(upgraded_dcos, app_id)) for app_id in test_app_ids}
        log.debug('Test app tasks at end:\n' + pprint.pformat(tasks_end))
        assert tasks_start == tasks_end

    def test_mesos_task_state_remains_consistent(self, upgraded_dcos, setup_workload):
        test_app_ids, tasks_start, task_state_start = setup_workload
        task_state_end = get_master_task_state(upgraded_dcos, tasks_start[test_app_ids[0]][0])
        assert all(item in task_state_end.items() for item in task_state_start.items())

    @pytest.mark.xfail
    def test_app_dns_survive(self, upgraded_dcos, dns_app):
        marathon_framework_id = upgraded_dcos.marathon.get('/v2/info').json()['frameworkId']
        dns_app_task = upgraded_dcos.marathon.get('/v2/apps' + dns_app['id'] + '/tasks').json()['tasks'][0]
        dns_log = parse_dns_log(upgraded_dcos.mesos_sandbox_file(
            dns_app_task['slaveId'],
            marathon_framework_id,
            dns_app_task['id'],
            dns_app['env']['DNS_LOG_FILENAME']))
        dns_failure_times = [entry[0] for entry in dns_log if entry[1] != 'SUCCESS']
        assert len(dns_failure_times) == 0, 'Failed to resolve Marathon app hostname {hostname} at least once' \
            'Hostname failed to resolve at these times:\n{failures}'.format(
                hostname=dns_app['env']['RESOLVE_NAME'],
                failures='\n'.join(dns_failure_times))

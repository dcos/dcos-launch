""" Steps:
Setup:
- Input launch config (or launch info for clusters that already exist)
- Launch cluster if it does not exist
- Input target installer artifact
- Optionally provide path to config add-ins

Setup the cluster workload

Upgrade the cluster using launch config to identify bootstrap nodes, ssh user, and ssh key

Check the cluster workload
"""
import json
import logging
import os
import pprint
import random
import uuid

import dcos_launch
import dcos_launch.config
import dcos_test_utils
import dcos_test_utils.dcos_api_session
import pkg_resources
import pytest
import retrying
import yaml
from dcos_test_utils.helpers import CI_CREDENTIALS, marathon_app_id_to_mesos_dns_subdomain, session_tempfile

logging.basicConfig(format='[%(asctime)s|%(name)s|%(levelname)s]: %(message)s', level=logging.DEBUG)
log = logging.getLogger(__name__)

TEST_APP_NAME_FMT = 'upgrade-{}'


@retrying.retry(
    wait_fixed=1000 * 10,
    retry_on_result=lambda result: result is False)
def wait_for_mesos_metric(cluster, host, key, value):
    """Return True when host's Mesos metric key is equal to value."""
    if host in cluster.masters:
        port = 5050
    else:
        port = 5051
    response = cluster.get('/metrics/snapshot', host=host, port=port)
    return response.json().get(key) == value


def upgrade_dcos(
        dcos_api_session: dcos_test_utils.dcos_api_session.DcosApiSession,
        onprem_cluster: dcos_test_utils.onprem.OnpremCluster,
        installer_url: str,
        user_config: dict,
        platform: str):
    assert platform == 'aws', 'AWS is the only supported platform backend currently'

    ssh_client = onprem_cluster.ssh_client
    version = dcos_api_session.get_version()

    # kill previous genconf on bootstrap host if it is still running
    bootstrap_host = onprem_cluster.bootstrap_host.public_ip
    log.info('Killing any previous installer before starting upgrade')
    previous_installer = ssh_client.command(
        bootstrap_host,
        ['docker', 'ps', '--quiet', '--filter', 'name=dcos-genconf', '--filter', 'status=running']).decode().strip()
    if previous_installer:
        ssh_client.command(
            bootstrap_host,
            ['docker', 'kill', previous_installer])

    bootstrap_home = ssh_client.get_home_dir(bootstrap_host)

    log.info('Clearing out old installation files')
    genconf_dir = os.path.join(bootstrap_home, 'genconf')
    ssh_client.command(bootstrap_host, ['sudo', 'rm', '-rf', genconf_dir])
    ssh_client.command(bootstrap_host, ['mkdir', genconf_dir])
    installer_path = os.path.join(bootstrap_home, 'dcos_generate_config.sh')
    dcos_test_utils.onprem.download_dcos_installer(ssh_client, bootstrap_host, installer_path, installer_url)

    log.info('Starting ZooKeeper on the bootstrap node')
    zk_host = onprem_cluster.start_bootstrap_zk()
    # start the nginx that will host the bootstrap files
    bootstrap_url = 'http://' + onprem_cluster.start_bootstrap_nginx()

    with ssh_client.tunnel(bootstrap_host) as tunnel:
        log.info('Setting up upgrade config on bootstrap host')
        upgrade_config = {
            'cluster_name': 'My Upgraded DC/OS',
            'ssh_user': ssh_client.user,
            'master_discovery': 'static',
            'exhibitor_storage_backend': 'zookeeper',
            'exhibitor_zk_hosts': zk_host,
            'exhibitor_zk_path': '/exhibitor',
            'bootstrap_url': bootstrap_url,
            'rexray_config_reset': platform,
            'platform': platform,
            'master_list': [h.private_ip for h in onprem_cluster.masters],
            'agent_list': [h.private_ip for h in onprem_cluster.private_agents],
            'public_agent_list': [h.private_ip for h in onprem_cluster.public_agents]}
        upgrade_config.update(user_config)

        # transfer ip-detect and ssh key
        tunnel.copy_file(
            session_tempfile(
                yaml.dump(upgrade_config).encode()), os.path.join(bootstrap_home, 'genconf/config.yaml'))
        tunnel.copy_file(
            session_tempfile(
                ssh_client.key.encode()), os.path.join(bootstrap_home, 'genconf/ssh_key'))
        tunnel.command(['chmod', '600', os.path.join(bootstrap_home, 'genconf/ssh_key')])
        ip_detect_script = pkg_resources.resource_string(
            'dcos_launch', 'ip-detect/{}.sh'.format(platform)).decode('utf-8')
        tunnel.copy_file(session_tempfile(ip_detect_script.encode()), os.path.join(bootstrap_home, 'genconf/ip-detect'))

        log.info('Generating node upgrade script')
        upgrade_script_path = tunnel.command(
            ['bash', installer_path, '--generate-node-upgrade-script ' + version]
        ).decode('utf-8').splitlines()[-1].split("Node upgrade script URL: ", 1)[1]

        log.info('Editing node upgrade script...')
        # Remove docker (and associated journald) restart from the install
        # script. This prevents Docker-containerized tasks from being killed
        # during agent upgrades.
        tunnel.command([
            'sudo', 'sed', '-i',
            '-e', '"s/systemctl restart systemd-journald//g"',
            '-e', '"s/systemctl restart docker//g"',
            bootstrap_home + '/genconf/serve/dcos_install.sh'])
        tunnel.command(['docker', 'restart', 'dcos-bootstrap-nginx'])
    # upgrading can finally start
    master_list = [host.public_ip for host in onprem_cluster.masters]
    private_agent_list = [host.public_ip for host in onprem_cluster.private_agents]
    public_agent_list = [host.public_ip for host in onprem_cluster.public_agents]
    upgrade_ordering = [
        # Upgrade masters in a random order.
        ('master', 'master', random.sample(master_list, len(master_list))),
        ('slave', 'agent', private_agent_list),
        ('slave_public', 'public agent', public_agent_list)]
    logging.info('\n'.join(
        ['Upgrade plan:'] +
        ['{} ({})'.format(host, role_name) for _, role_name, hosts in upgrade_ordering for host in hosts]
    ))
    for role, role_name, hosts in upgrade_ordering:
        log.info('Upgrading {} nodes: {}'.format(role_name, repr(hosts)))
        for host in hosts:
            log.info('Upgrading {}: {}'.format(role_name, repr(host)))
            ssh_client.command(
                host,
                [
                    'curl',
                    '--silent',
                    '--verbose',
                    '--show-error',
                    '--fail',
                    '--location',
                    '--keepalive-time', '2',
                    '--retry', '20',
                    '--speed-limit', '100000',
                    '--speed-time', '60',
                    '--remote-name', upgrade_script_path])
            ssh_client.command(host, ['sudo', 'bash', 'dcos_node_upgrade.sh'])
            wait_metric = {
                'master': 'registrar/log/recovered',
                'slave': 'slave/registered',
                'slave_public': 'slave/registered',
            }[role]
            log.info('Waiting for {} to rejoin the cluster...'.format(role_name))
            try:
                wait_for_mesos_metric(dcos_api_session, host, wait_metric, 1)
            except retrying.RetryError as exc:
                raise Exception(
                    'Timed out waiting for {} to rejoin the cluster after upgrade: {}'.
                    format(role_name, repr(host))
                ) from exc
    dcos_api_session.wait_for_dcos()


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
            "maxConsecutiveFailures": 3
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
            "maxConsecutiveFailures": 3
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
            'RESOLVE_NAME': marathon_app_id_to_mesos_dns_subdomain(healthcheck_app_id) + '.marathon.mesos',
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
def launcher():
    assert 'TEST_UPGRADE_LAUNCH_CONFIG_PATH' in os.environ
    return dcos_launch.get_launcher(
        dcos_launch.config.get_validated_config(os.environ['TEST_UPGRADE_LAUNCH_CONFIG_PATH'], strict=False))


@pytest.fixture(scope='session')
def onprem_cluster(launcher, installer_url):
    # installer_url is not a required fixture but it is used to ensure that the launcher is not
    # created when an installer target has not even been specified
    assert launcher.config['provider'] == 'onprem', 'Only onprem provider is supported for upgrades!'
    if os.environ.get('TEST_UPGRADE_CREATE_CLUSTER') == 'true':
        info = launcher.create()
        with open('upgrade_test_info.json', 'w') as f:
            json.dump(info, f)
        launcher.wait()
    else:
        try:
            launcher.wait()
        except dcos_launch.util.LauncherError:
            raise AssertionError(
                'Cluster creation was not specified with TEST_UPGRADE_CREATE_CLUSTER, yet launcher '
                'cannot reach the speficied cluster')
    cluster = launcher.get_onprem_cluster()
    return cluster


@pytest.fixture(scope='session')
def dcos_api_session(onprem_cluster, launcher):
    session = dcos_test_utils.dcos_api_session.DcosApiSession(
        'http://' + onprem_cluster.masters[0].public_ip,
        [m.public_ip for m in onprem_cluster.masters],
        [m.public_ip for m in onprem_cluster.private_agents],
        [m.public_ip for m in onprem_cluster.public_agents],
        'root',
        dcos_test_utils.dcos_api_session.DcosUser(CI_CREDENTIALS),
        exhibitor_admin_password=launcher.config.get('dcos_config').get('exhibitor_admin_password'))
    session.wait_for_dcos()
    return session


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
def installer_url():
    assert 'TEST_UPGRADE_INSTALLER_URL' in os.environ
    return os.environ['TEST_UPGRADE_INSTALLER_URL']


@pytest.fixture(scope='session')
def upgrade_user_config():
    if 'TEST_UPGRADE_DCOS_CONFIG_PATH' in os.environ:
        with open(os.environ['TEST_UPGRADE_DCOS_CONFIG_PATH'], 'r') as f:
            return yaml.load(f.read())
    else:
        return {}


@pytest.fixture(scope='session')
def upgraded_dcos(dcos_api_session, launcher, setup_workload, onprem_cluster, installer_url, upgrade_user_config):
    upgrade_dcos(
        dcos_api_session,
        onprem_cluster,
        installer_url,
        upgrade_user_config,
        launcher.config['platform'])


@pytest.mark.usefixtures('upgraded_dcos')
@pytest.mark.skipif(
    'TEST_UPGRADE_INSTALLER_URL' not in os.environ or 'TEST_UPGRADE_DCOS_CONFIG_PATH' not in os.environ,
    reason='This test must have targets specified to be run!')
class TestUpgrade:
    def test_marathon_app_tasks_survive(self, dcos_api_session, setup_workload):
        tasks_end = {app_id: sorted(app_task_ids(dcos_api_session, app_id)) for app_id in setup_workload[0]}
        log.debug('Test app tasks at end:\n' + pprint.pformat(tasks_end))
        assert setup_workload[1] == tasks_end

    def test_mesos_task_state_remains_consistent(self, dcos_api_session, setup_workload):
        task_state_end = self.get_master_task_state(dcos_api_session, self.tasks_start[self.test_app_ids[0]][0])
        assert setup_workload[2] == task_state_end

    def test_app_dns_survive(self, dcos_api_session, dns_app):
        marathon_framework_id = dcos_api_session.marathon.get('/v2/info').json()['frameworkId']
        dns_app_task = dcos_api_session.marathon.get('/v2/apps' + dns_app['id'] + '/tasks').json()['tasks'][0]
        dns_log = parse_dns_log(dcos_api_session.mesos_sandbox_file(
            dns_app_task['slaveId'],
            marathon_framework_id,
            dns_app_task['id'],
            dns_app['env']['DNS_LOG_FILENAME']))
        dns_failure_times = [entry[0] for entry in dns_log if entry[1] != 'SUCCESS']
        assert len(dns_failure_times) == 0, 'Failed to resolve Marathon app hostname {hostname} at least once' \
            'Hostname failed to resolve at these times:\n{failures}'.format(
                hostname=dns_app['env']['RESOLVE_NAME'],
                failures='\n'.join(dns_failure_times))

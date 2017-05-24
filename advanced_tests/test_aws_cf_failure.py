import logging
import json
import os

import pytest
import requests
import retrying

import dcos_launch
import dcos_test_utils.arm
import dcos_test_utils.helpers
from dcos_test_utils.helpers import CI_CREDENTIALS, retry_boto_rate_limits

log = logging.getLogger(__name__)


def wait_for_pong(url, timeout):
    """continually GETs /ping expecting JSON pong:true return
    Does not stop on exception as connection error may be expected
    """
    @retrying.retry(wait_fixed=3000, stop_max_delay=timeout * 1000)
    def ping_app():
        log.info('Attempting to ping test application')
        r = requests.get('http://{}/ping'.format(url), timeout=10)
        r.raise_for_status()
        assert r.json() == {"pong": True}, 'Unexpected response from server: ' + repr(r.json())
    ping_app()


@pytest.fixture(scope='session')
def launcher():
    launcher = dcos_launch.get_launcher(
        dcos_launch.config.get_validated_config(os.environ['TEST_UPGRADE_LAUNCH_CONFIG_PATH'], strict=False))
    assert launcher.config['provider'] == 'aws', 'Only aws provider is supports automatically respawning agents!'
    if os.environ.get('TEST_AGENT_FAILURE_CREATE_CLUSTER') == 'true':
        info = launcher.create()
        with open('agent_failure_test_info.json', 'w') as f:
            json.dump(info, f)
        launcher.wait()
    else:
        try:
            launcher.wait()
        except dcos_launch.util.LauncherError:
            raise AssertionError(
                'Cluster creation was not specified with TEST_UPGRADE_CREATE_CLUSTER, yet launcher '
                'cannot reach the speficied cluster')
    return launcher


@pytest.fixture(scope='session')
def dcos_api_session(onprem_cluster, launcher):
    description = launcher.describe()
    session = dcos_test_utils.dcos_api_session.DcosApiSession(
        'http://' + description['masters'][0].public_ip,
        [m.private_ip for m in description['masters']],
        [m.private_ip for m in description['private_agents']],
        [m.private_ip for m in description['public_agents']],
        'root',
        dcos_test_utils.dcos_api_session.DcosUser(CI_CREDENTIALS))
    session.wait_for_dcos()
    return session


@pytest.fixture
def vip_apps(dcos_api_session):
    vip1 = '6.6.6.1:6661'
    test_app1, _ = dcos_test_utils.marathon.get_test_app(vip=vip1)
    name = 'myvipapp'
    port = 5432
    test_app2, _ = dcos_test_utils.marathon.get_test_app(vip='{}:{}'.format(name, port))
    vip2 = '{}.marathon.l4lb.thisdcos.directory:{}'.format(name, port)
    with dcos_api_session.marathon.deploy_and_cleanup(test_app1):
        with dcos_api_session.marathon.deploy_and_cleanup(test_app2):
            yield ((test_app1, vip1), (test_app2, vip2))


@pytest.mark.skipif
def test_agent_failure(launcher, dcos_api_session, vip_apps):
    # Accessing AWS Resource objects will trigger a client describe call.
    # As such, any method that touches AWS APIs must be wrapped to avoid
    # CI collapse when rate limits are inevitably reached
    @retry_boto_rate_limits
    def get_running_instances(instance_iter):
        return [i for i in instance_iter if i.state['Name'] == 'running']

    @retry_boto_rate_limits
    def get_instance_ids(instance_iter):
        return [i.instance_id for i in instance_iter]

    @retry_boto_rate_limits
    def get_private_ips(instance_iter):
        return sorted([i.private_ip_address for i in get_running_instances(instance_iter)])

    # make sure the app works before starting
    wait_for_pong(vip_apps[0][1], 120)
    wait_for_pong(vip_apps[1][1], 10)
    agent_ids = get_instance_ids(
        get_running_instances(launcher.stack.public_agent_instances) +
        get_running_instances(launcher.private_agent_instances))

    # Agents are in auto-scaling groups, so they will automatically be replaced
    launcher.boto_wrapper.client('ec2').terminate_instances(InstanceIds=agent_ids)
    waiter = launcher.boto_wrapper.client('ec2').get_waiter('instance_terminated')
    retry_boto_rate_limits(waiter.wait)(InstanceIds=agent_ids)

    # Tell mesos the machines are "down" and not coming up so things get rescheduled.
    down_hosts = [{'hostname': slave, 'ip': slave} for slave in dcos_api_session.all_slaves]
    dcos_api_session.post(
        '/mesos/maintenance/schedule',
        json={'windows': [{
            'machine_ids': down_hosts,
            'unavailability': {'start': {'nanoseconds': 0}}
        }]}).raise_for_status()
    dcos_api_session.post('/mesos/machine/down', json=down_hosts).raise_for_status()

    public_agent_count = len(dcos_api_session.public_slaves)
    private_agent_count = len(dcos_api_session.slaves)

    @retrying.retry(
        wait_fixed=60 * 1000,
        retry_on_result=lambda res: res is False,
        stop_max_delay=900 * 1000)
    def wait_for_agents_to_refresh():
        public_agents = get_running_instances(launcher.stack.public_agent_instances)
        if len(public_agents) == public_agent_count:
            dcos_api_session.public_slave_list = get_private_ips(public_agents)
        else:
            log.info('Waiting for {} public agents. Current: {}'.format(
                     public_agent_count, len(public_agents)))
            return False
        private_agents = get_running_instances(launcher.stack.private_agent_instances)
        if len(private_agents) == private_agent_count:
            dcos_api_session.slave_list = get_private_ips(private_agents)
        else:
            log.info('Waiting for {} private agents. Current: {}'.format(
                     private_agent_count, len(private_agents)))
            return False

    wait_for_agents_to_refresh()

    # verify that everything else is still working
    dcos_api_session.wait_for_dcos()
    # finally verify that the app is again running somewhere with its VIPs
    # Give marathon five minutes to deploy both the apps
    wait_for_pong(vip_apps[0][1], 300)
    wait_for_pong(vip_apps[1][1], 10)

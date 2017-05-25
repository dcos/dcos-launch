import json
import logging
import os

import pytest
import retrying
import yaml

import dcos_test_utils.helpers
import dcos_test_utils.dcos_api_session
import dcos_test_utils.marathon

log = logging.getLogger(__name__)


@retrying.retry(wait_fixed=10 * 1000)
def wait_for_pong(tunnel: dcos_test_utils.ssh_client.Tunnelled, url):
    """continually GETs /ping expecting JSON pong:true return
    Does not stop on exception as connection error may be expected
    """
    log.info('Attempting to ping test application')
    out = tunnel.command(['curl', '--fail', '--location', 'http://{}/ping'.format(url)]).decode()
    log.info('curl response: ' + out)
    assert json.loads(out) == {"pong": True}
    log.info('Ping successful!')


@pytest.fixture(scope='session')
def dcos_api_session(launcher):
    if launcher.config['provider'] != 'aws':
        pytest.skip('This test can only run on AWS')
    description = launcher.describe()
    session = dcos_test_utils.dcos_api_session.DcosApiSession(
        'http://' + description['masters'][0]['public_ip'],
        [m['public_ip'] for m in description['masters']],
        [m['private_ip'] for m in description['private_agents']],
        [m['private_ip'] for m in description['public_agents']],
        'root',
        dcos_test_utils.dcos_api_session.DcosUser(dcos_test_utils.helpers.CI_CREDENTIALS))
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


def can_provide_aws():
    launch_config_path = os.getenv('TEST_LAUNCH_CONFIG_PATH')
    if launch_config_path:
        with open(launch_config_path, 'r') as f:
            return yaml.load(f).get('provider') == 'aws'
    return False


@pytest.mark.skipif(not can_provide_aws(), reason='This test must run on an AWS-provided cluster')
def test_agent_failure(launcher, dcos_api_session, vip_apps):
    # Accessing AWS Resource objects will trigger a client describe call.
    # As such, any method that touches AWS APIs must be wrapped to avoid
    # CI collapse when rate limits are inevitably reached
    @dcos_test_utils.helpers.retry_boto_rate_limits
    def get_running_instances(instance_iter):
        return [i for i in instance_iter if i.state['Name'] == 'running']

    @dcos_test_utils.helpers.retry_boto_rate_limits
    def get_instance_ids(instance_iter):
        return [i.instance_id for i in instance_iter]

    @dcos_test_utils.helpers.retry_boto_rate_limits
    def get_private_ips(instance_iter):
        return sorted([i.private_ip_address for i in get_running_instances(instance_iter)])

    ssh_client = launcher.get_ssh_client()

    # make sure the app works before starting
    log.info('Waiting for VIPs to be routable...')
    with ssh_client.tunnel(dcos_api_session.masters[0]) as tunnel:
        wait_for_pong(tunnel, vip_apps[0][1])
        wait_for_pong(tunnel, vip_apps[1][1])

    agent_ids = get_instance_ids(
        get_running_instances(launcher.stack.public_agent_instances) +
        get_running_instances(launcher.stack.private_agent_instances))

    # Agents are in auto-scaling groups, so they will automatically be replaced
    log.info('Terminating instances...')
    launcher.boto_wrapper.client('ec2').terminate_instances(InstanceIds=agent_ids)
    waiter = launcher.boto_wrapper.client('ec2').get_waiter('instance_terminated')
    log.info('Waiting for instances to be terminated')
    dcos_test_utils.helpers.retry_boto_rate_limits(waiter.wait)(InstanceIds=agent_ids)

    # Tell mesos the machines are "down" and not coming up so things get rescheduled.
    log.info('Posting to mesos that agents are down')
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
        retry_on_result=lambda res: res is False)
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
    log.info('Waiting for VIPs to be routable...')
    with ssh_client.tunnel(dcos_api_session.masters[0]) as tunnel:
        wait_for_pong(tunnel, vip_apps[0][1])
        wait_for_pong(tunnel, vip_apps[1][1])

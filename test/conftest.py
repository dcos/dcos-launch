import functools
import json
from collections import namedtuple
from contextlib import contextmanager

import pytest

import dcos_launch
import dcos_launch.cli
import dcos_launch.config
import dcos_launch.onprem
import dcos_launch.platforms
import dcos_test_utils
import dcos_test_utils.ssh_client
from dcos_launch.util import get_temp_config_path, stub
from dcos_test_utils.helpers import Host


class MockTunnelled:
    def __init__(self, base_cmd: list, target: str):
        pass

    def command(self, cmd, **kwargs):
        return b''

    def copy_file(self, src, dst):
        pass


@contextmanager
def mocked_context(*args, **kwargs):
    """ To be directly patched into an ssh.tunnel invocation to prevent
    any real SSH attempt
    """
    yield MockTunnelled(list(), 'foo')


@pytest.fixture
def mocked_test_runner(monkeypatch):
    monkeypatch.setattr(dcos_launch.util, 'try_to_output_unbuffered', stub(0))


@pytest.fixture
def mock_ssh_client(monkeypatch):
    # monkeypatch.setattr(dcos_test_utils.ssh_client, 'Tunnelled', MockTunnelled)
    monkeypatch.setattr(dcos_test_utils.ssh_client, 'open_tunnel', mocked_context)
    monkeypatch.setattr(dcos_test_utils.ssh_client.SshClient, 'command', stub(b''))
    monkeypatch.setattr(dcos_test_utils.ssh_client.SshClient, 'get_home_dir', stub(b''))
    # need to nullify platforms.onprem
    monkeypatch.setattr(dcos_launch.platforms.onprem, 'prepare_bootstrap', stub('foo'))
    monkeypatch.setattr(dcos_launch.platforms.onprem, 'install_dcos', stub(None))


@pytest.fixture
def ssh_key_path(tmpdir):
    ssh_key_path = tmpdir.join('ssh_key')
    ssh_key_path.write(dcos_launch.util.MOCK_SSH_KEY_DATA)
    return str(ssh_key_path)


class MockStack:
    def __init__(self):
        self.stack_id = dcos_launch.util.MOCK_STACK_ID


class MockGceWrapper:
    def __init__(self, credentials_dict):
        DeploymentManagerMock = namedtuple('DeploymentManagerMock', 'deployments')
        DeploymentFunctionsMock = namedtuple('DeploymentFunctionsMock', 'insert delete get')
        ApiRequestMock = namedtuple('ApiRequestMock', 'execute')
        self.project_id = ''
        api_request_mock = ApiRequestMock(lambda: {'operation': {'status': 'DONE'}})
        self.deployment_manager = DeploymentManagerMock(lambda: DeploymentFunctionsMock(stub(api_request_mock),
                                                                                        stub(api_request_mock),
                                                                                        stub(api_request_mock)))


mock_pub_priv_host = Host('127.0.0.1', '12.34.56')
mock_priv_host = Host('127.0.0.1', None)
MOCK_GCE_DEPLOYMENT_INFO = {'operation': {'status': 'DONE'}}
MOCK_GCE_INSTANCE_INFO = {'name': 'mock_instance',
                          'networkInterfaces': [{'networkIP': 'mock_net_ip',
                                                 'accessConfigs': [{'natIP': 'mock_nat_ip'}]}],
                          'metadata': {'fingerprint': 'mock_fingerprint'}}


@pytest.fixture
def mocked_aws_cf(monkeypatch, mocked_test_runner):
    """Does not include SSH key mocking
    """
    # mock credentials
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'AEF234DFLDWQMNEZ2')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'ASDPFOKAWEFN123')
    monkeypatch.setattr(dcos_launch.platforms.aws.DcosCfStack, '__init__', stub(None))
    monkeypatch.setattr(
        dcos_launch.platforms.aws, 'fetch_stack',
        lambda stack_name, bw: dcos_launch.platforms.aws.DcosCfStack(stack_name, bw))
    # mock create
    monkeypatch.setattr(dcos_launch.platforms.aws.BotoWrapper, 'create_stack', stub(MockStack()))
    # mock wait
    monkeypatch.setattr(dcos_launch.platforms.aws.CfStack, 'wait_for_complete', stub(None))
    # mock describe
    monkeypatch.setattr(dcos_launch.platforms.aws.DcosCfStack, 'get_master_ips',
                        stub([mock_pub_priv_host]))
    monkeypatch.setattr(dcos_launch.platforms.aws.DcosCfStack, 'get_private_agent_ips',
                        stub([mock_priv_host]))
    monkeypatch.setattr(dcos_launch.platforms.aws.DcosCfStack, 'get_public_agent_ips',
                        stub([mock_pub_priv_host]))
    # mock delete
    monkeypatch.setattr(dcos_launch.platforms.aws.DcosCfStack, 'delete', stub(None))
    monkeypatch.setattr(dcos_launch.platforms.aws.BotoWrapper, 'delete_key_pair', stub(None))
    # mock config
    monkeypatch.setattr(dcos_launch.platforms.aws.BotoWrapper, 'create_key_pair',
                        stub(dcos_launch.util.MOCK_SSH_KEY_DATA))


@pytest.fixture
def mocked_aws_zen_cf(monkeypatch, mocked_aws_cf):
    monkeypatch.setattr(dcos_launch.platforms.aws.DcosZenCfStack, '__init__', stub(None))
    monkeypatch.setattr(
        dcos_launch.platforms.aws, 'fetch_stack',
        lambda stack_name, bw: dcos_launch.platforms.aws.DcosZenCfStack(stack_name, bw))
    # mock create
    monkeypatch.setattr(dcos_launch.platforms.aws.BotoWrapper, 'create_vpc_tagged', stub(dcos_launch.util.MOCK_VPC_ID))
    monkeypatch.setattr(
        dcos_launch.platforms.aws.BotoWrapper, 'create_internet_gateway_tagged',
        stub(dcos_launch.util.MOCK_GATEWAY_ID))
    monkeypatch.setattr(dcos_launch.platforms.aws.BotoWrapper, 'create_subnet_tagged',
                        stub(dcos_launch.util.MOCK_SUBNET_ID))
    # mock delete
    monkeypatch.setattr(dcos_launch.platforms.aws.BotoWrapper, 'delete_subnet', stub(None))
    monkeypatch.setattr(dcos_launch.platforms.aws.BotoWrapper, 'delete_vpc', stub(None))
    monkeypatch.setattr(dcos_launch.platforms.aws.BotoWrapper, 'delete_internet_gateway', stub(None))
    # mock describe
    monkeypatch.setattr(dcos_launch.platforms.aws.DcosZenCfStack, 'get_master_ips',
                        stub([mock_pub_priv_host]))
    monkeypatch.setattr(dcos_launch.platforms.aws.DcosZenCfStack, 'get_private_agent_ips',
                        stub([mock_priv_host]))
    monkeypatch.setattr(dcos_launch.platforms.aws.DcosZenCfStack, 'get_public_agent_ips',
                        stub([mock_pub_priv_host]))
    # mock delete
    monkeypatch.setattr(dcos_launch.platforms.aws.DcosZenCfStack, 'delete', stub(None))


@pytest.fixture
def mocked_azure(monkeypatch, mocked_test_runner):
    monkeypatch.setenv('AZURE_CLIENT_ID', 'AEF234DFLDWQMNEZ2')
    monkeypatch.setenv('AZURE_CLIENT_SECRET', 'ASDPFOKAWEFN123')
    monkeypatch.setenv('AZURE_TENANT_ID', 'ASDPFOKAWEFN123')
    monkeypatch.setenv('AZURE_SUBSCRIPTION_ID', 'ASDPFOKAWEFN123')
    monkeypatch.setattr(dcos_launch.platforms.arm.ServicePrincipalCredentials, '__init__', stub(None))
    monkeypatch.setattr(dcos_launch.platforms.arm.ResourceManagementClient, '__init__', stub(None))
    monkeypatch.setattr(dcos_launch.platforms.arm.NetworkManagementClient, '__init__', stub(None))
    monkeypatch.setattr(dcos_launch.platforms.arm.AzureWrapper, 'deploy_template_to_new_resource_group', stub(None))
    monkeypatch.setattr(dcos_launch.platforms.arm.DcosAzureResourceGroup, 'wait_for_deployment', stub(None))
    monkeypatch.setattr(dcos_launch.platforms.arm.DcosAzureResourceGroup, 'delete', stub(None))
    monkeypatch.setattr(dcos_launch.platforms.arm.DcosAzureResourceGroup, 'get_master_ips',
                        stub([mock_pub_priv_host]))
    monkeypatch.setattr(dcos_launch.platforms.arm.DcosAzureResourceGroup, 'get_private_agent_ips',
                        stub([mock_priv_host]))
    monkeypatch.setattr(dcos_launch.platforms.arm.DcosAzureResourceGroup, 'get_public_agent_ips',
                        stub([mock_pub_priv_host]))
    monkeypatch.setattr(dcos_launch.platforms.arm.DcosAzureResourceGroup, 'public_agent_lb_fqdn', 'abc-foo-bar')
    monkeypatch.setattr(dcos_launch.platforms.arm.DcosAzureResourceGroup, 'public_master_lb_fqdn', 'dead-beef')


@pytest.fixture
def mocked_gcp(monkeypatch, mock_ssh_client):
    monkeypatch.setenv('GCE_CREDENTIALS', '{"project_id":"foobar"}')
    monkeypatch.setenv('GCE_ZONE', 'us-west1-a')
    monkeypatch.setattr(dcos_launch.platforms.gcp.GcpWrapper, '__init__', MockGceWrapper.__init__)
    monkeypatch.setattr(dcos_launch.platforms.gcp.GcpWrapper, 'get_instance_info',
                        lambda _, __: MOCK_GCE_INSTANCE_INFO)
    monkeypatch.setattr(dcos_launch.platforms.gcp.GcpWrapper, 'list_group_instances',
                        lambda _, __: [{'instance': 'mock'}])
    monkeypatch.setattr(dcos_launch.gcp.BareClusterLauncher, 'key_helper', lambda self: self.config.update(
        {'ssh_private_key': dcos_launch.util.MOCK_SSH_KEY_DATA, 'ssh_public_key': dcos_launch.util.MOCK_SSH_KEY_DATA}))
    monkeypatch.setattr(dcos_launch.gcp.BareClusterLauncher, 'get_cluster_hosts', lambda self: [mock_pub_priv_host] *
                        (self.config['num_masters'] + self.config['num_public_agents'] +
                         self.config['num_private_agents']))
    monkeypatch.setattr(dcos_launch.gcp.BareClusterLauncher, 'get_bootstrap_host', lambda self: mock_pub_priv_host)


@pytest.fixture
def mocked_aws_cfstack_bare_cluster(monkeypatch, mock_ssh_client, mocked_aws_cf):
    monkeypatch.setattr(dcos_launch.platforms.aws.BareClusterCfStack, '__init__', stub(None))
    monkeypatch.setattr(dcos_launch.platforms.aws.BareClusterCfStack, 'delete', stub(None))
    monkeypatch.setattr(
        dcos_launch.platforms.aws.BareClusterCfStack, 'get_cluster_host_ips', stub([mock_pub_priv_host] * 4))
    monkeypatch.setattr(dcos_launch.platforms.aws.BareClusterCfStack, 'get_bootstrap_ip', stub(mock_pub_priv_host))
    monkeypatch.setattr(
        dcos_launch.platforms.aws, 'fetch_stack', lambda stack_name,
        bw: dcos_launch.platforms.aws.BareClusterCfStack(stack_name, bw))


@pytest.fixture
def aws_cf_config_path(tmpdir, ssh_key_path, mocked_aws_cf):
    return get_temp_config_path(tmpdir, 'aws-cf.yaml', update={'ssh_private_key_filename': ssh_key_path})


@pytest.fixture
def aws_cf_with_helper_config_path(tmpdir, mocked_aws_cf):
    return get_temp_config_path(tmpdir, 'aws-cf-with-helper.yaml')


@pytest.fixture
def aws_zen_cf_config_path(tmpdir, ssh_key_path, mocked_aws_zen_cf):
    return get_temp_config_path(tmpdir, 'aws-zen-cf.yaml')


@pytest.fixture
def aws_cf_no_pytest_config_path(tmpdir, mocked_aws_cf):
    return get_temp_config_path(tmpdir, 'aws-cf-no-pytest.yaml')


@pytest.fixture
def azure_config_path(tmpdir, mocked_azure, ssh_key_path):
    return get_temp_config_path(tmpdir, 'azure.yaml', update={'ssh_private_key_filename': ssh_key_path})


@pytest.fixture
def azure_with_helper_config_path(tmpdir, mocked_azure):
    return get_temp_config_path(tmpdir, 'azure-with-helper.yaml')


@pytest.fixture
def aws_onprem_config_path(tmpdir, ssh_key_path, mocked_aws_cfstack_bare_cluster):
    return get_temp_config_path(tmpdir, 'aws-onprem.yaml', update={
        'ssh_private_key_filename': ssh_key_path})


@pytest.fixture
def aws_onprem_with_helper_config_path(tmpdir, mocked_aws_cfstack_bare_cluster):
    return get_temp_config_path(tmpdir, 'aws-onprem-with-helper.yaml')


@pytest.fixture
def mock_genconf_dir(tmpdir):
    """ For testing genconf_dir and providing onprem configuration via a local
        genconf dir. Similarly, the DC/OS config can be provided by a 'dcos_config' field
        in the dcos-launch config.yaml or it can be provided in a (native) genconf/config.yaml
    """
    genconf_dir = tmpdir.join('genconf')
    genconf_dir.ensure(dir=True)
    genconf_dir.join('config.yaml').write("""
---
cluster_name: My Awesome DC/OS
resolvers:
    - 8.8.4.4
    - 8.8.8.8
dns_search: mesos
master_discovery: static
exhibitor_storage_backend: static
""")
    return str(genconf_dir)


@pytest.fixture
def aws_onprem_with_genconf_config_path(tmpdir, mock_genconf_dir, mocked_aws_cfstack_bare_cluster):
    return get_temp_config_path(tmpdir, 'aws-onprem-with-genconf.yaml', update={
        'genconf_dir': mock_genconf_dir})


@pytest.fixture
def gcp_onprem_config_path(tmpdir, ssh_key_path, mocked_gcp):
    return get_temp_config_path(tmpdir, 'gcp-onprem.yaml', update={
        'ssh_private_key_filename': ssh_key_path})


@pytest.fixture
def gcp_onprem_with_helper_config_path(tmpdir, mocked_gcp):
    return get_temp_config_path(tmpdir, 'gcp-onprem-with-helper.yaml')


@pytest.fixture
def gcp_onprem_with_fd_helper_config_path(tmpdir, mocked_gcp):
    return get_temp_config_path(tmpdir, 'gcp-onprem-with-fd-helper.yaml')


def check_cli(cmd):
    assert dcos_launch.cli.main(cmd) == 0, 'Command failed! {}'.format(' '.join(cmd))


def check_success(capsys, tmpdir, config_path):
    """
    Runs through the required functions of a launcher and then
    runs through the default usage of the script for a
    given config path and info path, ensuring each step passes
    if all steps finished successfully, this parses and returns the generated
    info JSON and stdout description JSON for more specific checks
    """
    # Test launcher directly first
    config = dcos_launch.config.get_validated_config_from_path(config_path)
    launcher = dcos_launch.get_launcher(config)
    info = launcher.create()
    # Grab the launcher again with the output from create
    launcher = dcos_launch.get_launcher(info)
    launcher.wait()
    launcher.describe()
    launcher.test([], {})
    launcher.delete()

    info_path = str(tmpdir.join('my_specific_info.json'))  # test non-default name

    # Now check launcher via CLI
    check_cli(['create', '--config-path={}'.format(config_path), '--info-path={}'.format(info_path)])
    # use the info written to disk to ensure JSON parsable
    with open(info_path) as f:
        info = json.load(f)

    check_cli(['wait', '--info-path={}'.format(info_path)])

    # clear stdout capture
    capsys.readouterr()
    check_cli(['describe', '--info-path={}'.format(info_path)])
    # capture stdout from describe and ensure JSON parse-able
    description = json.loads(capsys.readouterr()[0])

    # general assertions about description
    assert 'masters' in description
    assert 'private_agents' in description
    assert 'public_agents' in description

    check_cli(['pytest', '--info-path={}'.format(info_path)])

    check_cli(['delete', '--info-path={}'.format(info_path)])

    return info, description


@pytest.fixture
def check_cli_success(capsys, tmpdir):
    return functools.partial(check_success, capsys, tmpdir)

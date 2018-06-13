import collections
import json
import os
import subprocess

import pkg_resources

import dcos_launch
import dcos_test_utils
from dcos_launch import config
from dcos_test_utils import helpers


def test_aws_onprem(check_cli_success, aws_onprem_config_path):
    info, desc = check_cli_success(aws_onprem_config_path)
    assert 'stack_id' in info
    assert info['ssh_private_key'] == dcos_launch.util.MOCK_SSH_KEY_DATA
    assert 'template_body' not in desc  # distracting irrelevant information
    assert 'bootstrap_host' in desc


def test_aws_onprem_install_prereqs(check_cli_success, aws_onprem_install_prereqs_config_path):
    info, desc = check_cli_success(aws_onprem_install_prereqs_config_path)
    assert 'stack_id' in info
    assert info['ssh_private_key'] == dcos_launch.util.MOCK_SSH_KEY_DATA
    assert 'template_body' not in desc  # distracting irrelevant information
    assert 'bootstrap_host' in desc
    assert info['prereqs_script_filename'] == 'unset'
    assert info['install_prereqs']
    assert os.path.exists(config.expand_path(
            pkg_resources.resource_filename(dcos_launch.__name__, 'scripts/install_prereqs.sh'),
            info['config_dir']))


def test_aws_onprem_with_helper(check_cli_success, aws_onprem_with_helper_config_path):
    info, desc = check_cli_success(aws_onprem_with_helper_config_path)
    assert 'stack_id' in info
    assert info['ssh_private_key'] == dcos_launch.util.MOCK_SSH_KEY_DATA
    assert 'template_body' not in desc  # distracting irrelevant information
    assert 'KeyName' in info['template_parameters']
    assert 'bootstrap_host' in desc


def test_aws_onprem_with_extra_iam(check_cli_success, aws_onprem_with_extra_iam_config_path):
    info, desc = check_cli_success(aws_onprem_with_extra_iam_config_path)
    assert 'stack_id' in info
    assert info['ssh_private_key'] == dcos_launch.util.MOCK_SSH_KEY_DATA
    assert 'template_body' not in desc  # distracting irrelevant information
    assert 'KeyName' in info['template_parameters']
    assert 'bootstrap_host' in desc


def test_gcp_onprem(check_cli_success, gcp_onprem_config_path):
    info, desc = check_cli_success(gcp_onprem_config_path)
    assert info['ssh_private_key'] == dcos_launch.util.MOCK_SSH_KEY_DATA
    assert info['ssh_public_key'] == dcos_launch.util.MOCK_SSH_KEY_DATA
    assert 'template_body' not in desc  # distracting irrelevant information
    assert 'bootstrap_host' in desc


def test_gcp_onprem_with_helper(check_cli_success, gcp_onprem_with_helper_config_path):
    info, desc = check_cli_success(gcp_onprem_with_helper_config_path)
    assert info['ssh_private_key'] == dcos_launch.util.MOCK_SSH_KEY_DATA
    assert info['ssh_public_key'] == dcos_launch.util.MOCK_SSH_KEY_DATA
    assert 'template_body' not in desc  # distracting irrelevant information
    assert 'bootstrap_host' in desc


def test_fault_domain_helper(check_cli_success, gcp_onprem_with_fd_helper_config_path, monkeypatch, tmpdir):

    config = dcos_launch.config.get_validated_config_from_path(gcp_onprem_with_fd_helper_config_path)

    # set the onprem cluster to return the correct number of mocked nodes, these names are throw awawy
    mock_private_agent_ips = list((helpers.Host('foo', 'bar') for _ in range(config['num_private_agents'])))
    mock_public_agent_ips = list((helpers.Host('foo', 'bar') for _ in range(config['num_public_agents'])))
    mock_master_ips = list((helpers.Host('foo', 'bar') for _ in range(config['num_masters'])))
    monkeypatch.setattr(
        dcos_test_utils.onprem.OnpremCluster,
        'get_private_agent_ips',
        lambda *args, **kwargs: mock_private_agent_ips)
    monkeypatch.setattr(
        dcos_test_utils.onprem.OnpremCluster,
        'get_public_agent_ips',
        lambda *args, **kwargs: mock_public_agent_ips)
    monkeypatch.setattr(
        dcos_test_utils.onprem.OnpremCluster,
        'get_master_ips',
        lambda *args, **kwargs: mock_master_ips)
    # now mock the hostnames that will be returned by the SSH command
    total_nodes = config['num_private_agents'] + config['num_public_agents'] + config['num_masters']
    # tail with '\n' to mimic reality
    hostname_stack = list((s.encode() for s in ('host-' + str(i) + '\n' for i in range(total_nodes))))
    hostname_list = list(hostname_stack)
    monkeypatch.setattr(
        dcos_test_utils.ssh_client.SshClient,
        'command',
        lambda *args, **kwargs: hostname_stack.pop())
    launcher = dcos_launch.get_launcher(config)
    fd_script = launcher._fault_domain_helper()
    results = collections.defaultdict(list)
    with tmpdir.as_cwd():
        for host in hostname_list:
            script_path = tmpdir.join('fault-domain-detect.sh')
            script_path.write(fd_script)
            subprocess.check_call([
                # strip \n here as this is hacking the processed script
                'sed', '-i',
                's/hostname=$(hostname)/hostname={}/g'.format(host.decode().strip('\n')),
                str(script_path)])
            fd_out = subprocess.check_output(['bash', str(script_path)])
            fd_json = json.loads(fd_out.decode())
            assert 'region' in fd_json['fault_domain']
            assert 'zone' in fd_json['fault_domain']
            results[fd_json['fault_domain']['region']['name']].append(fd_json['fault_domain']['zone']['name'])
    for region, info in config['fault_domain_helper'].items():
        # assert there are the correct number of assignments per region
        if info['local']:
            assert len(results[region]) == \
                info['num_private_agents'] + info['num_public_agents'] + config['num_masters']
        else:
            assert len(results[region]) == info['num_private_agents'] + info['num_public_agents']
        # assert there are the correct number of zones in the region
        assert set([region + '-' + str(i) for i in range(1, info['num_zones'] + 1)]) == set(results[region])

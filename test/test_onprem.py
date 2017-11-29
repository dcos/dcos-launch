import random
import string

import dcos_test_utils

import dcos_launch


def test_aws_onprem(check_cli_success, aws_onprem_config_path):
    info, desc = check_cli_success(aws_onprem_config_path)
    assert 'stack_id' in info
    assert info['ssh_private_key'] == dcos_launch.util.MOCK_SSH_KEY_DATA
    assert 'template_body' not in desc  # distracting irrelevant information


def test_aws_onprem_with_helper(check_cli_success, aws_onprem_with_helper_config_path):
    info, desc = check_cli_success(aws_onprem_with_helper_config_path)
    assert 'stack_id' in info
    assert info['ssh_private_key'] == dcos_launch.util.MOCK_SSH_KEY_DATA
    assert 'template_body' not in desc  # distracting irrelevant information
    assert 'KeyName' in info['template_parameters']


def test_gcp_onprem(check_cli_success, gcp_onprem_config_path):
    info, desc = check_cli_success(gcp_onprem_config_path)
    assert info['ssh_private_key'] == dcos_launch.util.MOCK_SSH_KEY_DATA
    assert info['ssh_public_key'] == dcos_launch.util.MOCK_SSH_KEY_DATA
    assert 'template_body' not in desc  # distracting irrelevant information


def test_gcp_onprem_with_helper(check_cli_success, gcp_onprem_with_helper_config_path):
    info, desc = check_cli_success(gcp_onprem_with_helper_config_path)
    assert info['ssh_private_key'] == dcos_launch.util.MOCK_SSH_KEY_DATA
    assert info['ssh_public_key'] == dcos_launch.util.MOCK_SSH_KEY_DATA
    assert 'template_body' not in desc  # distracting irrelevant information


def test_gcp_onprem_with_fd_helper(check_cli_success, gcp_onprem_with_fd_helper_config_path, monkeypatch):
    monkeypatch.setattr(dcos_test_utils.ssh_client.SshClient, 'command', dcos_launch.util.stub(
              ''.join([random.choice(string.ascii_uppercase + string.digits) for _ in range(5)]).encode()))
    config = dcos_launch.config.get_validated_config_from_path(gcp_onprem_with_fd_helper_config_path)
    launcher = dcos_launch.get_launcher(config)
    assert launcher._fault_domain_helper() == 1

import pytest

import dcos_launch
import dcos_launch.cli
import dcos_launch.config
import dcos_launch.util
import dcos_test_utils.aws


def test_aws_cf_simple(check_cli_success, aws_cf_config_path):
    """Test that required parameters are consumed and appropriate output is generated
    """
    info, desc = check_cli_success(aws_cf_config_path)
    # check AWS specific info
    assert 'stack_id' in info
    assert info['ssh_private_key'] == dcos_launch.util.MOCK_SSH_KEY_DATA
    # key should not have been generated
    assert 'key_name' not in info['temp_resources']


def test_aws_zen_cf_simple(check_cli_success, aws_zen_cf_config_path):
    """Test that required parameters are consumed and appropriate output is generated
    """
    info, desc = check_cli_success(aws_zen_cf_config_path)
    # check AWS specific info
    assert 'stack_id' in info
    assert 'vpc' in info['temp_resources']
    assert 'gateway' in info['temp_resources']
    assert 'private_subnet' in info['temp_resources']
    assert 'public_subnet' in info['temp_resources']


def mock_stack_not_found(*args):
    raise Exception('Mock stack was not found!!!')


def test_missing_aws_stack(aws_cf_config_path, monkeypatch):
    """ Tests that clean and appropriate errors will be raised
    """
    monkeypatch.setattr(dcos_test_utils.aws, 'fetch_stack', mock_stack_not_found)
    config = dcos_launch.config.get_validated_config(aws_cf_config_path)
    aws_launcher = dcos_launch.get_launcher(config)

    def check_stack_error(cmd, args):
        with pytest.raises(dcos_launch.util.LauncherError) as exinfo:
            getattr(aws_launcher, cmd)(*args)
        assert exinfo.value.error == 'StackNotFound'

    info = aws_launcher.create()
    aws_launcher = dcos_launch.get_launcher(info)
    check_stack_error('wait', ())
    check_stack_error('describe', ())
    check_stack_error('delete', ())
    check_stack_error('test', ([], {}))


def test_key_helper(aws_cf_with_helper_config_path):
    config = dcos_launch.config.get_validated_config(aws_cf_with_helper_config_path)
    aws_launcher = dcos_launch.get_launcher(config)
    temp_resources = aws_launcher.key_helper()
    assert temp_resources['key_name'] == config['deployment_name']
    assert config['template_parameters']['KeyName'] == config['deployment_name']
    assert config['ssh_private_key'] == dcos_launch.util.MOCK_SSH_KEY_DATA


def test_zen_helper(aws_zen_cf_config_path):
    config = dcos_launch.config.get_validated_config(aws_zen_cf_config_path)
    aws_launcher = dcos_launch.get_launcher(config)
    temp_resources = aws_launcher.zen_helper()
    assert temp_resources['vpc'] == dcos_launch.util.MOCK_VPC_ID
    assert temp_resources['gateway'] == dcos_launch.util.MOCK_GATEWAY_ID
    assert temp_resources['private_subnet'] == dcos_launch.util.MOCK_SUBNET_ID
    assert temp_resources['public_subnet'] == dcos_launch.util.MOCK_SUBNET_ID
    assert config['template_parameters']['Vpc'] == dcos_launch.util.MOCK_VPC_ID
    assert config['template_parameters']['InternetGateway'] == dcos_launch.util.MOCK_GATEWAY_ID
    assert config['template_parameters']['PrivateSubnet'] == dcos_launch.util.MOCK_SUBNET_ID
    assert config['template_parameters']['PublicSubnet'] == dcos_launch.util.MOCK_SUBNET_ID

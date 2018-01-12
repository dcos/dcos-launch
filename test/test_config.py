import os

import pytest

from dcos_launch.config import LaunchValidator, get_validated_config_from_path
from dcos_launch.util import LauncherError, get_temp_config_path


@pytest.fixture
def mock_home(tmpdir):
    home_cache = os.getenv('HOME', None)
    os.environ['HOME'] = str(tmpdir)
    yield str(tmpdir)
    if home_cache is not None:
        os.environ['HOME'] = home_cache
    else:
        del os.environ['HOME']


@pytest.fixture
def mock_relative_path(tmpdir):
    with tmpdir.as_cwd():
        yield str(tmpdir)


def test_launch_validator(mock_home, mock_relative_path):
    test_schema = {
        'foobar_path': {'coerce': 'expand_local_path'},
        'baz_path': {'coerce': 'expand_local_path'}}
    validator = LaunchValidator(test_schema, config_dir=mock_relative_path)

    test_input = {
        'foobar_path': 'foo/bar',
        'baz_path': '~/baz'}
    expected_output = {
        'foobar_path': os.path.join(mock_relative_path, 'foo/bar'),
        'baz_path': os.path.join(mock_home, 'baz')}

    assert validator.normalized(test_input) == expected_output


class TestAwsCloudformation:
    def test_basic(self, aws_cf_config_path):
        get_validated_config_from_path(aws_cf_config_path)

    def test_with_key_helper(self, aws_cf_with_helper_config_path):
        get_validated_config_from_path(aws_cf_with_helper_config_path)

    def test_with_zen_helper(self, aws_zen_cf_config_path):
        get_validated_config_from_path(aws_zen_cf_config_path)

    def test_without_pytest_support(self, aws_cf_no_pytest_config_path):
        get_validated_config_from_path(aws_cf_no_pytest_config_path)

    def test_error_with_invalid_field(self, tmpdir):
        with pytest.raises(LauncherError) as exinfo:
            get_validated_config_from_path(
                get_temp_config_path(
                    tmpdir, 'aws-cf-with-helper.yaml', update={'installer_url': 'foobar'}))
        assert exinfo.value.error == 'ValidationError'
        assert 'installer_url' in exinfo.value.msg


class TestAzureTemplate:
    def test_basic(self, azure_config_path):
        get_validated_config_from_path(azure_config_path)

    def test_with_key_helper(self, azure_with_helper_config_path):
        get_validated_config_from_path(azure_with_helper_config_path)

    def test_error_with_invalid_field(self, tmpdir):
        with pytest.raises(LauncherError) as exinfo:
            get_validated_config_from_path(
                get_temp_config_path(
                    tmpdir, 'azure-with-helper.yaml', update={'num_masters': '0.0.0'}))
        assert exinfo.value.error == 'ValidationError'
        assert 'num_masters' in exinfo.value.msg


class TestAwsOnprem:
    def test_basic(self, aws_onprem_config_path):
        get_validated_config_from_path(aws_onprem_config_path)

    def test_with_key_helper(self, aws_onprem_with_helper_config_path):
        get_validated_config_from_path(aws_onprem_with_helper_config_path)

    def test_with_genconf(self, aws_onprem_with_genconf_config_path):
        get_validated_config_from_path(aws_onprem_with_genconf_config_path)

    def test_error_is_skipped_in_nested_config(self, tmpdir):
        get_validated_config_from_path(
            get_temp_config_path(
                tmpdir, 'aws-onprem-with-helper.yaml',
                update={'dcos_config': {'provider': 'aws'}}))


class TestGcpOnprem:
    def test_basic(self, gcp_onprem_config_path):
        get_validated_config_from_path(gcp_onprem_config_path)

    def test_with_key_helper(self, gcp_onprem_with_helper_config_path):
        get_validated_config_from_path(gcp_onprem_with_helper_config_path)

    def test_error_with_invalid_field(self, tmpdir):
        with pytest.raises(LauncherError) as exinfo:
            get_validated_config_from_path(
                get_temp_config_path(
                    tmpdir, 'gcp-onprem-with-helper.yaml', update={'num_masters': '0.0.0'}))
        assert exinfo.value.error == 'ValidationError'
        assert 'num_masters' in exinfo.value.msg

    def test_no_local_region(self, tmpdir):
        """ Tests that if no 'local' option is handed to the fault domain helper,
        an error will be raised
        """
        config = get_validated_config_from_path(
            get_temp_config_path(
                tmpdir, 'gcp-onprem-with-fd-helper.yaml'))
        del config['fault_domain_helper']['USA']['local']
        with pytest.raises(LauncherError) as exinfo:
            get_validated_config_from_path(
                get_temp_config_path(
                    tmpdir, 'gcp-onprem-with-fd-helper.yaml',
                    update={'fault_domain_helper': config['fault_domain_helper']}))
        assert exinfo.value.error == 'ValidationError'

    def test_with_fd_helper(self, gcp_onprem_with_fd_helper_config_path):
        config = get_validated_config_from_path(gcp_onprem_with_fd_helper_config_path)
        assert config['num_private_agents'] == 9
        assert config['num_public_agents'] == 5
        assert set(config['fault_domain_helper'].keys()) == {'Europe', 'USA', 'Asia'}

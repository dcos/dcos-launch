import os

import pytest

from dcos_launch.config import LaunchValidator, get_validated_config
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
        get_validated_config(aws_cf_config_path)

    def test_with_key_helper(self, aws_cf_with_helper_config_path):
        get_validated_config(aws_cf_with_helper_config_path)

    def test_with_zen_helper(self, aws_zen_cf_config_path):
        get_validated_config(aws_zen_cf_config_path)

    def test_without_pytest_support(self, aws_cf_no_pytest_config_path):
        get_validated_config(aws_cf_no_pytest_config_path)

    def test_error_with_invalid_field(self, tmpdir):
        with pytest.raises(LauncherError) as exinfo:
            get_validated_config(
                get_temp_config_path(
                    tmpdir, 'aws-cf-with-helper.yaml', update={'installer_url': 'foobar'}))
        assert exinfo.value.error == 'ValidationError'
        assert 'installer_url' in exinfo.value.msg


class TestAzureTemplate:
    def test_basic(self, azure_config_path):
        get_validated_config(azure_config_path)

    def test_with_key_helper(self, azure_with_helper_config_path):
        get_validated_config(azure_with_helper_config_path)

    def test_error_with_invalid_field(self, tmpdir):
        with pytest.raises(LauncherError) as exinfo:
            get_validated_config(
                get_temp_config_path(
                    tmpdir, 'azure-with-helper.yaml', update={'num_masters': '0.0.0'}))
        assert exinfo.value.error == 'ValidationError'
        assert 'num_masters' in exinfo.value.msg


class TestAwsOnprem:
    def test_basic(self, aws_onprem_config_path):
        get_validated_config(aws_onprem_config_path)

    def test_with_key_helper(self, aws_onprem_with_helper_config_path):
        get_validated_config(aws_onprem_with_helper_config_path)

    def test_error_with_nested_config(self, tmpdir):
        with pytest.raises(LauncherError) as exinfo:
            get_validated_config(
                get_temp_config_path(
                    tmpdir, 'aws-onprem-with-helper.yaml',
                    update={'dcos_config': {
                        'ip_detect_content': 'foo',
                        'ip_detect_filename': 'bar'}}))
        assert exinfo.value.error == 'ValidationError'
        assert 'ip_detect' in exinfo.value.msg

    def test_error_is_skipped_in_nested_config(self, tmpdir):
        get_validated_config(
            get_temp_config_path(
                tmpdir, 'aws-onprem-with-helper.yaml',
                update={'dcos_config': {'provider': 'aws'}}))


class TestGceOnprem:
    def test_basic(self, gce_onprem_config_path):
        get_validated_config(gce_onprem_config_path)

    def test_with_key_helper(self, gce_onprem_with_helper_config_path):
        get_validated_config(gce_onprem_with_helper_config_path)

    def test_error_with_invalid_field(self, tmpdir):
        with pytest.raises(LauncherError) as exinfo:
            get_validated_config(
                get_temp_config_path(
                    tmpdir, 'gce-onprem-with-helper.yaml', update={'num_masters': '0.0.0'}))
        assert exinfo.value.error == 'ValidationError'
        assert 'num_masters' in exinfo.value.msg

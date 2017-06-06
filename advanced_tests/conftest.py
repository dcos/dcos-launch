import json
import os
import time

import pytest

import dcos_launch.config
import dcos_launch.util
from dcos_test_utils import logging

logging.setup_logging('DEBUG')


@pytest.fixture(scope='session')
def create_cluster():
    if 'TEST_CREATE_CLUSTER' not in os.environ:
        raise Exception('TEST_CREATE_CLUSTER must be to set true or false in the local environment')
    return os.environ['TEST_CREATE_CLUSTER'] == 'true'


@pytest.fixture(scope='session')
def cluster_info_path(create_cluster):
    path = os.getenv('TEST_CLUSTER_INFO_PATH', 'cluster_info.json')
    if os.path.exists(path) and create_cluster:
        raise Exception('Test cannot begin while cluster_info.json is present in working directory')
    return path


@pytest.fixture(scope='session')
@pytest.mark.skipif(
    'TEST_LAUNCH_CONFIG_PATH' not in os.environ,
    reason='This test must have dcos-launch config YAML or info JSON to run')
def launcher(create_cluster, cluster_info_path):
    """ Optionally create and wait on a cluster to finish provisioning.

    This function uses environment variables as arguments:
    - TEST_LAUNCH_CONFIG_PATH: either a launch config YAML for a new cluster or
        a launch info JSON for an existing cluster
    - TEST_CREATE_CLUSTER: can be `true` or `false`. If `true`, a new cluster
        will be created for this test
    - TEST_CLUSTER_INFO_PATH: path where the cluster info will be info JSON
        will be dumped for future manipulation
    """
    # Use non-strict validation so that info JSONs with extra fields do not
    # raise errors on configuration validation
    if create_cluster:
        launcher = dcos_launch.get_launcher(
            dcos_launch.config.get_validated_config(os.environ['TEST_LAUNCH_CONFIG_PATH']))
        info = launcher.create()
        with open(cluster_info_path, 'w') as f:
            json.dump(info, f)
        # basic wait to account for initial provisioning delay
        time.sleep(180)
        launcher.wait()
    else:
        try:
            launcher = dcos_launch.get_launcher(json.load(open(os.environ['TEST_LAUNCH_CONFIG_PATH'], 'r')))
            launcher.wait()
        except dcos_launch.util.LauncherError:
            raise AssertionError(
                'Cluster creation was not specified with TEST_CREATE_CLUSTER, yet launcher '
                'cannot reach the speficied cluster')
    return launcher

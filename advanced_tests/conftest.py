import logging
import json
import os

import pytest

import dcos_launch.config
import dcos_launch.util

logging.basicConfig(format='[%(asctime)s|%(name)s|%(levelname)s]: %(message)s', level=logging.INFO)


@pytest.fixture(scope='session')
def launcher():
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
    launcher = dcos_launch.get_launcher(
        dcos_launch.config.get_validated_config(os.environ['TEST_LAUNCH_CONFIG_PATH'], strict=False))
    if os.environ.get('TEST_CREATE_CLUSTER') == 'true':
        info = launcher.create()
        with open(os.getenv('TEST_CLUSTER_INFO_PATH', 'test_cluster_info.json'), 'w') as f:
            json.dump(info, f)
        launcher.wait()
    else:
        try:
            launcher.wait()
        except dcos_launch.util.LauncherError:
            raise AssertionError(
                'Cluster creation was not specified with TEST_CREATE_CLUSTER, yet launcher '
                'cannot reach the speficied cluster')
    return launcher

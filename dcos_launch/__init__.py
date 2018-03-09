import dcos_launch.acs_engine
import dcos_launch.arm
import dcos_launch.aws
import dcos_launch.gcp
import dcos_launch.onprem
import dcos_launch.util

VERSION = '0.1.0'


def get_launcher(config, env=None):
    """Returns the correct class of launcher from a validated launch config dict
    """
    platform = config['platform']
    provider = config['provider']
    if platform == 'aws':
        if provider == 'aws':
            return dcos_launch.aws.DcosCloudformationLauncher(config, env=env)
        if provider == 'onprem':
            return dcos_launch.aws.OnPremLauncher(config, env=env)
    if platform == 'azure':
        if provider == 'azure':
            return dcos_launch.arm.AzureResourceGroupLauncher(config, env=env)
        if provider == 'acs-engine':
            return dcos_launch.acs_engine.ACSEngineLauncher(config, env=env)
    if platform == 'gcp':
        return dcos_launch.gcp.OnPremLauncher(config, env=env)
    raise dcos_launch.util.LauncherError('UnsupportedAction', 'Launch platform not supported: {}'.format(platform))

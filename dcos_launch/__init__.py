import dcos_launch.arm
import dcos_launch.aws
import dcos_launch.gce
import dcos_launch.onprem
import dcos_launch.util


def get_launcher(config, env=None):
    """Returns the correct class of launcher from a validated launch config dict
    """
    platform = config['platform']
    provider = config['provider']
    if platform == 'aws':
        if provider == 'aws':
            return dcos_launch.aws.DcosCloudformationLauncher(config, env=env)
        if provider == 'onprem':
            return dcos_launch.onprem.OnpremLauncher(config, env=env)
    if platform == 'azure':
        return dcos_launch.arm.AzureResourceGroupLauncher(config, env=env)
    if platform == 'gce':
        return dcos_launch.onprem.OnpremLauncher(config, env=env)
    raise dcos_launch.util.LauncherError('UnsupportedAction', 'Launch platform not supported: {}'.format(platform))

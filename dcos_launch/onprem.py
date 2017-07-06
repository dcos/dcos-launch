import copy
import logging
import subprocess

import pkg_resources
import yaml

import dcos_launch.aws
import dcos_launch.gce
import dcos_launch.util
import dcos_test_utils.aws
import dcos_test_utils.onprem
from dcos_test_utils.helpers import Url

log = logging.getLogger(__name__)

STATE_FILE = 'LAST_COMPLETED_STAGE'


class OnpremLauncher(dcos_launch.util.AbstractLauncher):
    def __init__(self, config):
        # can only be set during the wait command
        self.bootstrap_host = None
        self.config = config

    def create(self):
        return self.get_bare_cluster_launcher().create()

    def post_state(self, state):
        self.get_ssh_client().command(self.bootstrap_host, ['printf', state, '>', STATE_FILE])

    def get_last_state(self):
        return self.get_ssh_client().command(self.bootstrap_host, ['cat', STATE_FILE]).decode().strip()

    def get_bare_cluster_launcher(self):
        if self.config['platform'] == 'aws':
            return dcos_launch.aws.BareClusterLauncher(self.config)
        elif self.config['platform'] == 'gce':
            return dcos_launch.gce.BareClusterLauncher(self.config)
        else:
            raise dcos_launch.util.LauncherError(
                'PlatformNotSupported',
                'Platform currently not supported for onprem: {}'.format(self.config['platform']))

    def get_onprem_cluster(self):
        return dcos_test_utils.onprem.OnpremCluster.from_hosts(
            ssh_client=self.get_ssh_client(),
            hosts=self.get_bare_cluster_launcher().get_hosts(),
            num_masters=int(self.config['num_masters']),
            num_private_agents=int(self.config['num_private_agents']),
            num_public_agents=int(self.config['num_public_agents']))

    def get_completed_onprem_config(self, cluster: dcos_test_utils.onprem.OnpremCluster) -> dict:
        onprem_config = self.config['dcos_config']
        # First, try and retrieve the agent list from the cluster
        onprem_config['agent_list'] = [h.private_ip for h in cluster.private_agents]
        onprem_config['public_agent_list'] = [h.private_ip for h in cluster.public_agents]
        onprem_config['master_list'] = [h.private_ip for h in cluster.masters]
        # if the user wanted to use exhibitor as the backend, then start it
        if onprem_config.get('exhibitor_storage_backend') == 'zookeeper':
            onprem_config['exhibitor_zk_hosts'] = cluster.start_bootstrap_zk()
        # if key helper is true then ssh key must be injected, or the key
        # must have been provided as a file and still needs to be injected
        if self.config['key_helper'] or 'ssh_key' not in onprem_config:
            onprem_config['ssh_key'] = self.config['ssh_private_key']
        # check if ssh user was not provided
        if 'ssh_user' not in onprem_config:
            onprem_config['ssh_user'] = self.config['ssh_user']
        # check if the user provided any filenames and convert them into content
        for key_name in ('ip_detect_filename', 'ip_detect_public_filename'):
            if key_name not in onprem_config:
                continue
            new_key_name = key_name.replace('_filename', '_contents')
            if new_key_name in onprem_config:
                raise dcos_launch.util.LauncherError(
                    'InvalidDcosConfig', 'Cannot set *_filename and *_contents simultaneously!')
            onprem_config[new_key_name] = dcos_launch.util.read_file(onprem_config[key_name])
            del onprem_config[key_name]
        # set the simple default IP detect script if not provided
        if 'ip_detect_contents' not in onprem_config:
            onprem_config['ip_detect_contents'] = pkg_resources.resource_string(
                'dcos_test_utils', 'ip-detect/{}.sh'.format(self.config['platform'])).decode()
        if 'ip_detect_public_contents' not in onprem_config:
            # despite being almost identical aws_public.sh will crash the installer if not safely dumped
            onprem_config['ip_detect_public_contents'] = yaml.dump(pkg_resources.resource_string(
                'dcos_test_utils', 'ip-detect/{}_public.sh'.format(self.config['platform'])).decode())
        # For no good reason the installer uses 'ip_detect_script' instead of 'ip_detect_contents'
        onprem_config['ip_detect_script'] = onprem_config['ip_detect_contents']
        del onprem_config['ip_detect_contents']
        log.debug('Generated cluster configuration: {}'.format(onprem_config))
        return onprem_config

    def wait(self):
        log.info('Waiting for bare cluster provisioning status..')
        self.get_bare_cluster_launcher().wait()
        cluster = self.get_onprem_cluster()
        log.info('Waiting for SSH connectivity to cluster host...')
        for host in cluster.hosts:
            cluster.ssh_client.wait_for_ssh_connection(host.public_ip, self.config['ssh_port'])

        self.bootstrap_host = cluster.bootstrap_host.public_ip
        try:
            self.get_ssh_client().command(self.bootstrap_host, ['test', '-f', STATE_FILE])
            last_complete = self.get_last_state()
            log.info('Detected previous launch state, continuing '
                     'from last complete stage ({})'.format(last_complete))
        except subprocess.CalledProcessError:
            log.info('No installation state file detected; beginning fresh install...')
            last_complete = None

        if last_complete is None:
            cluster.setup_installer_server(self.config['installer_url'], False)
            last_complete = 'SETUP'
            self.post_state(last_complete)

        installer = dcos_test_utils.onprem.DcosInstallerApiSession(Url(
            'http', self.bootstrap_host, '', '', '', self.config['installer_port']))
        if last_complete == 'SETUP':
            last_complete = 'GENCONF'
            installer.genconf(self.get_completed_onprem_config(cluster))
            self.post_state(last_complete)
        if last_complete == 'GENCONF':
            installer.preflight()
            last_complete = 'PREFLIGHT'
            self.post_state(last_complete)
        if last_complete == 'PREFLIGHT':
            installer.deploy()
            last_complete = 'DEPLOY'
            self.post_state(last_complete)
        if last_complete == 'DEPLOY':
            installer.postflight()
            last_complete = 'POSTFLIGHT'
            self.post_state(last_complete)
        if last_complete != 'POSTFLIGHT':
            raise dcos_launch.util.LauncherError('InconsistentState', 'State on bootstrap host is: ' + last_complete)

    def describe(self):
        """ returns host information stored in the config as
        well as the basic provider info
        """
        cluster = self.get_onprem_cluster()
        extra_info = {
            'bootstrap_host': dcos_launch.util.convert_host_list([cluster.bootstrap_host])[0],
            'masters': dcos_launch.util.convert_host_list(cluster.get_master_ips()),
            'private_agents': dcos_launch.util.convert_host_list(cluster.get_private_agent_ips()),
            'public_agents': dcos_launch.util.convert_host_list(cluster.get_public_agent_ips())}
        desc = copy.copy(self.config)
        desc.update(extra_info)
        # blackout unwanted fields
        desc.pop('template_body', None)
        desc.pop('template_parameters', None)
        return desc

    def delete(self):
        """ just deletes the hardware
        """
        self.get_bare_cluster_launcher().delete()

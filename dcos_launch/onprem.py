import logging
import os

import pkg_resources
import yaml

import dcos_launch.aws
import dcos_launch.gcp
import dcos_launch.util
from dcos_launch import platforms
from dcos_test_utils import onprem, ssh_client

log = logging.getLogger(__name__)


class OnpremLauncher(dcos_launch.util.AbstractLauncher):
    def __init__(self, config, env=None):
        # can only be set during the wait command
        self.bootstrap_host = None
        self.config = config
        if env is None:
            env = os.environ.copy()
        self.env = env

    def create(self):
        return self.get_bare_cluster_launcher().create()

    def get_bare_cluster_launcher(self):
        if self.config['platform'] == 'aws':
            return dcos_launch.aws.BareClusterLauncher(self.config, env=self.env)
        elif self.config['platform'] == 'gcp':
            return dcos_launch.gcp.BareClusterLauncher(self.config, env=self.env)
        else:
            raise dcos_launch.util.LauncherError(
                'PlatformNotSupported',
                'Platform currently not supported for onprem: {}'.format(self.config['platform']))

    def get_onprem_cluster(self):
        cluster_launcher = self.get_bare_cluster_launcher()
        return onprem.OnpremCluster.from_hosts(
            # the onprem cluster object only uses the ssh client to talk to BS host
            ssh_client=self.get_ssh_client(user='bootstrap_ssh_user'),
            bootstrap_host=cluster_launcher.get_bootstrap_host(),
            cluster_hosts=cluster_launcher.get_cluster_hosts(),
            num_masters=int(self.config['num_masters']),
            num_private_agents=int(self.config['num_private_agents']),
            num_public_agents=int(self.config['num_public_agents']))

    def get_completed_onprem_config(self, cluster: onprem.OnpremCluster, bootstrap_ssh_client) -> dict:
        onprem_config = self.config['dcos_config']
        onprem_config['num_masters'] = self.config['num_masters']
        # First, try and retrieve the agent list from the cluster
        # if the user wanted to use exhibitor as the backend, then start it
        exhibitor_backend = onprem_config.get('exhibitor_storage_backend')
        if exhibitor_backend == 'zookeeper':
            zk_service_name = 'dcos-bootstrap-zk'
            with bootstrap_ssh_client.tunnel(cluster.bootstrap_host.public_ip) as t:
                if not ssh_client.get_docker_service_status(t, zk_service_name):
                    ssh_client.start_docker_service(
                        t,
                        zk_service_name,
                        ['--publish=2181:2181', '--publish=2888:2888', '--publish=3888:3888', 'jplock/zookeeper'])
                onprem_config['exhibitor_zk_hosts'] = cluster.bootstrap_host.private_ip + ':2181'
        elif exhibitor_backend == 'static':
            onprem_config['master_list'] = [h.private_ip for h in cluster.masters]
        # if key helper is true then ssh key must be injected, or the key
        # must have been provided as a file and still needs to be injected
        if self.config['key_helper'] or 'ssh_key' not in onprem_config:
            onprem_config['ssh_key'] = self.config['ssh_private_key']
        # check if the user provided any filenames and convert them into content
        for key_name in ('ip_detect_filename', 'ip_detect_public_filename',
                         'fault_domain_script_filename'):
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
                'dcos_launch', 'ip-detect/{}.sh'.format(self.config['platform'])).decode()
        if 'ip_detect_public_contents' not in onprem_config:
            # despite being almost identical aws_public.sh will crash the installer if not safely dumped
            onprem_config['ip_detect_public_contents'] = yaml.dump(pkg_resources.resource_string(
                'dcos_launch', 'ip-detect/{}_public.sh'.format(self.config['platform'])).decode())
        # set the fault domain scipt
        if 'fault_domain_detect_contents' not in onprem_config and 'fault_domain_helper' not in self.config:
            onprem_config['fault_domain_detect_contents'] = yaml.dump(pkg_resources.resource_string(
                'dcos_launch', 'fault-domain-detect/{}.sh'.format(self.config['platform'])).decode())
        elif 'fault_domain_helper' in self.config:
            onprem_config['fault_domain_detect_contents'] = yaml.dump(self._fault_domain_helper())

        log.debug('Generated cluster configuration: {}'.format(onprem_config))
        return onprem_config

    def _fault_domain_helper(self) -> str:
        """ Will create a script with cluster hostnames baked in so that
        an arbitary cluster/zone composition can be provided
        Note: agent count has already been validated by the config module so
            we can assume everything will be correct here
        """
        region_zone_map = dict()
        cluster = self.get_onprem_cluster()
        public_agents = cluster.get_public_agent_ips()
        private_agents = cluster.get_private_agent_ips()
        masters = cluster.get_master_ips()
        case_str = ""
        case_template = """
{hostname})
    REGION={region}
    ZONE={zone} ;;
"""
        for region, info in self.config['fault_domain_helper'].items():
            z_i = 0  # zones iterator
            z_mod = info['num_zones']  # zones modulo
            zones = list(range(1, z_mod + 1))
            if info['local']:
                while len(masters) > 0:
                    hostname = self.get_ssh_client().command(
                        masters.pop().public_ip, ['hostname']).decode().strip('\n')
                    region_zone_map[hostname] = region + '-' + str(zones[z_i % z_mod])
                    z_i += 1
            for _ in range(info['num_public_agents']):
                if len(public_agents) > 0:
                    # distribute out the nodes across the zones until we run out
                    hostname = self.get_ssh_client().command(
                        public_agents.pop().public_ip, ['hostname']).decode().strip('\n')
                    region_zone_map[hostname] = region + '-' + str(zones[z_i % z_mod])
                    z_i += 1
            for _ in range(info['num_private_agents']):
                if len(private_agents) > 0:
                    # distribute out the nodes across the zones until we run out
                    hostname = self.get_ssh_client().command(
                        private_agents.pop().public_ip, ['hostname']).decode().strip('\n')
                    region_zone_map[hostname] = region + '-' + str(zones[z_i % z_mod])
                    z_i += 1
            # now format the hostname-zone map into a BASH case statement
            for host, zone in region_zone_map.items():
                case_str += case_template.format(
                    hostname=host,
                    region=region,
                    zone=zone)

        # double escapes and curly brackets are needed for python interpretation
        bash_script = """
#!/bin/bash
hostname=$(hostname)
case $hostname in
{cases}
esac
echo "{{\\"fault_domain\\":{{\\"region\\":{{\\"name\\": \\"$REGION\\"}},\\"zone\\":{{\\"name\\": \\"$ZONE\\"}}}}}}"
"""
        return bash_script.format(cases=case_str)

    def wait(self):
        cluster = self.get_bare_cluster_launcher()
        cluster.wait()
        platforms.onprem.install_dcos(
            cluster,
            self.config['installer_url'],
            self.get_ssh_client(user='bootstrap_ssh_user'),
            self.get_ssh_client(),
            self.config['prereqs_script_path'],
            self.config['onprem_install_parallelism'],
            self.config['install_logs_enabled'])

    def describe(self):
        """ returns host information stored in the config as
        well as the basic provider info
        """
        cluster = self.get_onprem_cluster()
        return {
            'bootstrap_host': dcos_launch.util.convert_host_list([cluster.bootstrap_host])[0],
            'masters': dcos_launch.util.convert_host_list(cluster.get_master_ips()),
            'private_agents': dcos_launch.util.convert_host_list(cluster.get_private_agent_ips()),
            'public_agents': dcos_launch.util.convert_host_list(cluster.get_public_agent_ips())}

    def delete(self):
        """ just deletes the hardware
        """
        self.get_bare_cluster_launcher().delete()

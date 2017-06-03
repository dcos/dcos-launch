""" Script that runs through the installation procedure and raises an error if
it fails. This also outputs a cluster info JSON for dcos-launch to run tests after
this has completed.
"""
import json
import logging
import os
import sys
import time

import pkg_resources
import pytest
import yaml

import dcos_launch
from dcos_launch import config
from dcos_test_utils import helpers, onprem, ssh_client

log = logging.getLogger(__name__)


class DcosCliInstaller():
    """ This class binds an SSH client to some installer meta data
    so that commands can stream unbuffered to stdout without boilerplate
    """
    def __init__(self, host: str, installer_path: str, ssh: ssh_client.SshClient):
        self.host = host
        self.ssh = ssh
        self.installer_path = installer_path

    def run_cli_cmd(self, cli_option: str):
        log.info('Running installer with: {}'.format(cli_option))
        return self.ssh_command(['bash', self.installer_path, cli_option], stdout=sys.stdout.buffer)

    def ssh_command(self, *args, **kwargs):
        return self.ssh.command(self.host, *args, **kwargs)

    def copy_to_host(self, src_path, dst_path):
        with self.ssh.tunnel(self.host) as tunnel:
            tunnel.copy_file(src_path, dst_path)

    def genconf(self):
        self.run_cli_cmd('--genconf')

    def preflight(self):
        self.run_cli_cmd('--preflight')

    def install_prereqs(self):
        self.run_cli_cmd('--install-prereqs')

    def deploy(self):
        self.run_cli_cmd('--deploy')

    def postflight(self):
        self.run_cli_cmd('--postflight')

    def generate_node_upgrade_script(self, version):
        # tunnel run_cmd calls check_output which returns the output hence returning this
        return self.run_cli_cmd("--generate-node-upgrade-script " + version)


@pytest.fixture(scope='session')
def onprem_launcher():
    launcher = dcos_launch.get_launcher(config.get_validated_config(
        os.environ['TEST_LAUNCH_CONFIG_PATH']))
    if launcher.config['provider'] != 'onprem':
        pytest.skip('Must use a launch config with `provider: onprem` to run this test')
    if launcher.config['platform'] != 'aws':
        pytest.skip('Must use a launch config with `platform: aws` to run this test')
    return launcher


@pytest.fixture(scope='session')
def onprem_cluster(onprem_launcher):
    # need to get bare_cluster launcher to call wait as onprem_launcher will
    # install dcos via API during wait and we want the CLI to do this
    bare_cluster_launcher = onprem_launcher.get_bare_cluster_launcher()
    info = bare_cluster_launcher.create()
    with open(os.getenv('TEST_CLUSTER_INFO_PATH', 'test_cluster_info.json'), 'w') as f:
        json.dump(info, f)
    log.info('Sleeping for 3 minutes as cloud provider creates bare cluster..')
    time.sleep(180)
    bare_cluster_launcher.wait()
    return onprem_launcher.get_onprem_cluster()


@pytest.mark.skipif(
    'TEST_LAUNCH_CONFIG_PATH' not in os.environ,
    reason='TEST_LAUNCH_CONFIG_PATH must be set to point to a config YAML to launch')
@pytest.mark.skipif(
    os.environ.get('TEST_CREATE_CLUSTER') != 'true',
    reason='TEST_CREATE_CLUSTER must be set to run this test!')
def test_installer_cli(onprem_cluster, onprem_launcher):
    host = onprem_cluster.bootstrap_host.public_ip
    ssh = onprem_launcher.get_ssh_client()

    log.info('Verifying SSH-connectivity to cluster')
    for h in onprem_cluster.hosts:
        ssh.wait_for_ssh_connection(h.public_ip)

    log.info('Setting up installer host')
    home_dir = ssh.get_home_dir(host)
    ssh.add_ssh_user_to_docker_users(host)

    genconf_dir = os.path.join(home_dir, 'genconf')
    ssh.command(host, ['mkdir', '-p', genconf_dir])

    installer_path = os.path.join(home_dir, 'dcos_generate_config.sh')
    onprem.download_dcos_installer(
        ssh,
        host,
        installer_path,
        onprem_launcher.config['installer_url'])
    cli_installer = DcosCliInstaller(host, installer_path, ssh)
    log.info('Installer is ready for use!')

    # Start with minimal, default config, and then inject user settings
    test_config = {
        'cluster_name': 'SSH Installed DC/OS',
        'bootstrap_url': 'file:///opt/dcos_install_tmp',
        'master_discovery': 'static',
        'master_list': [m.private_ip for m in onprem_cluster.masters],
        'ssh_user': onprem_launcher.config['ssh_user'],
        'agent_list': [a.private_ip for a in onprem_cluster.private_agents],
        'platform': 'aws',
        'rexray_config_preset': 'aws',
        'public_agent_list': [a.private_ip for a in onprem_cluster.public_agents],
        'exhibitor_storage_backend': 'static'}
    test_config.update(onprem_launcher.config['dcos_config'])

    # explicitly transfer the files to be in the designated paths on the host
    log.info('Transfering config.yaml')
    cli_installer.copy_to_host(
        helpers.session_tempfile(
            yaml.dump(test_config).encode()), os.path.join(genconf_dir, 'config.yaml'))

    log.info('Transfering ip-detect script')
    ip_detect_script = pkg_resources.resource_string('dcos_test_utils', 'ip-detect/aws.sh')
    cli_installer.copy_to_host(
        helpers.session_tempfile(ip_detect_script), os.path.join(genconf_dir, 'ip-detect'))

    log.info('Transferring deployment SSH key')
    cli_installer.copy_to_host(
        helpers.session_tempfile(
            onprem_launcher.config['ssh_private_key'].encode()), os.path.join(genconf_dir, 'ssh_key'))
    cli_installer.ssh_command(['chmod', '600', os.path.join(genconf_dir, 'ssh_key')])

    log.info('Running installation procedure')
    cli_installer.genconf()
    cli_installer.install_prereqs()
    cli_installer.preflight()
    cli_installer.deploy()
    cli_installer.postflight()

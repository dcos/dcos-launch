import logging
import os
import random

import pkg_resources
import retrying
import yaml

import dcos_test_utils
import dcos_test_utils.onprem
from dcos_test_utils.helpers import session_tempfile

log = logging.getLogger(__name__)


@retrying.retry(
    wait_fixed=1000 * 10,
    retry_on_result=lambda result: result is False)
def wait_for_mesos_metric(cluster, host, key, value):
    """Return True when host's Mesos metric key is equal to value."""
    if host in cluster.masters:
        port = 5050
    else:
        port = 5051
    log.info('Polling metrics snapshot endpoint')
    response = cluster.get('/metrics/snapshot', host=host, port=port)
    return response.json().get(key) == value


def upgrade_dcos(
        dcos_api_session: dcos_test_utils.dcos_api_session.DcosApiSession,
        onprem_cluster: dcos_test_utils.onprem.OnpremCluster,
        starting_version: str,
        installer_url: str,
        user_config: dict,
        platform: str) -> None:
    """ Performs the documented upgrade process on a cluster

    Note: This is intended for testing purposes only and is an irreversible process

    Args:
        dcos_api_session: API session object capable of authenticating with the
            upgraded DC/OS cluster
        onprem_cluster: SSH-backed onprem abstraction for the cluster to be upgraded
        installer_url: URL for the installer to drive the upgrade
        user_config: this function already creates a viable upgrade config based on
            the onprem_cluster, but overrides can be provided via this dict
        platform: this must be `aws` as no other platform is currently supported
    """
    assert platform == 'aws', 'AWS is the only supported platform backend currently'

    ssh_client = onprem_cluster.ssh_client

    # kill previous genconf on bootstrap host if it is still running
    bootstrap_host = onprem_cluster.bootstrap_host.public_ip
    log.info('Killing any previous installer before starting upgrade')
    previous_installer = ssh_client.command(
        bootstrap_host,
        ['docker', 'ps', '--quiet', '--filter', 'name=dcos-genconf', '--filter', 'status=running']).decode().strip()
    if previous_installer:
        ssh_client.command(
            bootstrap_host,
            ['docker', 'kill', previous_installer])

    bootstrap_home = ssh_client.get_home_dir(bootstrap_host)

    log.info('Clearing out old installation files')
    genconf_dir = os.path.join(bootstrap_home, 'genconf')
    ssh_client.command(bootstrap_host, ['sudo', 'rm', '-rf', genconf_dir])
    ssh_client.command(bootstrap_host, ['mkdir', genconf_dir])
    installer_path = os.path.join(bootstrap_home, 'dcos_generate_config.sh')
    dcos_test_utils.onprem.download_dcos_installer(ssh_client, bootstrap_host, installer_path, installer_url)

    log.info('Starting ZooKeeper on the bootstrap node')
    zk_host = onprem_cluster.start_bootstrap_zk()
    # start the nginx that will host the bootstrap files
    bootstrap_url = 'http://' + onprem_cluster.start_bootstrap_nginx()

    with ssh_client.tunnel(bootstrap_host) as tunnel:
        log.info('Setting up upgrade config on bootstrap host')
        upgrade_config = {
            'cluster_name': 'My Upgraded DC/OS',
            'ssh_user': ssh_client.user,
            'master_discovery': 'static',
            'exhibitor_storage_backend': 'zookeeper',
            'exhibitor_zk_hosts': zk_host,
            'exhibitor_zk_path': '/exhibitor',
            'bootstrap_url': bootstrap_url,
            'rexray_config_reset': platform,
            'platform': platform,
            'master_list': [h.private_ip for h in onprem_cluster.masters],
            'agent_list': [h.private_ip for h in onprem_cluster.private_agents],
            'public_agent_list': [h.private_ip for h in onprem_cluster.public_agents]}
        upgrade_config.update(user_config)

        # transfer ip-detect and ssh key
        tunnel.copy_file(
            session_tempfile(
                yaml.dump(upgrade_config).encode()), os.path.join(bootstrap_home, 'genconf/config.yaml'))
        tunnel.copy_file(
            session_tempfile(
                ssh_client.key.encode()), os.path.join(bootstrap_home, 'genconf/ssh_key'))
        tunnel.command(['chmod', '600', os.path.join(bootstrap_home, 'genconf/ssh_key')])
        ip_detect_script = pkg_resources.resource_string(
            'dcos_test_utils', 'ip-detect/{}.sh'.format(platform)).decode('utf-8')
        tunnel.copy_file(session_tempfile(ip_detect_script.encode()), os.path.join(bootstrap_home, 'genconf/ip-detect'))

        log.info('Generating node upgrade script')
        upgrade_script_path = tunnel.command(
            ['bash', installer_path, '--generate-node-upgrade-script ' + starting_version]
        ).decode('utf-8').splitlines()[-1].split("Node upgrade script URL: ", 1)[1]

        log.info('Editing node upgrade script...')
        # Remove docker (and associated journald) restart from the install
        # script. This prevents Docker-containerized tasks from being killed
        # during agent upgrades.
        tunnel.command([
            'sudo', 'sed', '-i',
            '-e', '"s/systemctl restart systemd-journald//g"',
            '-e', '"s/systemctl restart docker//g"',
            bootstrap_home + '/genconf/serve/dcos_install.sh'])
        tunnel.command(['docker', 'restart', 'dcos-bootstrap-nginx'])
    # upgrading can finally start
    master_list = [host.public_ip for host in onprem_cluster.masters]
    private_agent_list = [host.public_ip for host in onprem_cluster.private_agents]
    public_agent_list = [host.public_ip for host in onprem_cluster.public_agents]
    upgrade_ordering = [
        # Upgrade masters in a random order.
        ('master', 'master', random.sample(master_list, len(master_list))),
        ('slave', 'agent', private_agent_list),
        ('slave_public', 'public agent', public_agent_list)]
    logging.info('\n'.join(
        ['Upgrade plan:'] +
        ['{} ({})'.format(host, role_name) for _, role_name, hosts in upgrade_ordering for host in hosts]
    ))
    for role, role_name, hosts in upgrade_ordering:
        log.info('Upgrading {} nodes: {}'.format(role_name, repr(hosts)))
        for host in hosts:
            log.info('Upgrading {}: {}'.format(role_name, repr(host)))
            ssh_client.command(
                host,
                [
                    'curl',
                    '--silent',
                    '--verbose',
                    '--show-error',
                    '--fail',
                    '--location',
                    '--keepalive-time', '2',
                    '--retry', '20',
                    '--speed-limit', '100000',
                    '--speed-time', '60',
                    '--remote-name', upgrade_script_path])
            ssh_client.command(host, ['sudo', 'bash', 'dcos_node_upgrade.sh'])
            wait_metric = {
                'master': 'registrar/log/recovered',
                'slave': 'slave/registered',
                'slave_public': 'slave/registered',
            }[role]
            log.info('Waiting for {} to rejoin the cluster...'.format(role_name))
            try:
                wait_for_mesos_metric(dcos_api_session, host, wait_metric, 1)
            except retrying.RetryError as exc:
                raise Exception(
                    'Timed out waiting for {} to rejoin the cluster after upgrade: {}'.
                    format(role_name, repr(host))
                ) from exc
    dcos_api_session.wait_for_dcos()

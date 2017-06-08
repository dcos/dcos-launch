import logging
import os
import random

import retrying

import dcos_test_utils
import dcos_test_utils.onprem

from dcos_test_utils import ssh_client

log = logging.getLogger(__name__)


@retrying.retry(
    wait_fixed=1000 * 10,
    retry_on_result=lambda result: result is False)
def wait_for_mesos_metric(cluster, host, key):
    """Return True when host's Mesos metric key is equal to value."""
    if host in cluster.masters:
        port = 5050
    else:
        port = 5051
    log.info('Polling metrics snapshot endpoint')
    # A CA cert may be set during the upgrade, so do not verify just in case
    response = cluster.get('/metrics/snapshot', host=host, port=port, verify=False)
    return response.json().get(key) == 1


def reset_bootstrap_host(ssh: ssh_client.SshClient, bootstrap_host: str):
    with ssh.tunnel(bootstrap_host) as t:
        log.info('Checking for previous installer before starting upgrade')
        home_dir = t.command(['pwd']).decode().strip()
        previous_installer = t.command(
            ['docker', 'ps', '--quiet', '--filter', 'name=dcos-genconf']).decode().strip()
        if previous_installer:
            log.info('Previous installer found, killing...')
            t.command(['docker', 'rm', '--force', previous_installer])
        t.command(['sudo', 'rm', '-rf', os.path.join(home_dir, 'genconf*'), os.path.join(home_dir, 'dcos*')])


def upgrade_dcos(
        dcos_api_session: dcos_test_utils.dcos_api_session.DcosApiSession,
        onprem_cluster: dcos_test_utils.onprem.OnpremCluster,
        starting_version: str,
        installer_url: str) -> None:
    """ Performs the documented upgrade process on a cluster

    (1) downloads installer
    (2) runs the --node-upgrade command
    (3) edits the upgrade script to allow docker to live
    (4) (a) goes to each host and starts the upgrade procedure
        (b) uses an API session to check the upgrade endpoint

    Note:
        - This is intended for testing purposes only and is an irreversible process
        - One must have all file-based resources on the bootstrap host before
            invoking this function

    Args:
        dcos_api_session: API session object capable of authenticating with the
            upgraded DC/OS cluster
        onprem_cluster: SSH-backed onprem abstraction for the cluster to be upgraded
        installer_url: URL for the installer to drive the upgrade

    TODO: This method is only supported when the installer has the node upgrade script
        feature which was not added until 1.9. Thus, add steps to do a 1.8 -> 1.8 upgrade
    """
    ssh_client = onprem_cluster.ssh_client

    bootstrap_host = onprem_cluster.bootstrap_host.public_ip

    # Fetch installer
    bootstrap_home = ssh_client.get_home_dir(bootstrap_host)
    installer_path = os.path.join(bootstrap_home, 'dcos_generate_config.sh')
    dcos_test_utils.onprem.download_dcos_installer(ssh_client, bootstrap_host, installer_path, installer_url)

    # check that we can use the bootstrap host as an HTTP server
    onprem_cluster.start_bootstrap_nginx()

    with ssh_client.tunnel(bootstrap_host) as tunnel:
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
                wait_for_mesos_metric(dcos_api_session, host, wait_metric)
            except retrying.RetryError as exc:
                raise Exception(
                    'Timed out waiting for {} to rejoin the cluster after upgrade: {}'.
                    format(role_name, repr(host))
                ) from exc

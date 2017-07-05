import getpass
import random
import socket
import subprocess
import uuid
from contextlib import contextmanager

import pytest
from retrying import retry

from dcos_test_utils.ssh_client import SshClient, open_tunnel


def can_connect(port):
    sock = socket.socket()
    sock.settimeout(0.1)  # Always localhost, should be wayy faster than this.
    try:
        sock.connect(('127.0.0.1', port))
        return True
    except OSError:
        return False


class SshdManager():
    def __init__(self, tmpdir):
        self.tmpdir = tmpdir
        self.sshd_config_path = str(tmpdir.join('sshd_config'))
        self.key_path = str(tmpdir.join('host_key'))
        subprocess.check_call(['ssh-keygen', '-f', self.key_path, '-t', 'rsa', '-N', ''])
        with open(self.key_path, 'r') as f:
            self.key = f.read().strip()

        config = [
            'Protocol 1,2',
            'RSAAuthentication yes',
            'PubkeyAuthentication yes',
            'StrictModes no',
            'LogLevel DEBUG']
        config.append('AuthorizedKeysFile {}'.format(tmpdir.join('host_key.pub')))
        config.append('HostKey {}'.format(self.key_path))

        with open(self.sshd_config_path, 'w') as f:
            f.write('\n'.join(config))

        assert tmpdir.join('host_key').check()
        assert tmpdir.join('host_key.pub').check()
        assert tmpdir.join('sshd_config').check()

    @contextmanager
    def run(self, count):
        # Get unique number of available TCP ports on the system
        sshd_ports = []
        for try_port in random.sample(range(10000, 11000), count):
            # If the port is already in use, skip it.
            while can_connect(try_port):
                try_port += 1
            sshd_ports.append(try_port)

        # Run sshd servers in parallel, cleaning up when the yield returns.
        subprocesses = []
        for port in sshd_ports:
            subprocesses.append(subprocess.Popen(
                ['/usr/sbin/sshd', '-p{}'.format(port), '-f{}'.format(self.sshd_config_path), '-e', '-D'],
                cwd=str(self.tmpdir)))

        # Wait for the ssh servers to come up
        @retry(stop_max_delay=1000, retry_on_result=lambda x: x is False)
        def check_server(port):
            return can_connect(port)

        for port in sshd_ports:
            check_server(port)

        yield sshd_ports

        # Stop all the subproceses. They are ephemeral temporary SSH connections, no point in being nice
        # with SIGTERM.
        for s in subprocesses:
            s.kill()


@pytest.fixture
def sshd_manager(tmpdir):
    return SshdManager(tmpdir)


@pytest.fixture
def tunnel_args(sshd_manager):
    with sshd_manager.run(1) as sshd_ports:
        yield {
            'user': getpass.getuser(),
            'key': sshd_manager.key,
            'host': '127.0.0.1',
            'port': sshd_ports[0]}


def test_ssh_client(tunnel_args, tmpdir):
    """ Copies data to 'remote' (localhost) and then commands to cat that data back
    """
    src_text = str(uuid.uuid4())
    src_file = tmpdir.join('src')
    src_file.write(src_text)
    dst_file = tmpdir.join('dst')
    read_cmd = ['cat', str(dst_file)]
    with open_tunnel(**tunnel_args) as t:
        t.copy_file(str(src_file), str(dst_file))
        dst_text = t.command(read_cmd).decode().strip()
    assert dst_text == src_text, 'retrieved destination file did not match source!'

    ssh_client = SshClient(tunnel_args['user'], tunnel_args['key'])
    ssh_client_out = ssh_client.command(tunnel_args['host'], read_cmd, port=tunnel_args['port']).decode().strip()
    assert ssh_client_out == src_text, 'SshClient did not produce the expected result!'

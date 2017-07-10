"""Test that the mesosphere/cloudcleaner docker seems to work."""
import subprocess


def test_docker():
    """Check that the container can run."""
    subproc = subprocess.Popen(
        ["docker", "run", "mesosphere/cloudcleaner"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    stdout, stderr = subproc.communicate()

    assert stderr.decode() == "" and stdout.decode().startswith("ERROR:") and subproc.returncode == 1

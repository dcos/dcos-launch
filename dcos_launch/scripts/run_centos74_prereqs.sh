sudo setenforce 1
sudo bash -c 'echo -e "nameserver 8.8.8.8\n" >> /etc/resolv.conf'

sudo yum install -y yum-utils \
  device-mapper-persistent-data \
  lvm2

sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
# Docker 17.05 is an edge release
sudo yum-config-manager --enable docker-ce-edge

# Docker 17.05 has a separate package for SELinux
sudo yum install -y --setopt=obsoletes=0 \
  docker-ce-17.05.0.ce-1.el7.centos \
  docker-ce-selinux-17.05.0.ce-1.el7.centos

# Previously, when using Docker Engine, we would use the overlay storage driver configured in /etc/systemd/system/docker.service.d/override.conf
# Now that we are using a Docker CE release, the recommended storage driver is overlay2 and configured in /etc/docker/daemon.json
# read more here: https://docs.docker.com/storage/storagedriver/overlayfs-driver/
sudo tee /etc/docker/daemon.json <<- EOF
{
  "storage-driver": "overlay2"
}
EOF

sudo systemctl start docker
sudo systemctl enable docker

sudo yum install -y wget
sudo yum install -y git
sudo yum install -y unzip
sudo yum install -y curl
sudo yum install -y xz
sudo yum install -y ipset
sudo yum install -y ntp
sudo systemctl enable ntpd
sudo systemctl start ntpd
sudo getent group nogroup || sudo groupadd nogroup
sudo getent group docker || sudo groupadd docker
sudo touch /opt/dcos-prereqs.installed


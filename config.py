import inspect
import os
import hashlib

from getpass import getuser
from socket import gethostname

DEFAULT_TIMEOUT = 60
SOURCE_DIR = os.path.dirname(inspect.getfile(inspect.currentframe()))
DEFAULT_KEY = os.path.join(SOURCE_DIR, 'openstack-test.key')

class Config(object):

    def __init__(self):
        # Hosts to run this test on. All should be running OpenStack and have
        # VMS installed. The versions of OpenStack and VMS should correspond to
        # vms_version and openstack_version respectively. There should be at
        # least two.
        self.hosts = ['node10', 'node9']
        # Hosts without OpenStack installed. There should be at least one.
        self.hosts_without_openstack = ['xdev']

        # Instance flavor; determines RAM and what disks are attached.
        self.flavor_name = 'm1.tiny'
        # Name of the key to inject into the instances. Only Ubuntu Enterprise
        # Cloud images support this. Currently, none of our tests rely on an
        # injected key. Instead, we assume that the Image instances have the
        # public key corresponding to Image.guest_key_path.
        self.guest_key_name = 'openstack-test'
        # The version of openstack running on the hosts. Either "diablo" or
        # "essex".
        self.openstack_version = "essex"
        # A username on hosts that has passwordless sudo.
        self.host_user = "tester"
        # The private SSH key for host_user on all of the hosts.
        self.host_key_path = os.path.join(SOURCE_DIR, 'openstack-test.key')
        # How long to wait for servers to come up, become ping-able, ssh-able,
        # etc. In seconds.
        self.ops_timeout = DEFAULT_TIMEOUT
        # The ABI version of the agent to install on the master servers. The
        # latest build of the specified agent is installed on each master.
        self.agent_version = '1'
        # The version of VMS installed on the cluster.
        self.vms_version = '2.4'
        # The arch to use for non-arch tests (i.e., tests that aren't sensitive
        # to the arch).
        self.default_archs=['64']
        # The distro to use for non-distro tests (i.e., tests that aren't
        # sensitive to the distro).
        self.default_distros=['cirros']
        # Name to prefix to all of the tests. Defaults to Jenkins-$BUILD_NUMBER
        # if BUILD_NUMBER is set in the env. Otherwise, defaults to
        # $USER@$HOST-$PPID-$PID.
        self.run_name = None

        # The images available in Glance for the tests to use. The tests need
        # images of certain distributions for certain architectures; hence the
        # image names aren't important. See Image.
        self.images = [
            # Lean & mean cirros image.
            Image('cirros-0.3.0-x86_64', distro='cirros', arch='64', user='cirros'),

            # Ubuntu images
            Image('oneiric-agent-ready', distro='ubuntu', arch='64', user='ubuntu'),
            Image('precise-32bit-agent-ready', distro='ubuntu', arch='32', user='root'),
            Image('precise-PAE-agent-ready', distro='ubuntu', arch='pae', user='root'),
            # CentOS images
            Image('centos-6.3-amd64-agent-ready', distro='centos', arch='64', user='root'),
            Image('centos-6.3-32bit-agent-ready', distro='centos', arch='32', user='root'),
            Image('centos-6.3-PAE-agent-ready', distro='centos', arch='pae', user='root'),
        ]

    def get_all_archs(self):
        return list(set([i.arch for i in self.images]))

    def get_all_distros(self):
        return list(set([i.distro for i in self.images]))

    def post_config(self):
        if self.run_name == None:
            if os.getenv('BUILD_NUMBER'):
                self.run_name = 'Jenkins-%s' % os.getenv('BUILD_NUMBER')
            else:
                pid = os.getpid()
                ppid = os.getppid()
                user = getuser()
                host = gethostname()
                self.run_name = '%s@%s-%d-%d' % (user, host, ppid, pid)

        for image in self.images:
            if image.key == None:
                image.key = DEFAULT_KEY

    def get_images(self, distro, arch):
        return filter(lambda i: i.distro == distro and i.arch == arch,
                      self.images)

    def hostname_to_id(self, tenant_id, hostname):
        if self.openstack_version == "essex":
            return hashlib.sha224(str(tenant_id) + str(hostname)).hexdigest()
        else:
            return hashlib.sha224(str(hostname)).hexdigest()

    def id_to_hostname(self, tenant_id, id):
        for host in self.hosts:
            if self.hostname_to_id(tenant_id, host) == id:
                return host
        raise KeyError(id)

    def other_hosts(self, hostname=None, hostId=None, tenant_id=None):
        if hostname == None:
            hostname = id_to_hostname(tenant_id, hostId)
        return [host for host in self.hosts if host != hostname]

    def parse_vms_version(self):
        (major, minor) = [ int(x) for x in self.vms_version.split('.')[:2] ]
        return (major, minor)

class Image(object):
    '''Add an image. Fields specified with comma-separated key=val pairs.

    name: the name of the image in glance
    distro: the linux distribution: use ubuntu, centos, or cirros
    arch: the architecture -- use 32, 64, or pae
    user: the user to login as, must have passwordless sudo
    key: the path to the SSH key for the user; omit to use the default

    e.g., --image 11.10-a1-64,distro=ubuntu,user=ubuntu,arch=64
      '''
    def __init__(self, name, distro, arch, user=None, key=None):
        self.name = name
        self.distro = distro
        self.arch = arch
        self.user = user
        self.key = key

    def __repr__(self):
        return 'Image(name=%s, distro=%s, arch=%s, user=%s, key=%s)' % \
                (self.name, self.distro, self.arch, self.user, self.key)

default_config = Config()

import inspect
import os
import hashlib

from getpass import getuser
from socket import gethostname

DEFAULT_KEY_PATH = os.path.join(os.getenv('HOME'), '.ssh', 'id_rsa')

class Image(object):
    '''Add an image.
Fields are specified with comma-separated key=val pairs:
name -- the name of the image in glance,
distro -- the linux distribution,
arch -- the architecture,
user -- the user to login as,
key_path -- the path to the SSH key for the user,
key_name -- the name of the key for booting.
e.g. --image 11.10-a1-64,distro=ubuntu,user=ubuntu,arch=64
'''
    def __init__(self, name, distro, arch, user='root', key_path=None, key_name=None):
        self.name = name
        self.distro = distro
        self.arch = arch
        self.user = user
        self.key_path = key_path
        self.key_name = key_name

    def check(self):
        assert self.distro
        assert self.arch
        assert self.user
        assert self.key_path

    def __repr__(self):
        return 'Image(name=%s, distro=%s, arch=%s, user=%s, key_path=%s, key_name=%s)' % \
                (self.name, self.distro, self.arch, self.user, self.key_path, self.key_name)

class Config(object):

    def __init__(self):
        # Hosts in the OpenStack cluster. These are automatically
        # inferred if you access the cluster with an administrator.
        self.hosts = []

        # Hosts without OpenStack installed. There should be at least one.
        self.hosts_without_openstack = [gethostname()]

        # Instance flavor; determines RAM and what disks are attached.
        self.flavor_name = 'm1.tiny'

        # Name of the key to inject into the instances. You may use either
        # this mechanism to inject a guest key, or save some images with a
        # key preprovisioned. Both are acceptable.
        self.guest_key_name = None

        # The default key path for guests where it is not explicitly provided.
        self.guest_key_path = DEFAULT_KEY_PATH

        # Some tests will ssh to the hosts and ensure that the state is as
        # expected. This will happen using the host_user and the host_key_path
        # below.
        self.host_user = None
        self.host_key_path = DEFAULT_KEY_PATH

        # How long to wait for servers to come up, become ping-able, ssh-able,
        # etc. In seconds.
        self.ops_timeout = 600

        # A custom agent location (passed to the gc-install-agent command).
        self.agent_location = None
        self.agent_version  = 'latest'

        # The arch to use for non-arch tests (i.e., tests that aren't sensitive
        # to the arch).
        self.default_archs = []

        # The distro to use for non-distro tests (i.e., tests that aren't
        # sensitive to the distro).
        self.default_distros = []

        # Name to prefix to all of the tests. Defaults to the environment
        # variable RUN_NAME if available, otherwise one is constructed from
        # the current host, user and pid.
        self.run_name = None

        # The images available in Glance for the tests to use. The tests need
        # images of certain distributions for certain architectures; hence the
        # image names aren't important. See Image.
        # 
        # We no longer store defaults here in this repo, but as an example:
        #   Image('cirros-0.3.0-x86_64', distro='cirros', arch='64', user='cirros'),
        #   Image('oneiric-agent-ready', distro='ubuntu', arch='64', user='ubuntu'),
        #   Image('precise-32-agent-ready', distro='ubuntu', arch='32', user='root'),
        #   Image('precise-pae-agent-ready', distro='ubuntu', arch='pae', user='root'),
        #   Image('centos-6.3-64-agent-ready', distro='centos', arch='64', user='root'),
        #   Image('centos-6.3-32-agent-ready', distro='centos', arch='32', user='root'),
        #   Image('centos-6.3-pae-agent-ready', distro='centos', arch='pae', user='root'),
        self.images = []

        # Whether to leave the VMs around on failure.
        self.leave_on_failure = False

    def get_all_archs(self):
        return list(set([i.arch for i in self.images]))

    def get_all_distros(self):
        return list(set([i.distro for i in self.images]))

    def post_config(self):
        if self.run_name == None:
            if os.getenv('RUN_NAME'):
                self.run_name = os.getenv('RUN_NAME')
            else:
                pid = os.getpid()
                ppid = os.getppid()
                user = getuser()
                host = gethostname()
                self.run_name = '%s@%s-%d-%d' % (user, host, ppid, pid)

        archs = []
        distros = []
        for image in self.images:
            if not(image.arch) in archs:
                archs.append(image.arch)
            if not(image.distro) in distros:
                distros.append(image.distro)
            if image.key_name == None:
                image.key_name = self.guest_key_name
            if image.key_path == None:
                image.key_path = self.guest_key_path
        if len(self.default_archs) == 0:
            self.default_archs = archs
        if len(self.default_distros) == 0:
            self.default_distros = distros

    def get_images(self, distro, arch):
        return filter(lambda i: i.distro == distro and i.arch == arch, self.images)

    def hostname_to_ids(self, tenant_id, hostname):
        essex_hash  = hashlib.sha224(str(tenant_id) + str(hostname)).hexdigest()
        diablo_hash = hashlib.sha224(str(hostname)).hexdigest()
        print "hostname hashes for %s" % hostname
        print "essex = %s" % essex_hash
        print "diablo = %s" % diablo_hash
        return [essex_hash, diablo_hash]

    def id_to_hostname(self, tenant_id, host_id):
        for hostname in self.hosts:
            if host_id in self.hostname_to_ids(tenant_id, hostname):
                return hostname
        raise KeyError(host_id)

default_config = Config()

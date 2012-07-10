import inspect
import os
import hashlib

class Config(object):

    def __init__(self):
        # Path to the git repo for openstack-test.
        self.data_path = os.path.dirname(inspect.getfile(inspect.currentframe()))

        # Hosts to run this test on.
        self.hosts = ['node10', 'node9']
        self.hosts_without_openstack = ['xdev']

        self.flavor_name = 'm1.tiny'
        self.image_name = 'uec-oneiric-vmsagent3-root'
        self.guest_distro = "ubuntu" # Or rpm
        self.guest_has_agent = True
        self.key_name = 'openstack-test'
        self.key_path = os.path.join(self.data_path, 'openstack-test.key')
        self.guest_user = 'ubuntu'
        self.openstack_version = "essex"
        self.host_user = "tester"

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

default_config = Config()

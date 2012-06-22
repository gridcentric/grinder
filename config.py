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
        self.key_name = 'openstack-test'
        self.key_path = os.path.join(self.data_path, 'openstack-test.key')
        self.guest_user = 'ubuntu'
        self.openstack_version = "essex"

        self.build_server = '********'
        self.build_username = '********'
        self.build_password = '********'
        self.vms_project = 'Libvirt'
        self.openstack_project = 'Essex'
        self.package_tmp_dir = '.tmp'

        self.vms_packages = [
            ('vmsfs', 'vmsfs[0-9._]+amd64\.deb'),
            ('vms-kvm', 'vms-kvm[0-9._]+amd64\.deb'),
            ('vms', 'vms[0-9._]+-ubuntu1-py27_amd64\.deb'),
            ('vms-libvirt', 'vms-libvirt[0-9._]+amd64\.deb'),
            ('mcdist', 'mcdist[0-9._]+amd64\.deb'),
            ('vms-mcdist', 'vms-mcdist[0-9._]+amd64\.deb')]

        self.openstack_packages = [
            ('nova-gridcentric', 'nova-gridcentric_[0-9.]+-ubuntu[0-9.]+py2.7_all\.deb')]

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

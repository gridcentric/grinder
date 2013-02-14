# Copyright 2013 GridCentric Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import time
import random

from . logger import log
from . util import Notifier
from . shell import SecureShell
from . shell import RootShell
from . host import Host
from . vmsctl import Vmsctl
from . breadcrumbs import Breadcrumbs
from . util import fix_url_for_yum
from . util import wait_for
from . util import wait_for_ping
from . shell import wait_for_ssh
from . requirements import AVAILABILITY_ZONE

from novaclient.exceptions import NotFound

def wait_while_status(server, status):
    def condition():
        if server.status != status:
            return True
        server.get()
        return False
    wait_for('%s on ID %s to finish' % (status, str(server.id)), condition)

def wait_while_exists(server):
    def condition():
        try:
            server.get()
            return False
        except NotFound:
            return True
    wait_for('server %s to not exist' % server.id, condition)

def get_addrs(server):
    ips = []
    for network in server.networks.values():
        ips.extend(network)
    return ips

class Instance(Notifier):

    def __init__(self, harness, server, image_config,
                 breadcrumbs=None, snapshot=None):
        Notifier.__init__(self)
        self.harness = harness
        self.server = server
        self.image_config = image_config
        self.image_config.check()
        self.id = server.id
        self.snapshot = snapshot
        if breadcrumbs == None:
            self.wait_for_boot()
            self.breadcrumbs = Breadcrumbs(self)
        else:
            self.breadcrumbs = breadcrumbs

    def wait_for_boot(self, status='ACTIVE'):
        self.wait_while_status('BUILD')
        assert self.get_status() == status
        if status == 'ACTIVE':
            wait_for_ping(self.get_addrs())
            wait_for_ssh(self.get_shell())

    def wait_while_host(self, host):
        wait_for('%s to not be on host %s' % (self, host),
                 lambda: self.get_host().id != host.id)

    def wait_for_migrate(self, host, dest):
        self.wait_while_host(host)
        self.wait_while_status('MIGRATING')
        self.assert_alive(dest)
        self.breadcrumbs.add('post migration to %s' % dest.id)

    def wait_while_status(self, status):
        wait_while_status(self.server, status)

    def wait_while_exists(self):
        wait_while_exists(self.server)

    def wait_for_bless(self):
        self.wait_while_status('BUILD')
        assert self.get_status() == 'BLESSED'
        # Test issue #152. The severs/detail and servers/<ID> were returning
        # difference statuses for blessed servers. servers.get() retrieves
        # servers/<ID> and servers.list() retrieves servers/detail.
        for server in self.harness.client.servers.list():
            if server.id == self.id:
                assert server.status == 'BLESSED'
                break
        else:
            assert False

    def __str__(self):
        return 'Instance(name=%s, id=%s)' % (self.server.name, self.id)

    def root_command(self, command, **kwargs):
        ssh = RootShell(self.get_addrs()[0],
                        self.image_config.key_path,
                        self.image_config.user)
        return ssh.check_output(command, **kwargs)

    def get_host(self):
        self.server.get()
        hostname = getattr(self.server, 'OS-EXT-SRV-ATTR:host', None)
        if hostname:
            if not(hostname in self.harness.config.hosts):
                self.harness.config.hosts.append(hostname)
            return Host(hostname, self.harness.config)
        else:
            return Host(self.harness.config.id_to_hostname(self.server.tenant_id, self.server.hostId))

    def get_shell(self):
        return SecureShell(self.get_addrs()[0],
                           self.image_config.key_path,
                           self.image_config.user)

    def get_status(self):
        self.server.get()
        return self.server.status

    def get_ram(self):
        flavor = self.harness.client.flavors.find(name=self.harness.config.flavor_name)
        return flavor.ram

    def get_addrs(self):
        return get_addrs(self.server)

    def get_raw_id(self):
        """
        Returns the id of the server. In Essex the actual id of the server is
        never returned, only the uuid from the nova-api. This figures out what
        the id should be.
        """
        self.server.get()
        instance_name = getattr(self.server, 'OS-EXT-SRV-ATTR:instance_name', None)
        if instance_name:
            # Essex and later encode the name in an extended attribute.
            _, _, hex_id = instance_name.rpartition("-")
            try:
                return int(hex_id, 16)
            except ValueError:
                log.error("Failed to determine id of server %s" % str(self))
        else:
            # In diablo the id really is the id.
            return self.server.id

    def get_vms_id(self):
        host = self.get_host()
        osid = '%08x' % self.get_raw_id()
        (stdout, stderr) = \
            host.check_output('ps aux | grep qemu-system | grep %s | grep -v ssh | grep -v ssh' % osid)
        return int(stdout.split('\n')[0].strip().split()[1])

    def get_iptables_rules(self, host=None):
        if host == None:
            host = self.get_host()

        server_id = self.get_raw_id()

        # Check if the server has iptables rules.
        return host.get_nova_compute_instance_filter_rules(server_id)

    @Notifier.notify
    def bless(self):
        log.info('Blessing %s', self)
        self.breadcrumbs.add('Pre bless')
        blessed_list = self.harness.gcapi.bless_instance(self.server)
        assert len(blessed_list) == 1
        blessed = blessed_list[0]

        # Sanity checks on the blessed instance.
        assert blessed['id'] != self.id
        assert str(blessed['metadata']['blessed_from']) == str(self.id)
        assert blessed['name'] != self.server.name
        assert self.server.name in blessed['name']
        assert blessed['status'] in ['BUILD', 'BLESSED']

        snapshot = self.breadcrumbs.snapshot()
        server = self.harness.client.servers.get(blessed['id'])
        instance = Instance(self.harness, server, self.image_config,
                            breadcrumbs=False, snapshot=snapshot)

        instance.wait_for_bless()
        self.breadcrumbs.add('Post bless, child is %s' % instance.id)

        return instance

    @Notifier.notify
    def launch(self, target=None, guest_params=None, status='ACTIVE', name=None,
               user_data=None, security_groups=None, availability_zone=None):
        log.info("Launching from %s with target=%s guest_params=%s status=%s"
                  % (self, target, guest_params, status))
        params = {}
        if target != None:
            params['target'] = target
        if guest_params != None:
            params['guest'] = guest_params
        if name != None:
            params['name'] = name
        if user_data != None:
            params['user_data'] = user_data
        if security_groups != None:
            params['security_groups'] = security_groups

        # Folsom and later: pick the host, has to fall within the provided list
        if AVAILABILITY_ZONE.check(self.harness.client, self.harness.gcapi):
            if availability_zone is None:
                target_host = random.choice(self.harness.config.hosts)
                availability_zone = Host(target_host, self.harness.config).host_az()
                log.debug("Launching to host %s -> %s." %\
                            (target_host, availability_zone))
            params['availability_zone'] = availability_zone

        launched_list = self.harness.gcapi.launch_instance(self.server, params=params)

        # Verify the metadata returned by nova-gc.
        assert len(launched_list) == 1
        launched = launched_list[0]
        assert launched['id'] != self.id
        assert launched['status'] in [status, 'BUILD']

        if name == None:
            assert launched['name'] != self.server.name
            assert self.server.name in launched['name']
        else:
            assert launched['name'] == name

        # Retrieve the server from nova-compute. It should have our metadata added.
        server = self.harness.client.servers.get(launched['id'])
        assert server.metadata['launched_from'] == str(self.id)

        # Build the instance.
        breadcrumbs = self.snapshot.instantiate(get_addrs(server))
        instance = Instance(self.harness, server, self.image_config,
                            breadcrumbs=breadcrumbs, snapshot=None)
        instance.wait_for_boot(status)

        # Folsom and later: if the availability zone targeted a specific host, verify
        if AVAILABILITY_ZONE.check(self.harness.client, self.harness.gcapi):
            if ':' in availability_zone:
                target_host = availability_zone.split(':')[1]
                assert instance.get_host().id == target_host

        return instance

    def assert_alive(self, host=None):
        assert self.get_status() == 'ACTIVE'
        if host != None:
            assert self.get_host().id == host.id
        wait_for_ping(self.get_addrs())
        wait_for_ssh(self.get_shell())
        if host != None:
            self.breadcrumbs.add('alive on host %s' % host.id)
        else:
            self.breadcrumbs.add('alive')

    @Notifier.notify
    def migrate(self, host, dest):
        log.info('Migrating %s from %s to %s', self, host, dest)
        self.assert_alive(host)
        pre_migrate_iptables = self.get_iptables_rules(host)
        self.breadcrumbs.add('pre migration to %s' % dest.id)
        self.harness.gcapi.migrate_instance(self.server, dest.id)
        self.wait_for_migrate(host, dest)
        # Assert that the iptables rules have been cleaned up.
        time.sleep(1.0)
        assert (False, []) == self.get_iptables_rules(host)
        assert pre_migrate_iptables == self.get_iptables_rules(dest)

    @Notifier.notify
    def delete(self, recursive=False):
        if recursive:
            for id in self.list_blessed():
                instance = Instance(self.harness, self.harness.client.servers.get(id),
                                    self.image_config, breadcrumbs=False)
                instance.discard(recursive=True)
        log.info('Deleting %s', self)
        self.server.delete()
        self.wait_while_exists()

    @Notifier.notify
    def discard(self, recursive=False):
        if recursive:
            for id in self.list_launched():
                instance = Instance(self.harness, self.harness.client.servers.get(id),
                                    self.image_config, breadcrumbs=False)
                instance.delete(recursive=True)
                time.sleep(1.0) # Sleep after the delete.
        log.info('Discarding %s', self)
        self.harness.gcapi.discard_instance(self.server)
        self.wait_while_exists()

    def list_blessed(self):
        return map(lambda x: x['id'], self.harness.gcapi.list_blessed_instances(self.server))

    def list_launched(self):
        return map(lambda x: x['id'], self.harness.gcapi.list_launched_instances(self.server))

    def install_agent(self):
        if self.image_config.distro in ["centos", "rpm"] and\
           self.harness.config.agent_location is not None:
                agent_location = fix_url_for_yum(self.harness.config.agent_location)
        else:
            agent_location = self.harness.config.agent_location
        self.harness.gcapi.install_agent(self.server,
                                         user=self.image_config.user,
                                         key_path=self.image_config.key_path,
                                         location=agent_location,
                                         version=self.harness.config.agent_version)
        self.breadcrumbs.add("Installed agent version %s" % self.harness.config.agent_version)
        self.assert_agent_running()

    def remove_agent(self):
        # Remove package, ensure its paths are gone.
        # Principally, we want to see that removing works, and that
        # reinstallation and upgrades work.
        REMOVE_COMMAND = " \
            dpkg -r vms-agent || \
            rpm -e vms-agent || \
            (/etc/init.d/vmsagent stop && rm -rf /var/lib/vms)"
        self.root_command(REMOVE_COMMAND)
        self.breadcrumbs.add("Removed agent")
        self.assert_agent_not_running()

    def assert_agent_running(self):
        self.root_command("pidof vmsagent")

    def assert_agent_not_running(self):
        self.root_command("pidof vmsagent", expected_rc=1)

    def drop_caches(self):
        self.root_command("sh", input = "echo 3 > /proc/sys/vm/drop_caches")

    def vmsctl(self):
        return Vmsctl(self)

    def add_security_group(self, *args, **kwargs):
        return self.server.add_security_group(*args, **kwargs)

    def remove_security_group(self, *args, **kwargs):
        return self.server.remove_security_group(*args, **kwargs)

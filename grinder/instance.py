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

import json
import time
import random
import tempfile

from . logger import log
from . util import Notifier
from . shell import SecureShell
from . shell import RootShell
from . shell import WinShell
from . host import Host
from . vmsctl import Vmsctl
from . breadcrumbs import SSHBreadcrumbs
from . breadcrumbs import LinkBreadcrumbs
from . util import fix_url_for_yum
from . util import wait_for
from . util import wait_for_ping
from . util import wait_while_status
from . util import wait_for_status
from . util import wait_while_exists
from . shell import wait_for_shell
from . requirements import AVAILABILITY_ZONE, SCHEDULER_HINTS

def get_addrs(server, network=None):
    log.debug('get_addrs network=%s: %s', network, server.networks)
    if network != None:
        return server.networks[network]
    else:
        ips = []
        for network in server.networks.values():
            ips.extend(network)
        return ips

class InstanceFactory(object):

    @staticmethod
    def create(harness, server, image_config, **kwargs):
        ''' Instantiates an specific instance subtype based on the image's platform. '''
        platform = image_config.platform

        if platform == "windows":
            log.debug("Creating Windows instance.")
            return WindowsInstance(harness, server, image_config , **kwargs)
        elif platform == "linux":
            log.debug("Creating Linux instance.")
            return LinuxInstance(harness, server, image_config, **kwargs)
        else:
            raise ValueError("Unknown platform '%s'. " % platform +
                             "Currently supported platforms are 'windows' and 'linux'.")

class Instance(Notifier):

    def __init__(self, harness, server, image_config,
                 breadcrumbs=None, snapshot=None, keypair=None):
        Notifier.__init__(self)
        self.harness = harness
        self.server = server
        self.image_config = image_config
        self.image_config.check()
        self.id = server.id
        self.snapshot = snapshot
        self.breadcrumbs = breadcrumbs
        self.volumes = []

        if keypair is not None:
            self.privkey_fd = tempfile.NamedTemporaryFile()
            self.privkey_fd.write(keypair.private_key)
            self.privkey_fd.flush()
            self.privkey_path = self.privkey_fd.name
        else:
            self.privkey_path = self.image_config.key_path

    def wait_for_boot(self, status='ACTIVE'):
        self.wait_while_status('BUILD')
        assert self.get_status() == status
        if status == 'ACTIVE':
            self.instance_wait_for_ping()
            wait_for_shell(self.get_shell())

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
        for server in self.harness.nova.servers.list():
            if server.id == self.id:
                assert server.status == 'BLESSED'
                break
        else:
            assert False

    def __str__(self):
        return 'Instance(name=%s, id=%s)' % (self.server.name, self.id)

    def get_host(self):
        self.server.get()
        hostname = getattr(self.server, 'OS-EXT-SRV-ATTR:host', None)
        if hostname:
            if not(hostname in self.harness.config.hosts):
                self.harness.config.hosts.append(hostname)
            return Host(hostname, self.harness.config)
        else:
            return Host(self.harness.config.id_to_hostname(self.server.tenant_id, self.server.hostId), self.harness.config)

    def get_status(self):
        self.server.get()
        return self.server.status

    def get_ram(self):
        flavor = self.harness.nova.flavors.find(name=self.harness.config.flavor_name)
        return flavor.ram

    def get_addrs(self):
        '''Returns all IP addresses associated with the instance.'''
        return get_addrs(self.server)

    def get_address(self):
        '''Returns the preferred ip address to access an instance via.'''
        return get_addrs(self.server, self.harness.config.network_name)[0]

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
        (stdout, _) = \
            host.check_output('ps aux | grep qemu-system | grep %s | grep -v ssh | grep -v ssh' % osid)
        return int(stdout.split('\n')[0].strip().split()[1])

    def get_iptables_rules(self, host=None):
        if host == None:
            host = self.get_host()

        server_id = self.get_raw_id()

        # Check if the server has iptables rules.
        return host.get_nova_compute_instance_filter_rules(server_id)

    @Notifier.notify
    def bless(self, **kwargs):
        log.info('Blessing %s', self)
        self.breadcrumbs.add('Pre bless')

        # Unconditionally set up the params script on the master. This
        # operation is idempotent, so it is safe to do this even if
        # blessing the same instance multiple times.
        self.setup_params()

        blessed_list = self.harness.gcapi.bless_instance(self.server, **kwargs)
        assert len(blessed_list) == 1
        blessed = blessed_list[0]

        # Sanity checks on the blessed instance.
        assert blessed['id'] != self.id
        assert str(blessed['metadata']['blessed_from']) == str(self.id)
        assert blessed['name'] != self.server.name
        if 'name' in kwargs:
            assert blessed['name'] == kwargs['name']
        else:
            assert self.server.name in blessed['name']
        assert blessed['status'] in ['BUILD', 'BLESSED']

        snapshot = self.breadcrumbs.snapshot()
        server = self.harness.nova.servers.get(blessed['id'])
        instance = self.__class__(self.harness, server, self.image_config,
                                  breadcrumbs=False, snapshot=snapshot)

        instance.wait_for_bless()

        self.breadcrumbs.add('Post bless, child is %s' % instance.id)
        return instance

    @Notifier.notify
    def launch(self, target=None, guest_params=None, status='ACTIVE', name=None,
               user_data=None, security_groups=None, availability_zone=None,
               num_instances=None, keypair=None, scheduler_hints=None,
               paused_on_launch=False):
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
        if num_instances != None:
            params['num_instances'] = num_instances
        if keypair != None:
            params['key_name'] = keypair.name
        if scheduler_hints != None:
            params['scheduler_hints'] = scheduler_hints

        # Folsom: pick the host, has to fall within the provided list.
        # Grizzly and later: UNLESS, we have scheduler hints
        if (AVAILABILITY_ZONE.check(self.harness.nova) and
            not (SCHEDULER_HINTS.check(self.harness.nova) and
                 scheduler_hints != None)):
            if availability_zone is None:
                target_host = random.choice(self.harness.config.hosts)
                availability_zone = Host(target_host, self.harness.config).host_az()
                log.debug("Launching to host %s -> %s." %
                            (target_host, availability_zone))
            if availability_zone is not None:
                params['availability_zone'] = availability_zone

        # get an old list of launched VMs so we can discount these
        # from the launched VMs we're about to create.
        old_launches = self.harness.nova.gridcentric.list_launched(self.server)

        launched_list = self.harness.gcapi.launch_instance(self.server,
                                                           params=params)

        # Verify the metadata returned by nova-gc. Even with multiple instances
        # requested, a single server is returned (as per nova boot semantics)
        assert len(launched_list) == 1

        # The conform to the nova boot semantics, launch_instance only
        # returns one instance ID.  However, the user may have
        # requested more than one instance.  That's why we need to
        # re-list the launched instances to find the other instances
        # launched from the call above (and exclude the old launches).
        #
        # FIXME: TODO:
        #
        # The launch itself is using the wrapped gcapi.launch, which
        # is good.  We really should be using
        # harness.gcapi.list_launched_instances here for consistency.
        # Unfortunately, all of the code that depends on this function
        # expects a 'server' object instead of a 'dict'.
        launched_list = []
        all_launches = self.harness.nova.gridcentric.list_launched(self.server)
        for launched in all_launches:
            isnew = True
            for existing in old_launches:
                if existing.id == launched.id:
                    isnew = False
                    break
            if isnew:
                launched_list.append(launched)
        assert len(launched_list) >= 1

        clones = []
        for launched in launched_list:
            assert launched.id != self.id
            assert launched.status in [status, 'BUILD']

            if name == None:
                assert launched.name != self.server.name
                assert self.server.name in launched.name
            else:
                assert launched.name == name

            if keypair != None:
                assert launched.key_name == keypair.name

            # Retrieve the server from nova-compute. It should have our metadata added.
            server = self.harness.nova.servers.get(launched.id)
            assert server.metadata['launched_from'] == str(self.id)

            instance = self.__class__(self.harness, server, self.image_config,
                                      breadcrumbs=None, snapshot=None,
                                      keypair=keypair)
            instance.breadcrumbs = self.snapshot.instantiate(instance)
            instance.wait_for_boot(status)

            # Only ensure cloud init for instances that are active. We know ssh
            #et al will be dead for other status
            if launched.status == 'ACTIVE':
                # Only ensure cloud init for launched clones
                instance.ensure_cloudinit_done()

            # Folsom and later: if the availability zone targeted a specific host, verify
            if (AVAILABILITY_ZONE.check(self.harness.nova) and
                availability_zone != None):
                if ':' in availability_zone:
                    target_host = availability_zone.split(':')[1]
                    assert instance.get_host().id == target_host

            if paused_on_launch:
                self.harness.nova.servers.pause(server)
            clones.append(instance)

        # Most callers expect a singleton return value
        if num_instances is not None and num_instances != 1:
            return clones
        return clones[0]

    def instance_wait_for_ping(self):
        wait_for_ping([self.get_address()])

    def assert_alive(self, host=None):
        assert self.get_status() == 'ACTIVE'
        if host != None:
            assert self.get_host().id == host.id
        self.instance_wait_for_ping()
        wait_for_shell(self.get_shell())
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
                instance = self.__class__(
                    self.harness,
                    self.harness.nova.servers.get(id),
                    self.image_config, breadcrumbs=False)
                instance.discard(recursive=True)
        for volume in self.volumes:
            log.info('Detaching volume %s', volume.id)
            volume.detach()
            wait_for_status(volume, 'available')
        log.info('Deleting %s', self)
        self.server.delete()
        self.wait_while_exists()

    @Notifier.notify
    def discard(self, recursive=False):
        if recursive:
            self.delete_launched()
        log.info('Discarding %s', self)
        self.harness.gcapi.discard_instance(self.server)
        self.wait_while_exists()

    def list_blessed(self):
        return map(lambda x: x['id'], self.harness.gcapi.list_blessed_instances(self.server))

    def list_launched(self):
        return map(lambda x: x['id'], self.harness.gcapi.list_launched_instances(self.server))

    def delete_launched(self):
        for id in self.list_launched():
            instance = self.__class__(
                self.harness,
                self.harness.nova.servers.get(id),
                self.image_config, breadcrumbs=False)
            # Some tests purposefully fail the creation of an instance. So we
            # may race here with a launched instance in BUILD status still present
            # yet bound to make the delete fail
            try:
                instance.delete(recursive=True)
            except:
                if id in self.list_launched():
                    raise
            time.sleep(1.0) # Sleep after the delete.

    def vmsctl(self):
        return Vmsctl(self)

    def add_security_group(self, *args, **kwargs):
        return self.server.add_security_group(*args, **kwargs)

    def remove_security_group(self, *args, **kwargs):
        return self.server.remove_security_group(*args, **kwargs)

    def attach_volume(self, volume):
        # Figure out a decent name for a volume.
        before = set(self.list_devices())
        suggested = set(self.suggested_devices())
        available = list(suggested.difference(before))
        available.sort()
        device = available[0]

        # Do the attach and save the volume (returning the device).
        wait_for_status(volume, 'available')

        self.harness.nova.volumes.create_server_volume(self.server.id, volume.id, device)

        self.volumes.append(volume)

        wait_for_status(volume, 'in-use')

        wait_for('volume %s to be listed' % (volume.id), \
            lambda: device in self.list_devices())

        return device

    ### Platform-specific functionality.

    def get_shell(self):
        raise NotImplementedError()

    def root_command(self, command, **kwargs):
        raise NotImplementedError()

    def ensure_cloudinit_done(self):
        raise NotImplementedError()

    def setup_params(self):
        '''
        Performs any configuration on the guest necessary for reading
        the vms params on launched instances. This may be called
        multiple times on a single master and thus must be idempotent.
        '''
        raise NotImplementedError()

    def read_params(self):
        '''
        Returns a python object representation of the vms params passed to this
        instance, as currently seen by the instance's vms agent.
        '''
        raise NotImplementedError()

    def install_agent(self):
        raise NotImplementedError()

    def remove_agent(self):
        raise NotImplementedError()

    def assert_agent_running(self):
        raise NotImplementedError()

    def assert_agent_not_running(self):
        raise NotImplementedError()

    def post_hook_cloudinit(self):
        raise NotImplementedError()

    def assert_userdata(self, userdata):
        '''
        Ensure the userdata visible from the guest matches the argument to this
        function.
        '''
        raise NotImplementedError()

    def assert_guest_running(self):
        '''
        A light-weight operation to ensure the guest operating system is
        alive. This operation shall not touch large amounts of guest memory and
        shall be prompt.
        '''
        raise NotImplementedError()

    def assert_guest_stable(self):
        '''
        A more expensive but more comprehensive test to ensure the guest
        operating system is stable. This operation may touch a significant
        amount of memory (which can cause a lot of hypervisor memory related
        operations such as fetching and sharing) and should excercise kernel
        functionality to rule out driver and guest memory malfunctions.
        '''
        raise NotImplementedError()

    def drop_caches(self):
        '''
        Cause the guest operating system to drop all cached memory.
        '''
        raise NotImplementedError()

    def allocate_balloon(self, size_pages):
        '''
        Allocates a memory region of size 'size_pages' in the guest. Returns a
        fingerprint of the memory region which can be used with
        assert_balloon_integrity() to verify the integrity of the balloon. Only
        a single balloon may be allocated on a guest. The effects of allocating
        a new balloon without releasing the previous are undefined.
        '''
        raise NotImplementedError()

    def assert_balloon_integrity(self, fingerprint):
        '''
        Ensures the instance's current balloon's fingerprint matches the
        provided fingerprint.
        '''
        raise NotImplementedError()

    def thrash_balloon_memory(self, target_pages):
        '''
        Perform some guest operation with the intention of causing
        large amounts of guest physical memory to be
        re-allocated. This operation requires an existing balloon on
        the instance.
        '''
        raise NotImplementedError()

    def release_balloon(self):
        '''
        Frees all memory associated with any previously allocated balloon. This
        is safe to call when no balloon has been allocated.
        '''

    def list_devices(self):
        '''
        List attached devices.
        '''
        raise NotImplementedError()

    def suggested_devices(self):
        '''
        Suggested device names.
        '''
        raise NotImplementedError()

    def prime_volume(self, device):
        '''
        Format and do block IO to store random bytes on a named volume.
        Returns the hash of the random bytes, which are guaranteed to
        not be cached in RAM.
        '''
        raise NotImplementedError()

    def verify_volume(self, device, md5):
        '''
        Remount the named volume and verify the stored random bytes.
        Shred those bytes to test consistency of parent/sibling volumes.
        '''
        raise NotImplementedError()

class LinuxInstance(Instance):

    PARAMS_SCRIPT = """#!/usr/bin/env python
import json
import os
import sys

# Check the command-line arguments: all agent versions pass the raw params json
# as argv[2].
data = json.loads(sys.argv[2])
assert isinstance(data, dict)

# Try to import the old vmsagent params parsing library.
sys.path.append('/etc/gridcentric/common')
try:
    import common
except ImportError:
    # Couldn't import the old library. Assume we're using the new agent, which
    # parses the params json and passes in the string params as environment
    # variables.
    for key, val in data.items():
        if type(val) in [str, unicode]:
            assert os.environ['VMS_%s' % key] == val
        else:
            assert 'VMS_%s' % key not in os.environ
else:
    # Successfully imported the old params library. Make sure it parsed the
    # command-line arguments properly.
    params = common.parse_params()
    assert sys.argv[1] == params.uid()
    assert data == params.get_dict()

# Dump the params json so grinder can do an end-to-end check.
open("/tmp/clone.log", "w").write(sys.argv[2])
"""

    def __init__(self, harness, server, image_config,
                 breadcrumbs=None, **kwargs):
        Instance.__init__(
            self, harness, server, image_config,
            breadcrumbs=(breadcrumbs or SSHBreadcrumbs(self)),
            **kwargs)
        self.TMP_SSH_KEY_PATH   = "/tmp/curr_ssh_key"
        self.RSA_HOST_KEY_PATH  = "/etc/ssh/ssh_host_rsa_key.pub"

    def get_shell(self):
        return SecureShell(self.get_address(),
                           self.privkey_path,
                           self.image_config.user,
                           self.harness.config.ssh_port)

    def root_command(self, command, **kwargs):
        ssh = RootShell(self.get_address(),
                        self.privkey_path,
                        self.image_config.user,
                        self.harness.config.ssh_port)
        return ssh.check_output(command, **kwargs)

    def ensure_cloudinit_done(self):
        # Do we have cloud init? Wait until it's done reshuffling ssh
        if not self.image_config.cloudinit:
            return

        # Ssh comes up and down while waiting for cloud init.
        # Hence tolerate errors. Note we got here after ensuring
        # ssh was up at least once
        def check_cloudinit_done():
            try:
                (key, stderr) =\
                    self.root_command("cat %s" % self.RSA_HOST_KEY_PATH)
                (tmpkey, stderr) =\
                    self.root_command("cat %s" % self.TMP_SSH_KEY_PATH)
                assert key == tmpkey
                return True
            except Exception:
                return False

        wait_for("Cloud init to be done", check_cloudinit_done)

    def setup_params(self):
        params_path = "/etc/gridcentric/clone.d/90_clone_params"
        self.root_command("cat > %s" % params_path, input=self.PARAMS_SCRIPT)
        self.root_command("chmod a+x %s" % params_path)

    def read_params(self):
        attempt = 0
        while attempt < 100:
            try:
                (output, _) = self.root_command('cat /tmp/clone.log')
                break
            except:
                # Wait a short bit and retry.
                attempt += 1
                time.sleep(0.1)
        try:
            return json.loads(output)
        except:
            log.error("Exception parsing params json, raw string was: %s" % \
                          str(output))
            raise

    def install_agent(self):
        if not self.image_config.agent_skip:
            if self.image_config.distro in ["centos", "rpm"] and\
                self.harness.config.agent_location is not None:
                agent_location = fix_url_for_yum(self.harness.config.agent_location)
            else:
                agent_location = self.harness.config.agent_location
            self.harness.gcapi.install_agent(self.server,
                                             user=self.image_config.user,
                                             key_path=self.privkey_path,
                                             location=agent_location,
                                             version=self.harness.config.agent_version)
            self.breadcrumbs.add("Installed agent version %s" % self.harness.config.agent_version)
            self.assert_agent_running()

    def remove_agent(self):
        if not self.image_config.agent_skip:
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

    def post_hook_cloudinit(self):
        # Do we have cloud init on Linux? Then install extra hooks
        # that will help us know when cloud init reshuffle is done
        if not self.image_config.cloudinit:
            return

        reset_path = "/etc/gridcentric/clone.d/01_reset"
        post_ci_path = "/etc/gridcentric/clone.d/21_post-cloud-init"
        reset_script = """#!/bin/bash
rm -f %s
""" % self.TMP_SSH_KEY_PATH
        post_ci_script = """#!/bin/bash
cat %s > %s
""" % (self.RSA_HOST_KEY_PATH, self.TMP_SSH_KEY_PATH)
        for (path, script) in [(reset_path, reset_script),
                               (post_ci_path, post_ci_script)]:
            self.root_command("cat > %s" % path, input=script)
            self.root_command("chmod a+x %s" % path)

    def assert_userdata(self, userdata):
        self.get_shell().check_output('curl http://169.254.169.254/latest/user-data 2>/dev/null',
                                      expected_output=userdata)

    def assert_guest_running(self):
        self.root_command('uptime')

    def assert_guest_stable(self):
        self.root_command('ps aux')
        self.root_command('find / > /dev/null')

    def drop_caches(self):
        self.root_command("sh", input = "echo 3 > /proc/sys/vm/drop_caches")

    def allocate_balloon(self, size_pages):
        # Remount tmpfs with a 16MiB headroom on top of the requested size.
        tmpfs_size = (size_pages << 12) + (16 << 20)
        self.root_command("mount -o remount,size=%d /dev/shm" % (tmpfs_size))
        # Convert target to 2M super pages.
        self.root_command("dd if=/dev/urandom of=/dev/shm/file bs=2M count=%d" % (size_pages >> 9))
        (md5, _) = self.root_command("md5sum /dev/shm/file")
        return md5

    def assert_balloon_integrity(self, fingerprint):
        (md5, _) = self.root_command("md5sum /dev/shm/file")
        assert fingerprint == md5

    def thrash_balloon_memory(self, target_pages):
        self.root_command("shred -f -u -n 1 /dev/shm/file")
        self.drop_caches()
        # Remount tmpfs with a 16MiB headroom on top of the requested size.
        tmpfs_size = (target_pages << 12) + (16 << 20)
        self.root_command("mount -o remount,size=%d /dev/shm" % (tmpfs_size))
        self.root_command(
            "dd if=/dev/urandom of=/dev/shm/file bs=4k count=%d" % (target_pages))

    def release_balloon(self):
        self.root_command("rm -f /dev/shm/file")

    def list_devices(self):
        # Return the output from parsing /proc/partitions.
        (output, _) = self.root_command("cat /proc/partitions")
        lines = output.split("\n")[2:]
        devices = ["/dev/%s" % line.split()[-1] for line in lines if len(line) > 0]
        return devices

    def suggested_devices(self):
        return map(lambda x: '/dev/vd%s' % chr(x), range(ord('a'), ord('z')))

    def prime_volume(self, device):
        # Format, mount and umount the device.
        self.root_command("mkfs.ext3 %s" % device)
        self.root_command("mount %s /mnt" % device)
        self.root_command("dd if=/dev/urandom of=/mnt/test.file bs=1K count=1024")
        (md5, _) = self.root_command("md5sum /mnt/test.file")
        # *Really* ensure it's no longer in the page cache
        self.root_command("umount /mnt")
        self.drop_caches()
        self.root_command("blockdev --flushbufs %s" % device)
        return md5

    def verify_volume(self, device, md5):
        self.root_command("mount %s /mnt" % device)
        (new_md5, _) = self.root_command("md5sum /mnt/test.file")
        self.root_command("shred -f -u -n 1 -z /mnt/test.file")
        self.root_command("umount /mnt")
        assert new_md5 == md5

class WindowsInstance(Instance):

    def __init__(self, harness, server, image_config,
                 breadcrumbs=None, snapshot=None, **kwargs):
        Instance.__init__(
            self, harness, server, image_config,
            breadcrumbs=(breadcrumbs or LinkBreadcrumbs(self)),
            snapshot=snapshot, **kwargs)

    def get_shell(self):
        return WinShell(self.get_address(),
                        self.harness.config.windows_link_port)

    def ensure_cloudinit_done(self):
        pass

    def setup_params(self):
        pass

    def read_params(self):
        output, _ = self.get_shell().check_output('agent-proxy dump-params',
                                       expected_output=None)
        try:
            return json.loads(output)
        except:
            log.error("Exception parsing params json, raw string was: %s" % \
                          str(output))
            raise

    def install_agent(self):
        # Agent name manipulation trickery. Watch out for the "URL" passing an
        # authentication (username, password) tuple as space separated extra
        # components. If the actual URL does not contain an agent filename,
        # add it based on the arch. Finally, if the URL points to the wrong
        # arch filename, try to patch.
        agent_location = self.harness.config.windows_agent_location
        if len(agent_location.split()) == 3:
            (agent_location, user, password) = agent_location.split()
            split = True
        else:
            split = False
        arch = self.image_config.arch
        if not agent_location.endswith(".msi"):
            if arch == "64":
                agent_location += "/gc-agent-latest-amd64-release.msi"
            else:
                agent_location += "/gc-agent-latest-x86-release.msi"
        else:
            if arch == "64" and agent_location.find("amd64") == -1:
                agent_location = agent_location.replace("x86", "amd64")
            elif arch in ["pae", "32"] and agent_location.find("x86") == -1:
                agent_location = agent_location.replace("amd64", "x86")
        if split:
            agent_location = ' '.join([agent_location, user, password])

        shell = self.get_shell()
        shell.check_output('agent-update %s' % agent_location,
                           timeout=self.harness.config.ops_timeout)

        # Setup agent in continuous blessing mode with no preloading.
        shell.check_output('agent-proxy set-mode 3 0')

        version, _ = shell.check_output('agent-version', expected_output=None)
        version = version.strip()

        self.breadcrumbs.add("Installed agent version %s" % version)
        self.assert_agent_running()

    def remove_agent(self):
        self.get_shell().check_output('agent-remove')
        self.breadcrumbs.add("Removed agent")
        self.assert_agent_not_running()

    def assert_agent_running(self):
        self.get_shell().check_output('agent-proxy ping')

    def assert_agent_not_running(self):
        try:
            self.get_shell().check_output('agent-proxy ping', timeout=3)
            assert "Agent should not be running!" and False
        except RuntimeError:
            return

    def post_hook_cloudinit(self):
        pass

    def instance_wait_for_ping(self):
        # Windows instances have ICMP blocked by default
        pass

    def assert_userdata(self, userdata):
        # Retry once
        for i in range(2):
            guest_userdata, _ = self.get_shell().check_output(
                "get-userdata",
                expected_output=None)

            # TestListener uses DOS-style newlines and appends an extra newline at
            # the end.
            guest_userdata = guest_userdata.replace('\r', '')[:-1]

            if guest_userdata == userdata:
                return
        assert False

    def assert_guest_running(self):
        self.get_shell().check_output("agent-proxy ping")

    def assert_guest_stable(self):
        self.get_shell().check_output("agent-proxy ping")

    def drop_caches(self):
        # Drop caches on can take a long time so increase the timeout
        # from the default shell timeout.
        self.get_shell().check_output('drop-cache',
                           timeout=self.harness.config.ops_timeout)

    def allocate_balloon(self, size_pages):
        shell = self.get_shell()
        shell.check_output("balloon-alloc %d" % size_pages,
                           timeout=self.harness.config.ops_timeout)
        fingerprint, _ = shell.check_output("balloon-random-fill",
                                            expected_output=None,
                                            timeout=self.harness.config.ops_timeout)
        return int(fingerprint)

    def assert_balloon_integrity(self, fingerprint):
        output, _ = self.get_shell().check_output(
            "balloon-hash",
            expected_output=None,
            timeout=self.harness.config.ops_timeout)

        assert int(output) != 0
        assert int(output) == int(fingerprint)

    def thrash_balloon_memory(self, target_pages):
        # In the Windows case, we do not want to do a drop_caches() because the
        # Windows drop_caches() implementation touches ALL free memory, which
        # would cause unsharing of a very large number of pages on a reasonably
        # sized VM. We want to control how much unsharing we cause. An easy way
        # to thrash memory in the balloon is to simply refill it with newly
        # generated random data.
        output, _ = self.get_shell().check_output(
            "balloon-random-fill",
            timeout=self.harness.config.ops_timeout,
            expected_output=None)
        assert int(output) != 0

    def release_balloon(self):
        self.get_shell().check_output(
            "balloon-release",
            timeout=self.harness.config.ops_timeout,
            expected_output=None)

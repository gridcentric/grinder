import hashlib
import inspect
import os
import os 
import random
import shlex
import socket
import subprocess
import sys
import time
import unittest
import re
import tempfile
import shutil

import novaclient.exceptions

from gridcentric.nova.client.client import NovaClient
from novaclient.v1_1.client import Client
from novaclient.v1_1.servers import Server
from subprocess import PIPE

from logger import log
from config import default_config

# This is set by pytest_runtest_setup in conftest.py.
test_name = ''

def create_gcapi_client(config):
    '''Creates a NovaClient from the environment variables.'''
    # If we're on essex, we'll need to talk to the v2 authentication
    # system, which requires us to provide a service_type as a
    # target. Otherwise fall back to v1 authentication method.
    if config.openstack_version == 'essex':
        return NovaClient(auth_url=os.environ['OS_AUTH_URL'],
                          user=os.environ['OS_USERNAME'],
                          apikey=os.environ['OS_PASSWORD'],
                          project=os.environ['OS_TENANT_NAME'],
                          default_version=os.environ.get('NOVA_VERSION', 'v2.0'))
    else:
        return NovaClient(auth_url=os.environ['NOVA_URL'],
                          user=os.environ['NOVA_USERNAME'],
                          apikey=os.environ['NOVA_API_KEY'],
                          project=os.environ.get('NOVA_PROJECT_ID'),
                          default_version=os.environ.get('NOVA_VERSION', 'v1.1'))

def create_nova_client(config):
    '''Creates a nova Client from the environment variables.'''
    # If we're on essex, we'll need to talk to the v2 authentication
    # system, which requires us to provide a service_type as a
    # target. Otherwise fall back to v1 authentication method.
    if config.openstack_version == 'essex':
        return Client(username=os.environ['OS_USERNAME'],
                      api_key=os.environ['OS_PASSWORD'],
                      project_id=os.environ['OS_TENANT_NAME'],
                      auth_url=os.environ['OS_AUTH_URL'],
                      service_type='compute')
    else:
        return Client(username=os.environ['NOVA_USERNAME'],
                      api_key=os.environ['NOVA_API_KEY'],
                      project_id=os.environ['NOVA_PROJECT_ID'],
                      auth_url=os.environ['NOVA_URL'])

def create_client(config):
    '''Creates a nova Client with a gcapi client embeded.'''
    client = create_nova_client(config)
    setattr(client, 'gcapi', create_gcapi_client(config))
    return client

class SecureShell(object):
    def __init__(self, host, config):
        self.host = host
        self.key_path = config.key_path
        self.user = config.guest_user

    def ssh_opts(self):
        return '-o UserKnownHostsFile=/dev/null ' \
               '-o StrictHostKeyChecking=no ' \
               '-i %s ' % (self.key_path)

    def popen(self, args, **kwargs):
        # Too hard to support this.
        assert kwargs.get('shell') != True
        # If we get a string, just pass it to the client's shell.
        if type(args) in [str, unicode]:
            args = [args]
        log.debug('ssh %s@%s %s %s', self.user, self.host, self.ssh_opts(), ' '.join(args))
        return subprocess.Popen(['ssh'] + self.ssh_opts().split() + 
                                ['%s@%s' % (self.user, self.host)] + args, **kwargs)

    def check_output(self, args, **kwargs):
        returncode, stdout, stderr = self.call(args, **kwargs)
        if returncode != 0:
            log.error('Command %s failed:\n'
                      'returncode: %d\n'
                      '-------------------------\n'
                      'stdout:\n%s\n'
                      '-------------------------\n'
                      'stderr:\n%s', str(args), returncode, stdout, stderr)
        assert returncode == 0
        return stdout, stderr

    def call(self, args, **kwargs):
        input=kwargs.pop('input', None)
        p = self.popen(args, stdout=PIPE, stderr=PIPE, stdin=PIPE, **kwargs)
        stdout, stderr = p.communicate(input)
        return p.returncode, stdout, stderr

class SCPError(Exception):
    pass

class TransferChannel(SecureShell):
    def __do_scp(self, source, destination):
        log.debug('scp %s %s %s' % (self.ssh_opts(), source, destination))
        p = subprocess.Popen(['scp'] + self.ssh_opts().split() + [source] + 
                             [destination], stdout=PIPE, stderr=PIPE)
        stdout, stderr = p.communicate()
        if p.returncode != 0:
            raise SCPError("Failed scp transfer %s -> %s\n Stderr: %s" %
                            (source, destination, stderr))

    def put_file(self, local_path, remote_path = ''):
        os.stat(local_path)
        return self.__do_scp(local_path, '%s@%s:%s' % (self.user, self.host, remote_path))

    def get_file(self, remote_path, local_path = '.'):
        if local_path != '.':
            try:
                os.stat(local_path)
            except OSError:
                # Could be a filename that does not yet exist. But its directory should
                os.stat(os.path.dirname(local_path))
        return self.__do_scp('%s@%s:%s' % (self.user, self.host, remote_path), local_path)

class SecureRootShell(SecureShell):
    def call(self, args, **kwargs):
        if isinstance(args, str):
            args = [args]
        elif not isinstance(args, list):
            raise ValueError("Args of %s, must be list or string" % str(type(args)))
        args = ['sudo'] + args
        return SecureShell.call(self, args, **kwargs)

class HostSecureShell(SecureShell):
    def __init__(self, host, config):
        self.host = host
        self.key_path = config.key_path
        self.user = config.host_user

class VmsctlExecError(Exception):
    pass

class VmsctlLookupError(Exception):
    pass

class VmsctlInterface(object):
    def __init__(self, target, config = default_config):
        if type(target) in [int, long, unicode, str]:
            self.osid   = target
        elif isinstance(target, Server):
            if config.openstack_version == "diablo":
                self.osid   = target._info['id']
            else:
                self.osid   = target.id
        else:
            raise ValueError("Bad target %s." % str(type(target)))
        self.config = config
        self.vmsid  = None

        # Try to find on which host the instance is located
        for host in self.config.hosts:
            try:
                self.vmsid  = self.__osid_to_vmsid(host)
                self.host   = host
                break
            except VmsctlLookupError:
                # Try the next one if any
                pass
        if self.vmsid is None:
            raise VmsctlLookupError("Could not find Openstack instance %s in servers %s." %
                                    (str(osid), str(self.config.hosts)))

        # Now that we have the host establish the shell
        self.shell = HostSecureShell(self.host, self.config)

    def __osid_to_vmsid(self, host):
        shell = HostSecureShell(host, self.config)
        if self.config.openstack_version == 'essex':
            (rc, stdout, stderr) = shell.call(
                    "ps aux | grep qemu-system | grep %s | grep -v ssh | awk '{print $2}'" %
                        self.osid)
        else:
            (rc, stdout, stderr) = shell.call(
                    "ps aux | grep qemu-system | grep %08x | grep -v ssh | awk '{print $2}'" %
                        int(self.osid))
        if rc != 0:
            raise VmsctlLookupError("Openstack ID %s could not be matched to a VMS ID on "\
                                    "host %s." % (str(self.osid), host))
        try:
            # Int cast dande to make sure we got back a proper ID
            vmsid = int(stdout.split('\n')[0].strip())
        except:
            raise VmsctlLookupError("Openstack ID %s could not be matched to a VMS ID on "\
                                    "host %s." % (str(self.osid), host))
        return str(vmsid)

    def __do_call(self, args):
        if isinstance(args, str) or isinstance(args, unicode):
            args = args.split()
        if not isinstance(args, list):
            raise ValueError("Type of args is %s, should be string or list" 
                                % str(type(args)))
        try:
            log.debug("Calling %s on %s." % (str(args), self.host))
            (rc, stdout, stderr) = self.shell.call(["sudo", "vmsctl"] + args)
            log.debug("Calling %s on %s\nRC = %d\nStdout: %s\nStderr: %s" % 
                        (str(args), self.host, rc, stdout, stderr))
            return (rc, stdout, stderr)
        except Exception as e:
            raise VmsctlExecError("%s failed. Unknown RC.\nOutput:\n%s" %
                                    (str(args), e.strerror))

    def __set_call(self, args):
        (rc, stdout, stderr) = self.__do_call(args)
        # Calls that set a parameter return a 1
        if rc == 1:
            return stdout
        raise VmsctlExecError("Set param %s for VMS ID %s to %s failed. "\
                              "RC: %s\nOutput:\n%s" % (key, self.vmsid, 
                                                    str(value), str(rc), stderr))
    def set_param(self, key, value):
        self.__set_call(["set", self.vmsid, key, str(value)])

    def get_param(self, key):
        (rc, stdout, stderr) = self.__do_call(["get", self.vmsid, key])
        if rc == 0:
            return stdout.split('\n')[0].strip()
        raise VmsctlExecError("Get param %s for VMS ID %s failed. RC: %s\nOutput:\n%s" %
                                (key, self.vmsid, str(rc), stderr))

    def set_flag(self, key):
        self.set_param(key, '1')

    def clear_flag(self, key):
        self.set_param(key, '0')

    def get_target(self):
        return int(self.get_param("memory.target"))

    def get_current_memory(self):
        return int(self.get_param("memory.current"))

    def get_max_memory(self):
        return int(self.get_param("pages"))

    def set_target(self, value):
        self.set_param("memory.target", value)

    def clear_target(self):
        self.set_param("memory.target", '0')

    def dropall(self):
        self.__set_call(["dropall", self.vmsid])

    def launch_hoard(self, rate = '25'):
        self.__set_call(["hoard", self.vmsid, str(rate)])

    def stop_hoard(self):
        self.set_param("hoard", "0")

    def full_hoard(self, rate = '25', wait_seconds = 120, threshold = 0.9):
        self.launch_hoard(rate)
        tries = 0
        while float(self.get_current_memory()) <= (threshold * float(self.get_max_memory())):
            time.sleep(1)
            tries += 1
            if tries >= wait_seconds:
                return False
        self.stop_hoard()
        return True

    def info(self):
        (rc, stdout, stderr) = self.__do_call(["info", self.vmsid])
        if rc == 0:
            lines = [ l.strip() for l in stdout.split('\n') ]
            vmsid = lines[0].split(':')[0].strip()
            if vmsid == self.vmsid:
                return eval(' '.join(lines[1:]))
        raise VmsctlExecError("Get info for VMS ID %s failed. RC: %s\nOutput:\n%s" %
                                (self.vmsid, str(rc), stderr))

    def match_expected_params(self, expected):
        info = self.info()
        for (k,v) in expected.items():
            val = info.get(str(k), None)
            if val is None:
                raise LookupError("Queried for unavailable param %s in vmsctl %s" %
                                   (str(k), str(self.osid)))
            if str(v) != str(val):
                return False
        return True

def get_jenkins_deploy_script():
    dirname = tempfile.mkdtemp(prefix='openstack-test-jenkins')
    name = os.path.join(dirname, "deploy")
    rc = subprocess.call(("wget --auth-no-challenge --http-user=******** "\
                         "--http-password=******** "\
                         "http://********/job/Libvirt-master/ws/deploy"\
                         " -O %s" % name).split())
    if rc != 0:
        return None
    return name
        
def remove_jenkins_deploy_script(name):
    shutil.rmtree(os.path.dirname(name))

# Bring the latest agent from jenkins into the VM
def auto_install_agent(server, config, distro = None):
    user    = config.guest_user
    key     = config.key_path
    if distro is None:
        distro = config.guest
    jenkins_download = get_jenkins_deploy_script()
    if jenkins_download is None:
        raise RuntimeError("Could not download latest agent from jenkins")
    ip = get_addrs(server)[0]
    p = subprocess.Popen('REMOTE="-i %s %s@%s sudo" /bin/bash %s Agent-1 %s '\
                          'vms-agent' % (key, user, ip, jenkins_download, distro), 
                          shell=True)
    (stdout, stderr) = p.communicate()
    remove_jenkins_deploy_script(jenkins_download)
    if p.returncode != 0:
        raise RuntimeError("Deploy script failed (%d), stderr:\n%s" %
                            (p.returncode, stderr))

def wait_for(message, condition, duration=15, interval=1):
    log.info('Waiting %ss for %s', duration, message)
    start = time.time()
    while True:
        if condition():
            return
        remaining = start + duration - time.time()
        if remaining <= 0:
            raise Exception('Timeout: waited %ss for %s' % (duration, message))
        time.sleep(min(interval, remaining))

def wait_while_status(server, status, duration=60):
    def condition():
        if server.status != status:
            return True
        server.get()
        return False
    wait_for('%s on ID %s to finish' % (status, str(server.id)),
             condition, duration)

def wait_for_ping(ip, duration=60):
    wait_for('ping %s to respond' % ip,
             lambda: os.system('ping %s -c 1 -W 1 > /dev/null 2>&1' % ip) == 0,
             duration=duration)

def wait_for_ssh(ssh, duration=600):
    wait_for('ssh %s to respond' % ssh.host,
             lambda: ssh.call('true')[0] == 0, duration=duration)

def wait_while_exists(server, duration=60):
    def condition():
        try:
            server.get()
            return False
        except novaclient.exceptions.NotFound:
            return True
    wait_for('server %s to not exist' % server.id, condition, duration=duration)

def generate_name(prefix):
    return '%s-%d' % (prefix, random.randint(0, 1<<32))

def boot(client, name_prefix, config, image_name = None):
    name = generate_name(name_prefix)
    flavor = client.flavors.find(name=config.flavor_name)
    if image_name is None:
        image_name = config.image_name
    image = client.images.find(name=image_name)
    log.info('Booting %s instance named %s', image.name, name)
    server = client.servers.create(name=name,
                                   image=image.id,
                                   flavor=flavor.id,
                                   key_name=config.key_name)
    setattr(server, 'config', config)
    assert_boot_ok(server, config.guest_has_agent)
    return server

def get_addrs(server):
    ips = []
    for network in server.networks.values():
        ips.extend(network)
    return ips

def assert_boot_ok(server, withagent = True):
    wait_while_status(server, 'BUILD')
    assert server.status == 'ACTIVE'
    ip = get_addrs(server)[0]
    shell = SecureShell(ip, server.config)
    wait_for_ping(ip)
    wait_for_ssh(shell)
    # Sanity check on hostname
    shell.check_output('hostname')[0] == server.name
    if withagent:
        # Make sure that the vmsagent is running
        shell.check_output('pidof vmsagent')

def assert_raises(exception_type, command, *args, **kwargs):
    try:
        command(*args, **kwargs)
        assert False and 'Expected exception of type %s' % exception_type
    except Exception, e:
        assert type(e) ==  exception_type
        log.debug('Got expected exception %s', e)
        return e

class Breadcrumbs(object):
    def __init__(self, shell):
        self.shell = shell
        self.trail = []
        self.filename = '/tmp/test-breadcrumbs-%d' % random.randint(0, 1<<32)

    class Snapshot(object):
        def __init__(self, breadcrumbs):
            self.trail = list(breadcrumbs.trail)
            self.filename = breadcrumbs.filename

        def instantiate(self, shell):
            result = Breadcrumbs(shell)
            result.trail = list(self.trail)
            result.filename = self.filename
            return result

    def snapshot(self):
        return Breadcrumbs.Snapshot(self)

    def add(self, breadcrumb):
        self.assert_trail()
        breadcrumb = '%d: %s' % (len(self.trail), breadcrumb)
        log.debug('Adding breadcrumb "%s"', breadcrumb)
        self.shell.check_output('cat >> %s' % self.filename, input=breadcrumb + '\n')
        self.trail.append(breadcrumb)
        self.assert_trail()

    def assert_trail(self):
        if len(self.trail) == 0:
            self.shell.check_output('test ! -e %s' % self.filename)
        else:
            stdout, stderr = self.shell.check_output('cat %s' % self.filename)
            log.debug('Got breadcrumbs: %s', stdout.split('\n'))
            assert stdout.split('\n')[:-1] == list(self.trail)

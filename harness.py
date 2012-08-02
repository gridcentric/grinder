import hashlib
import inspect
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
import pytest

import novaclient.exceptions

from novaclient.v1_1.client import Client
from novaclient.v1_1.servers import Server
from subprocess import PIPE

from logger import log
from config import default_config

# This is set by pytest_runtest_setup in conftest.py.
test_name = ''

# This class serves as an adaptor for different versions of the API.
# In Diablo, we ship a special gc-api tool that can be used to interact
# directly with the Gridcentric API endpoints. From Essex onwards, the
# novaclient-gridcentric package is capable of directly extending the
# novaclient tools with Gridcentric hooks. For simplicity, we generally
# write to the older API, then have this class translate to the newer
# extensions.

class NovaClientGcApi(object):
    def __init__(self, novaclient):
        self.novaclient = novaclient

    def discard_instance(self, *args, **kwargs):
        return self.novaclient.gridcentric.discard(*args, **kwargs)

    def launch_instance(self, *args, **kwargs):
        params = kwargs.get('params', {})
        guest = params.get('guest', {})
        target = params.get('target', "0")
        return map(lambda x: x._info, self.novaclient.gridcentric.launch(*args, target=target, guest_params=guest))

    def bless_instance(self, *args, **kwargs):
        return map(lambda x: x._info, self.novaclient.gridcentric.bless(*args, **kwargs))

    def list_blessed_instances(self, *args, **kwargs):
        return map(lambda x: x._info, self.novaclient.gridcentric.list_blessed(*args, **kwargs))

    def list_launched_instances(self, *args, **kwargs):
        return map(lambda x: x._info, self.novaclient.gridcentric.list_launched(*args, **kwargs))

    def migrate_instance(self, *args, **kwargs):
        return self.novaclient.gridcentric.migrate(*args, **kwargs)

def create_gcapi_client(config):
    '''Creates a NovaClient from the environment variables.'''
    # If we're >= Essex, we'll need to talk to the v2 authentication
    # system, which requires us to provide a service_type as a
    # target. Otherwise fall back to v1 authentication method.
    if config.openstack_version == 'diablo':
        # Return the gridcentric packaged client (default is not extensible).
        from gridcentric.nova.client.client import NovaClient
        return NovaClient(auth_url=os.environ['NOVA_URL'],
                          user=os.environ['NOVA_USERNAME'],
                          apikey=os.environ['NOVA_API_KEY'],
                          project=os.environ.get('NOVA_PROJECT_ID'),
                          default_version=os.environ.get('NOVA_VERSION', 'v1.1'))

    else:
        # Return the gridcentric extensions from the standard client.
        novaclient = create_nova_client(config)
        return NovaClientGcApi(novaclient)

def create_nova_client(config):
    '''Creates a nova Client from the environment variables.'''
    # If we're >= Essex, we'll need to talk to the v2 authentication
    # system, which requires us to provide a service_type as a
    # target. Otherwise fall back to v1 authentication method.
    if config.openstack_version == 'diablo':
        return Client(username=os.environ['NOVA_USERNAME'],
                      api_key=os.environ['NOVA_API_KEY'],
                      project_id=os.environ['NOVA_PROJECT_ID'],
                      auth_url=os.environ['NOVA_URL'],
                      service_type='compute')
    else:
        from novaclient import shell
        extensions = shell.OpenStackComputeShell()._discover_extensions("1.1")
        if 'gridcentric' not in [e.name for e in extensions]:
            raise Exception('You don\'t have the gridcentric extension for the '
                            'nova client installed. It\'s in the '
                            'novaclient-gridcentric package.')
        return Client(extensions=extensions,
                      username=os.environ['OS_USERNAME'],
                      api_key=os.environ['OS_PASSWORD'],
                      project_id=os.environ['OS_TENANT_NAME'],
                      auth_url=os.environ['OS_AUTH_URL'],
                      service_type=os.environ['NOVA_SERVICE_TYPE'],
                      service_name=os.environ['NOVA_SERVICE_NAME'])

def find_exception(config):
    if config.openstack_version == 'diablo':
        from gridcentric.nova.client.exceptions import HttpException
        return HttpException
    else:
        from novaclient.exceptions import BadRequest
        return BadRequest

def create_client(config):
    '''Creates a nova Client with a gcapi client embeded.'''
    client = create_nova_client(config)
    gcapi = create_gcapi_client(config)
    setattr(gcapi, 'exception', find_exception(config))
    setattr(client, 'gcapi', gcapi)
    return client

class SecureShell(object):
    def __init__(self, host, key_path=None, user=None):
        '''Host can either be a string (ip address or hostname) or a Server. If
           host is a server, then key_path and user may be optionally specified
           to override host.image_config.'''
        if isinstance(host, Server):
            server = host
            host = get_addrs(host)[0]
            if key_path == None:
                key_path = server.image_config.key
            if user == None:
                user = server.image_config.user
        else:
            server = None
            if key_path == None or user == None:
                raise TypeError('key_path and user must be specified')

        self.host = host
        self.key_path = key_path
        self.user = user
        # By default ssh does not allocate a pseudo-tty (if asked to exec a
        # single command, from our harness). However, some programs may require
        # tty, e.g. sudo on CentOS 6.3. If we're running on CentOS, assume a tty
        # is needed unless explicitly disabled, as in cases in which we want to
        # manage stdin
        self.alloc_tty = server != None and\
                         server.image_config.distro == 'centos'

    def ssh_opts(self, use_tty=False):
        if use_tty:
            tty_arg = '-tt '
        else:
            tty_arg = ''
        return '-o UserKnownHostsFile=/dev/null ' \
               '-o StrictHostKeyChecking=no ' \
               '%s -i %s ' % (tty_arg, self.key_path)

    def ssh_args(self, use_tty=False):
        return '%s %s@%s' % (self.ssh_opts(use_tty), self.user, self.host)

    def popen(self, args, **kwargs):
        # Too hard to support this.
        assert kwargs.get('shell') != True
        # If we get a string, just pass it to the client's shell.
        if type(args) in [str, unicode]:
            args = [args]
        # Do we need to allocate a tty?
        use_tty = kwargs.pop('use_tty', self.alloc_tty)
        _stdin = kwargs.get('stdin', None)
        if _stdin is not None and _stdin is not PIPE:
            use_tty = False
        command = ['ssh'] + self.ssh_args(use_tty).split() + args
        log.debug(' '.join(command))
        return subprocess.Popen(command, **kwargs)

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
        input = kwargs.pop('input', None)
        if input is not None:
            use_tty = False
        else:
            use_tty = self.alloc_tty
        p = self.popen(args, stdout=PIPE, stderr=PIPE, stdin=PIPE, use_tty=use_tty, **kwargs)
        stdout, stderr = p.communicate(input)
        return p.returncode, stdout, stderr

class SCPError(Exception):
    pass

class TransferChannel(object):
    def __init__(self, ssh):
        self.ssh = ssh

    def __do_scp(self, source, destination):
        log.debug('scp %s %s %s' % (self.ssh.ssh_opts(), source, destination))
        p = subprocess.Popen(['scp'] + self.ssh.ssh_opts().split() + [source] +
                             [destination], stdout=PIPE, stderr=PIPE)
        stdout, stderr = p.communicate()
        if p.returncode != 0:
            raise SCPError("Failed scp transfer %s -> %s\n Stderr: %s" %
                            (source, destination, stderr))

    def put_file(self, local_path, remote_path=''):
        os.stat(local_path)
        return self.__do_scp(local_path, '%s@%s:%s' % (self.ssh.user, self.ssh.host, remote_path))

    def get_file(self, remote_path, local_path='.'):
        if local_path != '.':
            try:
                os.stat(local_path)
            except OSError:
                # Could be a filename that does not yet exist. But its directory should
                os.stat(os.path.dirname(local_path))
        return self.__do_scp('%s@%s:%s' % (self.ssh.user, self.ssh.host, remote_path), local_path)

class SecureRootShell(SecureShell):
    def ssh_args(self, use_tty=False):
        return SecureShell.ssh_args(self, use_tty) + ' sudo'

class HostSecureShell(SecureShell):
    def __init__(self, host, config):
        SecureShell.__init__(self, host, config.host_key_path, config.host_user)
        # This is a good choice as long as we launch tests on Ubuntu hosts
        self.alloc_tty = False

    def get_vmsfs_stats(self, genid=None):
        if genid is None:
            path = '/sys/fs/vmsfs/stats'
        else:
            path = '/sys/fs/vmsfs/%s' % genid
        (rc, stdout, stderr) = self.call('sudo cat %s' % path)
        if rc != 0:
            raise Exception("sudo cat %s failed with rc %d\nStderr: %s"
                             % (path, rc, stderr))
        # Post-process
        lines = [ x.strip() for x in stdout.split('\n')[:-1] ]
        statsdict = {}
        for line in lines:
            m = re.match('([a-z_]+): ([0-9]+) -', line)
            (key, value) = m.groups()
            statsdict[key] = long(value)
        return statsdict

class VmsctlExecError(Exception):
    pass

class VmsctlLookupError(Exception):
    pass

class VmsctlInterface(object):
    def __init__(self, target, config):
        if type(target) in [int, long, unicode, str]:
            self.osid = target
        elif isinstance(target, Server):
            if config.openstack_version == "diablo":
                self.osid = target._info['id']
            else:
                self.osid = target.id
        else:
            raise ValueError("Bad target %s." % str(type(target)))
        self.config = config
        self.vmsid = None

        # Try to find on which host the instance is located
        for host in self.config.hosts:
            try:
                self.vmsid = self.__osid_to_vmsid(host)
                self.host = host
                break
            except VmsctlLookupError:
                # Try the next one if any
                pass
        if self.vmsid is None:
            raise VmsctlLookupError("Could not find Openstack instance %s in servers %s." %
                                    (str(self.osid), str(self.config.hosts)))

        # Now that we have the host establish the shell
        self.shell = HostSecureShell(self.host, self.config)

    def __osid_to_vmsid(self, host):
        shell = HostSecureShell(host, self.config)
        if self.config.openstack_version == 'diablo':
            (rc, stdout, stderr) = shell.call(
                    "ps aux | grep qemu-system | grep %08x | grep -v ssh | awk '{print $2}'" %
                        int(self.osid))
        else:
            (rc, stdout, stderr) = shell.call(
                    "ps aux | grep qemu-system | grep %s | grep -v ssh | awk '{print $2}'" %
                        self.osid)
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
        if self.config.parse_vms_version() <= (2, 3):
            expected_rc = 1
        else:
            expected_rc = 0
        (rc, stdout, stderr) = self.__do_call(args)
        if rc == expected_rc:
            return stdout
        raise VmsctlExecError("Set call %s failed. "\
                              "RC: %s\nOutput:\n%s" % (str(args),
                                                       str(rc), stderr))
    def __action_call(self, action):
        (rc, stdout, stderr) = self.__do_call([action, self.vmsid])
        if rc != 0:
            raise VmsctlExecError("Action %s on ID %s RC %d.\nStdout: %s"
                                    % (action, str(self.vmsid), rc, stderr))

    def pause(self):
        self.__action_call("pause")

    def unpause(self):
        self.__action_call("unpause")

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

    def launch_hoard(self, rate='25'):
        self.__set_call(["hoard", self.vmsid, str(rate)])

    def stop_hoard(self):
        self.set_param("hoard", "0")

    def full_hoard(self, rate='25', wait_seconds=120, threshold=0.9):
        self.launch_hoard(rate)
        tries = 0
        maxmem = self.get_max_memory()
        while float(self.get_current_memory()) <= (threshold * float(maxmem)):
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

    def get_generation(self):
        info = self.info()
        return info['generation']

    def match_expected_params(self, expected):
        info = self.info()
        for (k, v) in expected.items():
            val = info.get(str(k), None)
            if val is None:
                raise LookupError("Queried for unavailable param %s in vmsctl %s" %
                                   (str(k), str(self.osid)))
            if str(v) != str(val):
                log.debug("Could not match param %s from vmsctl %s, got %s expected %s" %
                            (str(k), str(self.osid), str(val), str(v)))
                return False
        return True

def get_jenkins_deploy_script():
    dirname = tempfile.mkdtemp(prefix='openstack-test-jenkins')
    name = os.path.join(dirname, "deploy")
    rc = subprocess.call(("wget --auth-no-challenge --http-user=******** "\
                         "--http-password=******** "\
                         "http://********/job/build/ws/deploy"\
                         " -O %s" % name).split())
    if rc != 0:
        return None
    return name

def remove_jenkins_deploy_script(name):
    shutil.rmtree(os.path.dirname(name))

# Bring the latest agent from jenkins into the VM
def auto_install_agent(server, agent_version):
    distro = server.image_config.distro
    log.info('Installing agent version %s on %s' % (agent_version, server.id))
    jenkins_download = get_jenkins_deploy_script()
    if jenkins_download is None:
        raise RuntimeError("Could not download latest agent from jenkins")
    shell = SecureRootShell(server)
    command = ['/bin/bash', jenkins_download,
               '-m', server.image_config.arch,
               '-r', server.image_config.distro,
               '-d', '192.168.1.3',
               '-R', shell.ssh_args(),
               'Agent-%s' % agent_version,
               'vms-agent']
    log.debug(' '.join(command))
    p = subprocess.Popen(command)
    (stdout, stderr) = p.communicate()
    remove_jenkins_deploy_script(jenkins_download)
    if p.returncode != 0:
        raise RuntimeError("Deploy script failed (%d), stderr:\n%s" %
                            (p.returncode, stderr))

def check_agent_running(server):
    shell = SecureRootShell(server)
    if server.image_config.distro == 'ubuntu':
        shell.check_output("dpkg -l vms-agent | grep ^ii")
    elif server.image_config.distro == 'centos':
        shell.check_output("rpm -qa | grep vms-agent")
    shell.check_output("pidof vmsagent")

def wait_for(message, condition, interval=1):
    duration = int(default_config.ops_timeout)
    log.info('Waiting %ss for %s', duration, message)
    start = time.time()
    while True:
        if condition():
            return
        remaining = start + duration - time.time()
        if remaining <= 0:
            raise Exception('Timeout: waited %ss for %s' % (duration, message))
        time.sleep(min(interval, remaining))

def wait_while_status(server, status):
    def condition():
        if server.status != status:
            return True
        server.get()
        return False
    wait_for('%s on ID %s to finish' % (status, str(server.id)),
             condition)

def wait_for_ping(server):
    addrs = get_addrs(server)
    assert len(addrs) > 0
    ip = addrs[0]
    wait_for('ping %s to respond' % ip,
             lambda: os.system('ping %s -c 1 -W 1 > /dev/null 2>&1' % ip) == 0)

def wait_for_ssh(server):
    ssh = SecureShell(server)
    wait_for('ssh %s to respond' % ssh.host,
             lambda: ssh.call('true')[0] == 0)

def wait_while_exists(server):
    def condition():
        try:
            server.get()
            return False
        except novaclient.exceptions.NotFound:
            return True
    wait_for('server %s to not exist' % server.id, condition)

def generate_name(prefix):
    # If we're running within a jenkins environment, use the build number as
    # the unique test identifier. Otherwise, we use the unique identifier
    # generated by the test framework.
    if os.getenv("BUILD_NUMBER"):
        suffix = os.getenv("BUILD_NUMBER")
    else:
        suffix = str(random.randint(0, 1 << 32))
    return '%s-%s' % (prefix, suffix)

def boot(client, config, image_config=None):
    name = generate_name(test_name)
    flavor = client.flavors.find(name=config.flavor_name)
    if image_config == None:
        finder = ImageFinder()
        # Prefer to use CirrOS because it's so much smaller and therefore makes
        # migration and blessing faster. Fall back to Ubuntu.
        finder.add('cirros', '64')
        finder.add('ubuntu', '64')
        image_config = finder.find(client, config)
    image = client.images.find(name=image_config.name)
    log.info('Booting %s instance named %s', image.name, name)
    server = client.servers.create(name=name,
                                   image=image.id,
                                   flavor=flavor.id)
    server = get_server(server.id, client, config, image_config)
    setattr(server, 'image_config', image_config)
    assert_boot_ok(server)
    return server


def get_server(id, client, config, image_config):
    server = client.servers.get(id)
    setattr(server, 'image_config', image_config)
    return server

def get_addrs(server):
    ips = []
    for network in server.networks.values():
        ips.extend(network)
    return ips

def assert_boot_ok(server):
    wait_while_status(server, 'BUILD')
    assert server.status == 'ACTIVE'
    wait_for_ping(server)
    wait_for_ssh(server)

def assert_raises(exception_type, command, *args, **kwargs):
    try:
        command(*args, **kwargs)
        assert False and 'Expected exception of type %s' % exception_type
    except Exception, e:
        assert type(e) == exception_type
        log.debug('Got expected exception %s', e)
        return e

def get_iptables_rules(server, host=None, config=default_config):
    if host == None:
        # Determine the host from the server.
        host = config.id_to_hostname(server.tenant_id, server.hostId)
    host_shell = HostSecureShell(host, config)

    compute_iptables_chain = "nova-compute-local"
    server_iptables_chain = "nova-compute-inst-%s" % (str(server._info['id']))

    def get_rules(iptables_chain):
        stdout, stderr = host_shell.check_output("sudo iptables -L %s" % (iptables_chain))
        rules = stdout.split("\n")[2:]
        return rules
    # Check if the server has iptables rules
    for rule in get_rules(compute_iptables_chain):
        if server_iptables_chain in rule:
            # This server has rules defined on this host. Grab the server's rules
            return get_rules(server_iptables_chain)
    # Otherwise there are no rules so return an empty list.
    return []

class Breadcrumbs(object):
    def __init__(self, server):
        self.shell = SecureShell(server)
        self.trail = []
        self.filename = '/dev/shm/test-breadcrumbs-%d' % random.randint(0, 1<<32)

    class Snapshot(object):
        def __init__(self, breadcrumbs):
            self.trail = list(breadcrumbs.trail)
            self.filename = breadcrumbs.filename

        def instantiate(self, server):
            result = Breadcrumbs(server)
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
            assert [x.strip('\r') for x in stdout.split('\n')[:-1]] == list(self.trail)

class NoImageFoundError(Exception):
    pass

class ImageFinder(object):
    def __init__(self, skip_on_error=False):
        self.queries = []
        self.skip_on_error = skip_on_error

    def add(self, distro, arch):
        self.queries.append((distro, arch))

    def find(self, client, config):
        for distro, arch in self.queries:
            for image in config.get_images(distro, arch):
                try:
                    found = client.images.find(name=image.name)
                    return image
                except Exception:
                    log.debug('Image %s not found, skipping', image.name)
        if self.skip_on_error:
            pytest.skip()
        else:
            raise NoImageFoundError()

    @staticmethod
    def parametrize(metafunc, arg_name, distros, archs, skip_on_error=False):
        finders = []
        ids = []
        for distro in distros:
            for arch in archs:
                finder = ImageFinder(skip_on_error)
                finder.add(distro, arch)
                finders.append(finder)
                ids.append('%s %s' % (distro, arch))
        metafunc.parametrize(arg_name, finders, ids=ids)

def mark_test(fn, **kwargs):
    metadata = getattr(fn, '__test_markers', {})
    metadata.update(kwargs)
    setattr(fn, '__test_markers', metadata)
    return fn

def list_filter(l, exclude=None, include=None):
    if exclude == None:
        exclude = []
    if include != None:
        l = l + include
    return [e for e in l if e not in exclude]

def get_test_marker(fn, marker, default=None):
    return getattr(fn, '__test_markers', {}).get(marker, default)

def archtest(exclude=None, include=None):
    def _inner(fn):
        archs = list_filter(default_config.get_all_archs(), exclude, include)
        return mark_test(fn, archs=archs)
    return _inner

def get_test_archs(fn):
    return get_test_marker(fn, 'archs', default_config.default_archs)

def distrotest(exclude=None, include=None):
    def _inner(fn):
        distros = list_filter(default_config.get_all_distros(), exclude, include)
        return mark_test(fn, distros=distros)
    return _inner

def get_test_distros(fn):
    return get_test_marker(fn, 'distros', default_config.default_distros)

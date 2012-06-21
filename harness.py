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

import novaclient.exceptions

from gridcentric.nova.client.client import NovaClient
from novaclient.v1_1.client import Client
from subprocess import PIPE

from logger import log

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

    def popen(self, args, **kwargs):
        # Too hard to support this.
        assert kwargs.get('shell') != True
        # If we get a string, just pass it to the client's shell.
        if isinstance(args, str):
            args = [args]
        ssh_args = 'ssh -o UserKnownHostsFile=/dev/null' \
                   '    -o StrictHostKeyChecking=no' \
                   '    -i %s' \
                   '    %s@%s' % (self.key_path, self.user, self.host)
        log.debug('ssh %s@%s: %s', self.user, self.host, ' '.join(args))
        return subprocess.Popen(ssh_args.split() + args, **kwargs)

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

def boot(client, name_prefix, config):
    name = generate_name(name_prefix)
    flavor = client.flavors.find(name=config.flavor_name)
    image = client.images.find(name=config.image_name)
    log.info('Booting %s instance named %s', image.name, name)
    server = client.servers.create(name=name,
                                   image=image.id,
                                   flavor=flavor.id,
                                   key_name=config.key_name)
    setattr(server, 'config', config)
    assert_boot_ok(server)
    return server

def get_addrs(server):
    ips = []
    for network in server.networks.values():
        ips.extend(network)
    return ips

def assert_boot_ok(server):
    wait_while_status(server, 'BUILD')
    assert server.status == 'ACTIVE'
    ip = get_addrs(server)[0]
    shell = SecureShell(ip, server.config)
    wait_for_ping(ip)
    wait_for_ssh(shell)
    # Sanity check on hostname
    shell.check_output('hostname')[0] == server.name
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

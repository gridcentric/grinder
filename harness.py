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

from gridcentric.nova.client.client import NovaClient
from novaclient.v1_1.client import Client
from subprocess import PIPE

from logger import log

def create_gcapi_client():
    '''Creates a NovaClient from the environment variables.'''
    return NovaClient(auth_url=os.environ['NOVA_URL'],
                      user=os.environ['NOVA_USERNAME'],
                      apikey=os.environ['NOVA_API_KEY'],
                      project=os.environ.get('NOVA_PROJECT_ID'),
                      default_version=os.environ.get('NOVA_VERSION', 'v1.1'))

def create_nova_client():
    '''Creates a nova Client from the environment variables.'''
    return Client(username=os.environ['NOVA_USERNAME'],
                  api_key=os.environ['NOVA_API_KEY'],
                  project_id=os.environ['NOVA_PROJECT_ID'],
                  auth_url=os.environ['NOVA_URL'])

def create_client():
    '''Creates a nova Client with a gcapi client embeded.'''
    client = create_nova_client()
    setattr(client, 'gcapi', create_gcapi_client())
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

def wait_for(message, condition, duration=15, interval=0.5):
    log.info('Waiting %ss for %s', duration, message)
    start = time.time()
    while True:
        if condition():
            return
        remaining = start + duration - time.time()
        if remaining <= 0:
            raise Exception('Timeout: waited %ss for %s' % (duration, message))
        log.debug('Waiting %ds for %s ...', remaining, message)
        time.sleep(min(interval, remaining))

def wait_for_build(server):
    def condition():
        if server.status != 'BUILD':
            return True
        server.get()
        return False
    wait_for('BUILD on ID %s to finish' % str(server.id),
             condition, duration=60)

def wait_for_ping(server, duration=15):
    ip = server.networks['base_network'][0]
    wait_for('ping %s to respond' % ip,
             lambda: os.system('ping %s -c 1 -W 1 > /dev/null 2>&1' % ip) == 0,
             duration=duration)

def wait_for_ssh(ssh, duration=60):
    wait_for('ssh %s to respond' % ssh.host,
             lambda: ssh.call('true')[0] == 0, duration=duration)

def generate_name(prefix):
    return '%s-openstack-test-%d' % (prefix, random.randint(0, 1<<32))

def boot(client, name_prefix, config):
    name = generate_name(name_prefix)
    flavor = client.flavors.find(name=config.flavor_name)
    image = client.images.find(name=config.image_name)
    log.info('Booting %s instance named %s', image.name, name)
    server = client.servers.create(name=generate_name(name_prefix),
                                   image=image.id,
                                   flavor=flavor.id,
                                   key_name=config.key_name)
    setattr(server, 'config', config)
    assert_boot_ok(server)
    return server

def assert_boot_ok(server):
    wait_for_build(server)
    assert server.status == 'ACTIVE'
    ip = server.networks['base_network'][0]
    shell = SecureShell(ip, server.config)
    wait_for_ping(server)
    wait_for_ssh(shell)
    # Sanity check on hostname
    shell.check_output('hostname')[0] == server.name
    # Make sure that the vmsagent is running
    shell.check_output('pidof vmsagent')

class Breadcrumbs(object):
    def __init__(self, shell):
        self.shell = shell
        self.breadcrumbs = []
        self.filename = '/tmp/test-breadcrumbs-%d' % random.randint(0, 1<<32)

    def add(self, breadcrumb):
        self.assert_trail()
        breadcrumb = '%d: %s' % (len(self.breadcrumbs), breadcrumb)
        log.debug('Adding breadcrumb "%s"', breadcrumb)
        self.shell.check_output('cat >> %s' % self.filename, input=breadcrumb + '\n')
        self.breadcrumbs.append(breadcrumb)
        self.assert_trail()

    def assert_trail(self):
        if len(self.breadcrumbs) == 0:
            self.shell.check_output('test ! -e %s' % self.filename)
        else:
            stdout, stderr = self.shell.check_output('cat %s' % self.filename)
            log.debug('Got breadcrumbs: %s', stdout.split('\n'))
            assert stdout.split('\n')[:-1] == list(self.breadcrumbs)

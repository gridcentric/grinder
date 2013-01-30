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

import subprocess

from . logger import log
from . util import wait_for

class SecureShell(object):

    def __init__(self, host, key_path, user):
        self.host = host
        self.key_path = key_path
        self.user = user
        assert self.host
        assert self.key_path
        assert self.user

    def ssh_args(self):
        return [
                'ssh',
                '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'StrictHostKeyChecking=no',
                "-o", "PasswordAuthentication=no",
                "-i", self.key_path,
                "%s@%s" % (self.user, self.host),
               ]

    def check_output(self, command, input=None,
                     expected_rc=0, expected_output=None,
                     exc=False):
        # Run the given command through a shell on the other end.
        command = self.ssh_args() + ['sh', '-c', "'%s'" % command]
        ssh = subprocess.Popen(command,
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               close_fds=True)

        # Always execute the command in one go, we don't support
        # running long running commands in the test framework.
        (stdout, stderr) = ssh.communicate(input)
        (stdout, stderr) = (stdout.strip(), stderr.strip())
        if (expected_rc != None and expected_rc != ssh.returncode) or \
           (expected_output != None and stdout != expected_output):
            errormsg = 'Command failed: %s\n' \
                       'returncode: %d\n' \
                       '-------------------------\n' \
                       'stdout:\n%s\n' \
                       '-------------------------\n' \
                       'stderr:\n%s' % (" ".join(command), ssh.returncode, stdout, stderr)
            if exc:
                raise Exception(errormsg)
            log.error(errormsg)
            assert (expected_rc == None or expected_rc == ssh.returncode)
            assert (expected_output == None or expected_output == stdout)

        return (stdout, stderr)

class RootShell(SecureShell):

    '''The RootShell implements a subclass of the SecureShell,
    except we check if a sudo prefix is necessary when running commands.'''

    def __init__(self, *args, **kwargs):
        SecureShell.__init__(self, *args, **kwargs)
        self.sudo = []
        (whoami, err) = self.check_output('whoami')
        if whoami != 'root':
            self.sudo = ['sudo']

    def ssh_args(self):
        return super(RootShell,self).ssh_args() + self.sudo

def wait_for_ssh(shell):
    def _connect():
        try:
            shell.check_output('true', exc=True)
            return True
        except:
            return False
    wait_for('ssh %s to respond' % shell.host, _connect)

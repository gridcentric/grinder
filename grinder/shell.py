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

import select
import socket
import subprocess
import time

from . logger import log
from . util import wait_for

class SecureShell(object):

    def __init__(self, host, key_path, user, port):
        self.host = host
        self.key_path = key_path
        self.user = user
        self.port = port
        assert self.host
        assert self.user
        assert self.port

    def ssh_args(self):
        ssh_args = [
                'ssh',
                '-p', str(self.port),
                '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'StrictHostKeyChecking=no',
                "-o", "PasswordAuthentication=no",
                "-o", "TCPKeepAlive=yes",
                "-o", "ServerAliveInterval=30"]
        if self.key_path is not None:
            ssh_args += ["-i", self.key_path]

        ssh_args += ["%s@%s" % (self.user, self.host)]

        return ssh_args

    def check_output(self, command, input=None,
                     expected_rc=0, expected_output=None,
                     exc=False, extra_message=None, returnrc=False):
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
            errormsg = ""
            if extra_message:
                errormsg += extra_message + '\n'
            errormsg += 'Command failed: %s\n' \
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

        if returnrc:
            return (stdout, stderr, ssh.returncode)
        else:
            return (stdout, stderr)

    def is_alive(self):
        '''Runs a dummy command through the shell. Returns True if the
        shell is responsive, false otherwise. Useful for ensuring the
        shell is operational.'''
        try:
            self.check_output('true', exc=True)
            return True
        except:
            return False

class RootShell(SecureShell):

    '''The RootShell implements a subclass of the SecureShell,
    except we check if a sudo prefix is necessary when running commands.'''

    def __init__(self, host, key_path, user, port):
        SecureShell.__init__(self, host, key_path, user, port)
        self.sudo = []
        if user != 'root':
            self.sudo = ['sudo']

    def ssh_args(self):
        return super(RootShell,self).ssh_args() + self.sudo

def wait_for_shell(shell):
    wait_for('shell %s to respond' % shell.host, shell.is_alive)

class WinShell(object):

    def __init__(self, host, port):
        self.host = host
        self.port = port
        log.debug("Creating link to %s on port %d." % (self.host, self.port))

    def _connect(self):
        # When attempting to connect immediately after boot, the
        # TestListener service may not yet be initialized. Until the
        # service binds the port, we'll get connection refused errors.
        retries = 100
        while True:
            try:
                retries -= 1
                sock = socket.create_connection((self.host, self.port), 5)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                return sock
            except socket.error, exc:
                log.debug("Failed to connect to %s: %s. Retrying." % \
                              (self.host, exc))
                time.sleep(1)
                if retries <= 0:
                    raise

    def check_output(self, command, expected_output="ok", timeout=60):
        sock = self._connect()
        try:
            log.debug("Link I: %s" % command)
            sock.sendall(command)

            # If timeout is None, we don't expect a response back.
            if timeout is None:
                return (None, None)

            # Do a nonblocking wait for 'timeout'.
            sock.setblocking(0)
            ready = select.select([sock], [], [], timeout)
            if len(ready[0]) > 0 and ready[0][0] == sock:
                response = sock.recv(8192)
                log.debug("Link O: %s" % response.strip())
                if expected_output is None or \
                        response.strip() == expected_output:
                    return response, ""
                else:
                    raise ValueError("Link command '%s' sent unexpected " % \
                                         command +
                                     "response: %s. Expecting: %s." % \
                                         (response, expected_output))
            else:
                raise RuntimeError("Link command '%s' timed out." % command)

        finally:
            sock.close()

    def is_alive(self):
        '''Returns True if the link is operational.'''
        try:
            sock = self._connect()
            sock.close()
            return True
        except:
            return False


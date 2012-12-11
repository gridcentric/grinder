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
    except we check if a sudo prefix is necessary when running commands.
    Note that we will always run the given commands through a shell on
    the remote end, so you can still do things like 'cat > foo'.'''

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

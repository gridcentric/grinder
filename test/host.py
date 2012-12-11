import re

from . shell import RootShell

class Host(object):

    '''The Host object wraps around the HostSecureShell with some
    common operations (getting stats, checking usage, etc.).'''

    def __init__(self, hostname, config):
        self.id = hostname
        self.config = config

    def get_shell(self):
        return RootShell(self.id,
                         self.config.host_key_path,
                         self.config.host_user)

    def __str__(self):
        return 'Host(id=%s)' % (self.id)

    def check_output(self, command, **kwargs):
        shell = self.get_shell()
        return shell.check_output(command, **kwargs)

    def get_vmsfs_stats(self, genid=None):
        if genid is None:
            path = '/sys/fs/vmsfs/stats'
        else:
            path = '/sys/fs/vmsfs/%s' % genid

        # Grab the stats.
        (stdout, stderr) = self.check_output('cat %s' % path)

        # Post-process.
        lines = [x.strip() for x in stdout.split('\n')]
        statsdict = {}
        for line in lines:
            m = re.match('([a-z_]+): ([0-9]+) -', line)
            (key, value) = m.groups()
            statsdict[key] = long(value)
        return statsdict

    def get_ips(self):
        # Return the list of all assigned IP addresses.
        for line in lines:
            m = re.match('([a-z_]+): ([0-9]+) -', line)
            (key, value) = m.groups()
            statsdict[key] = long(value)
        return statsdict

    def get_ips(self):
        # Return the list of all assigned IP addresses.
        stdout, stderr = self.check_output('ip addr | grep "inet "')
        ips = map(lambda x: x.split()[1], stdout.split("\n"))
        return [ip.split("/")[0] for ip in ips]

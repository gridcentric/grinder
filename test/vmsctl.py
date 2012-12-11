import time

from . config import default_config

class Vmsctl(object):

    '''The Vmsctl interface wraps around an Instance object and provides
    convenience functions for running vmsctl on the target host.'''

    def __init__(self, instance):
        self.instance = instance
        self.vmsid = self.instance.get_vms_id()

    def call(self, command, *args):
        host = self.instance.get_host()
        (stdout, stderr) = host.check_output(
            "vmsctl %s %d " % (command, self.vmsid) + " ".join(args))
        return stdout

    def pause(self):
        self.call("pause")

    def unpause(self):
        self.call("unpause")

    def set_param(self, key, value):
        self.call("set", key, str(value))

    def get_param(self, key):
        return self.call("get", key)

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

    def generation(self):
        return self.get_param("generation")

    def set_target(self, value):
        self.set_param("memory.target", value)

    def clear_target(self):
        self.set_param("memory.target", '0')

    def dropall(self):
        self.call("dropall")

    def full_hoard(self, rate=10000, wait_seconds=default_config.ops_timeout, threshold=0.9):
        self.set_flag("hoard")
        self.set_param("hoard.rate", str(rate))
        tries = 0
        maxmem = self.get_max_memory()
        while float(self.get_current_memory()) <= (threshold * float(maxmem)):
            time.sleep(1.0)
            tries += 1
            if tries >= wait_seconds:
                return False
        self.clear_flag("hoard")
        return True

    def info(self):
        return eval('{' + self.call("info") + '}')[self.vmsid]

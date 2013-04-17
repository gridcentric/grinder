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
        return int(self.get_param("pages")) - int(self.get_param("memory.hole"))

    def generation(self):
        return self.get_param("generation")

    def set_target(self, value):
        self.set_param("memory.target", value)

    def clear_target(self):
        self.set_param("memory.target", '0')

    def dropall(self):
        self.call("dropall")

    # You need to set the appropriate knobs for vmsd to have the
    # right tools to meet your target.
    def meet_target(self, target, wait_seconds=default_config.ops_timeout):
        tries = 0
        self.set_target(target)
        while int(self.get_param("memory.current")) >= target:
            time.sleep(1.0)
            tries += 1
            if tries >= wait_seconds:
                return False
        return True

    def full_hoard(self, rate=10000, wait_seconds=default_config.ops_timeout):
        self.clear_target()
        self.clear_flag("eviction.enabled")
        self.set_flag("hoard")
        self.set_param("hoard.rate", str(rate))
        tries = 0

        while int(self.get_param("memory.complete")) != 1:
            time.sleep(1.0)
            tries += 1
            if tries >= wait_seconds:
                return False

        self.clear_flag("hoard")
        return True

    def info(self):
        return eval('{' + self.call("info") + '}')[self.vmsid]

#!/usr/bin/env python

import sys
import time
import random
import subprocess

from gridcentric.nova.client.client import NovaClient

COMMAND = "ssh -o ConnectTimeout=1 -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no peter@%s sh -c 'ls && ps'"

def usage():
    sys.stderr.write("usage: test-nova <id>\n")

if len(sys.argv) < 2:
    usage()
    exit()
 
instance_id = sys.argv[1]
client = NovaClient('http://localhost:8774/v1.1','admin','admin','admin','v1.1')

while True:
    instances = client.list_launched_instances(instance_id)
    tokill = len(instances)
    spinkill = 0
    sys.stderr.write("Deleting %d instances...\n" % len(instances))
    for instance in instances:
    	client.delete_instance(instance['id'])

    while len(instances) > 0:
        time.sleep(1.0)
        spinkill += 1
        instances = client.list_launched_instances(instance_id)
    sys.stderr.write("STAT: kill %d %d seconds\n" % (tokill, spinkill))

    tolaunch = random.randint(5,10)
    spinlaunch = 0
    sys.stderr.write("Launching %d instances...\n" % tolaunch)
    for i in range(tolaunch):
        client.launch_instance(instance_id)

    sys.stderr.write("Checking instances...\n")
    while True:
        time.sleep(1.0)
        spinlaunch += 1
        instances = client.list_launched_instances(instance_id)
        nonactive = False
        for instance in instances:
            if not(instance['status'] == 'ACTIVE') and not(instance['status'] == 'ERROR'):
                nonactive = True
        if not(nonactive):
            break
    sys.stderr.write("STAT: launch %d %d seconds\n" % (tolaunch, spinlaunch))

    # Give them 3 seconds to come up.
    time.sleep(3.0)

    addrs = []
    reached = 0
    for instance in instances:
        try:
            addrs.append(instance['addresses']['base_network'][0]['addr'])
        except:
            pass
    for addr in addrs:
        cmd = (COMMAND % addr).split()
        rc = subprocess.call(cmd)
        if rc != 0: 
            sys.stderr.write("Failed to reach %s.\n" % addr)
        else:
            reached += 1

    sys.stderr.write("STAT: %d/%d alive\n" % (reached, tolaunch))

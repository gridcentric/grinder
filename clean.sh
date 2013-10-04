#!/bin/bash

stall=0
for uuid in $(nova list | grep -v 'BLESSED' | tail -n +4 | head -n -1 | awk '{print $2;}'); do
    nova delete $uuid
    stall=$(($stall+3))
done
sleep $stall

stall=0
for uuid in $(nova list | grep -E '(BLESSED)' | awk '{print $2;}'); do
    nova discard $uuid
    stall=$(($stall+3))
done
sleep $stall

for uuid in $(nova secgroup-list | grep -i 'created by grinder' | awk '{print $2}'); do
    nova secgroup-delete $uuid;
done

for disk in $(cinder list | grep 'grindervol-' | awk '{print $2}'); do
    cinder delete $disk;
done

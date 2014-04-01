#!/bin/bash
set -x
# Delete the grinder lock file that corresponds to the grinder run about to happen
policy_lock=/tmp/grinder-policy-lock.$(echo $OS_AUTH_URL |sed "s|http://||g" | sed s/:/_/g | sed "s|/|_|g")_
echo "Cleaning up lock file: ${policy_lock}"
rm -f ${policy_lock}

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

for snap in $(cinder snapshot-list | grep 'snapshot for ' | awk '{print $2}'); do
    cinder snapshot-delete $snap;
done

for disk in $(cinder list | grep 'grindervol-' | awk '{print $2}'); do
    cinder delete $disk;
done

# Instances in ERROR state that remain after all of the above, are probably failed
# live-image-create entries
for uuid in $(nova list | awk '{print $2}' | grep -v ID); do
    echo $uuid; nova discard $uuid;
done

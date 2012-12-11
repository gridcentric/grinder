#!/bin/bash

for uuid in $(nova list | grep -E '(ACTIVE|ERROR|BUILD)' | awk '{print $2;}'); do
    nova delete $uuid;
done
for uuid in $(nova list | grep -E '(BLESSED)' | awk '{print $2;}'); do
    nova discard $uuid;
done

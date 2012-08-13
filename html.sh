#!/bin/bash

mkdir -p html

for x in logs/*.xml; do
    y=html/$(basename $x .xml).html
    xsltproc junit2html.xslt $x > $y
    touch --date="$(stat --printf '%y' $x)" $y
done

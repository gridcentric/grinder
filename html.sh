#!/bin/bash

mkdir -p html

for x in logs/*.xml; do
    xsltproc junit2html.xslt $x > html/$(basename $x .xml).html
done

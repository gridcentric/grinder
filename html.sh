#!/bin/bash

mkdir -p html

for x in logs/*.xml; do
    y=html/$(basename $x .xml).html
    xsltproc junit2html.xslt $x > $y
    touch --date="$(stat --printf '%y' $x)" $y
done

echo '<html><body><tt>' > html/index.html
for x in $(ls -t html | grep '.*\.html$' | grep -v index.html); do
    echo "$(stat --printf '%y' html/$x | sed 's/\..*//') <a href=\"$x\">$(basename $x .html)</a><br/>" >> html/index.html
done
echo '</tt></body></html>' >> html/index.html

#!/bin/bash

mkdir -p html

for x in logs/*.xml; do
    if [ ! -r $x ]; then
        continue
    fi
    y=html/$(basename $x .xml).html
    if [ ! -e $y -o $x -nt $y ]; then
        echo "generating $y"
        xsltproc junit2html.xslt $x > $y
        # pyunit screws up some xml escaping. It ouputs &amp;gt; when it should
        # output &gt;. We fix it up with sed here.
        sed -i 's/&amp;\(gt\|amp\|apos\|quot\);/\&\1;/g' $y
        touch --date="$(stat --printf '%y' $x)" $y
    fi
done

echo "generating html/index.html"
echo '<html><body><tt>' > html/index.html
for x in $(ls -t html | grep '.*\.html$' | grep -v index.html); do
    echo "$(stat --printf '%y' html/$x | sed 's/\..*//') <a href=\"$x\">$(basename $x .html)</a><br/>" >> html/index.html
done
echo '</tt></body></html>' >> html/index.html

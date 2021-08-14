#!/bin/bash

if [ $# -ne 1 ]; then 
    echo 'illegal number of arguments'
    exit 0
else
    feedname=$1
fi

. config

echo "Initializing feed $feedname".

feeddir=$documentroot/$feedname

mkdir $feeddir
if [ $? -ne 0 ] ; then
    echo "mkdir failed: try a different feedname or run with sudo"
    exit 0
fi

echo $feedname >> feeds
cd $documentroot

echo -n "Enter feed title: "
read feedtitle

echo -n "Enter URL: "
read feedurl

echo -n "Enter a URL for the thumbnail or leave empty: "
read thumburl

touch $feeddir/feed.body
touch $feeddir/archive


cat << EOF > $feeddir/params
feedname=$feedname
channelurl=$feedurl
feedtitle="$feedtitle"
thumburl="$thumburl"
EOF



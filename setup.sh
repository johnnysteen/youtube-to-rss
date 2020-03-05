#!/bin/bash
. config
echo $feedname >> feeds
cd $documentroot

feedname=$1
echo "Initializing feed $feedname".

feeddir=$documentroot/$feedname

mkdir $feeddir

echo -n "Enter feed title: "
read feedtitle

echo -n "Enter URL: "
read feedurl

touch $feeddir/feed.body
touch $feeddir/archive


cat << EOF > $feeddir/params
feedname=$feedname
channelurl=$feedurl
feedtitle="$feedtitle"
EOF



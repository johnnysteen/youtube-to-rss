#!/bin/bash

feedname=$1
echo "Initializing feed $feedname".

mkdir $feedname

echo -n "Enter feed title: "
read feedtitle

echo -n "Enter URL: "
read feedurl

touch $feedname/feed.body
touch $feedname/archive


cat << EOF > $feedname/params
feedname=$feedname
channelurl=$feedurl
feedtitle="$feedtitle"
EOF

echo $feedname >> feeds


#!/bin/bash

if (( $# != 3 )); then
    echo 'usage: ' $0 ' name-of-feed channel-url archive-file'
    exit 1
fi

URL='192.168.1.170'

youtube-dl -xciw --download-archive $3 $2 > log.out

grep -i '\[download\] destination' log.out > log2.out

while read LINE
do
    oldfile=${LINE#*: }                 #Long F@$&* title!-1234567890A.webm
    filebase=${oldfile%.*}              #Long F@$&* title!-1234567890A
    list_of_files=( "$filebase".* )
    oldfile="${list_of_files[0]}"       #Long F@$&* title!-1234567890A.mp4
    fileext=${oldfile##*.}              #mp4
    newfile=${filebase:(-11)}.$fileext  #1234567890A.mp4
    length=`ffmpeg -i "$oldfile" 2>&1 | grep Duration | awk -F: '{print 3600 * $2 + 60*$3 + $4 }'`
    mv "$oldfile" $newfile
    mv feed.body feed.oldbody
    cat << EOF >> feed.body
    <item>
    <title>${oldfile%-*}</title>
    <pubdate>`date`</pubdate>
    <enclosure url="http://$URL/$1/$newfile" type="audio/mpeg" length="$length"></enclosure>
    </item>
EOF
    cat feed.oldbody >> feed.body
    rm feed.oldbody
done < log2.out

cat feed.head feed.body feed.foot > feed.rss

rm log2.out


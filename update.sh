#!/bin/bash

. config

cd $documentroot/$1
. params

if [ -n "$2" ] && [ "$2" -eq "$2" ] 2>/dev/null; then
    numdl=$2
else
    numdl=1
fi

youtube-dl --restrict-filenames --write-info-json -xciw --yes-playlist --max-downloads $numdl --download-archive archive $channelurl > log.out

grep -i '\[download\] destination' log.out > log2.out

while read LINE
do
    oldfile=${LINE#*: }                 #Long F@#$ title!-1234567890A.webm
    filebase=${oldfile%.*}              #Long F@#$ title!-1234567890A

    echo 'New episode: ' $filebase

    vidurl=`cat "$filebase.info.json" | python -c "import sys, json; print(json.load(sys.stdin)['webpage_url'])"`
    pubdate=`cat "$filebase.info.json" | python -c "import sys, json; print(json.load(sys.stdin)['upload_date'])"`
    pubstring=`date -jf '%Y%m%d' '+%a, %d %b %Y %H:%M:%S %z' $pubdate`
    description=`cat "$filebase.info.json" | python -c "import sys, json; print(json.load(sys.stdin)['description'].encode('utf-8'))" | sed 's/\&/\&amp\;/g;s/\</\&lt\;/g;s/\>/\&gt\;/g'`

    echo 'Published ' "$pubstring"

    rm -- "$filebase.info.json"

    list_of_files=( "$filebase".* )
    oldfile="${list_of_files[0]}"       #Long F@#$ title!-1234567890A.mp4
    fileext=${oldfile##*.}              #mp4
    newfile=${filebase:(-11)}.$fileext  #1234567890A.mp4
    length=`ffmpeg -i "$oldfile" 2>&1 | grep Duration | awk -F: '{print 3600 * $2 + 60*$3 + $4 }'`

    mv "$oldfile" $newfile
    oldfile=$(echo $oldfile | sed 's/\&/\&amp\;/g;s/\</\&lt\;/g;s/\>/\&gt\;/g')


    mv feed.body feed.oldbody
    cat << EOF >> feed.body
    <item>
    <title>${oldfile%-$newfile}</title>
    <pubdate>$pubstring</pubdate>
    <guid>${filebase:(-11)}</guid>
    <enclosure url="http://$URL/$feedname/$newfile" type="audio/mpeg" length="$length"></enclosure>
    <description>
    ${oldfile%-$newfile}

    Original video: $vidurl

    $description
    </description>
    </item>
EOF

    cat feed.oldbody >> feed.body
    rm feed.oldbody
done < log2.out

cat << EOF > feed.newrss
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
    <title>$feedtitle</title>
    <link>https://$URL/$feedname/</link>
    <description>$feedtitle Youtube rips</description>
    <image>$thumburl</image>
    <generator>Visit johnnysteen/youtube-to-rss on Github</generator>
EOF


cat feed.body >> feed.newrss

cat << EOF >> feed.newrss
</channel>
</rss>
EOF

rm log2.out
mv feed.newrss feed.rss


#!/bin/bash
echo '**********' `date` '**********' 1>&2
echo $PATH 1>&2
PATH=$PATH:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
ytdlpath=/home/pi/youtube-to-rss
cd $ytdlpath

. config

cd $documentroot/$1
. params

overridelock=0
OPTIND=2
while getopts ":n:v:" arg; do
    case $arg in
        n)
            numdl=${OPTARG}
            ;;
        v)
            channelurl=${OPTARG}
            overridelock=1
            ;;
    esac
done

if [ "$overridelock" -eq 0 ]; then
    if [ -f LOCK ]; then
        echo "Update already in progress."
        exit 0
fi
fi

touch LOCK
#if [ -n "$2" ] && [ "$2" -eq "$2" ] 2>/dev/null; then
#    numdl=$2
#else
#    numdl=1
#fi

uniqid=$(date '+%s')

#youtube-dl --datebefore `date -v-1d +%Y%m%d` --restrict-filenames --write-info-json -xciw --yes-playlist --max-downloads $numdl --download-archive archive $channelurl > log.out
youtube-dl --cookies $ytdlpath/youtube.com_cookies.txt -o "%(id)s${uniqid}.%(ext)s" --abort-on-unavailable-fragment --restrict-filenames --write-info-json -xci --yes-playlist --max-downloads $numdl --download-archive archive $channelurl > log.out

grep -i '\[download\] destination' log.out > log2.out

for finfojson in *${uniqid}.info.json;
do
if [ -f $finfojson ]; then
    filebase=${finfojson%%.*}


    title=`cat -- "${finfojson}" | python -c "import sys, json; print(json.load(sys.stdin)['title'])" | sed 's/\&/\&amp\;/g;s/</\&lt\;/g;s/>/\&gt\;/g'`
    vidurl=`cat -- "${finfojson}" | python -c "import sys, json; print(json.load(sys.stdin)['webpage_url'])"`
    pubdate=`cat -- "${finfojson}" | python -c "import sys, json; print(json.load(sys.stdin)['upload_date'])"`
    pubstring=`date --date $pubdate '+%a, %d %b %Y %H:%M:%S %z'`
    description=`cat -- "${finfojson}" | python -c "import sys, json; print(json.load(sys.stdin)['description'].encode('utf-8'))" | sed 's/\&/\&amp\;/g;s/</\&lt\;/g;s/>/\&gt\;/g'`
    vid=`cat -- "${finfojson}" | python -c "import sys,json; print(json.load(sys.stdin)['id'])"`

    echo 'New episode: ' $title
    echo 'Published ' "$pubstring"

    rm -- "${finfojson}"

    list_of_files=( "$filebase".* )
    oldfile="${list_of_files[0]}"
    newfile=$oldfile

    length=`ffmpeg -i "$oldfile" 2>&1 | grep Duration | awk -F: '{print 3600 * $2 + 60*$3 + $4 }'`

    mv feed.body feed.oldbody
    cat << EOF >> feed.body
    <item>
    <title>${title}</title>
    <pubdate>$pubstring</pubdate>
    <guid>${vid}</guid>
    <enclosure url="http://$URL/$feedname/$newfile" type="audio/mpeg" length="$length"></enclosure>
    <description>
    ${title}

    Filename: $newfile
    Original video: $vidurl
    Downloaded: `date`

    $description
    </description>
    </item>
EOF

    cat feed.oldbody >> feed.body
    rm feed.oldbody
fi
done

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
rm LOCK


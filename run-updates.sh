#!/bin/bash

#documentroot=/Library/WebServer/Documents/
#. documentroot
#cd $documentroot

uptime=8 #update interval in hours
let interval=3600*$uptime
numdls=1
feedname=''

while :
do
    clear
    which youtube-dl
    youtube-dl --version
    . config
    let interval=3600*$uptime
    echo 'The time is ' `date '+%Y.%m.%d %H:%M:%S'`

    if [ "$argstr" = '' ]; then
        #youtube-dl -U
        while read LINE
        do
            echo "Checking feed '"$LINE"' for updates..."
            bash update.sh $LINE -n 1 2> /dev/null
        done < feeds
    else
        #echo "Checking feed '"$feedname"' for updates (downloading $numdls videos)..."
        #bash update.sh $feedname -n $numdls
        echo "bash update.sh $argstr"
        bash update.sh $argstr 2> /dev/null
    fi

    numdls=1
    feedname=''
    argstr=''
    hr=10#$(expr $(date +%H) % $uptime)
    let mins=10#$(date +%M)+60*$hr
    let secs=10#$(date +%S)+60*$mins
    let sleeptime=$interval-$secs
    let sleepsecs=$sleeptime%60
    let sleepmins=$sleeptime/60%60
    let sleephrs=$sleeptime/3600
    echo 'Finished updating at ' `date '+%Y.%m.%d %H:%M:%S'`
    echo 'Will return in' $sleephrs 'hrs' $sleepmins 'mins' $sleepsecs 'secs.'
    echo 'Hit ENTER to update now or type FEEDNAME NUMDLS'
    read -t $sleeptime argstr #feedname numdls
done



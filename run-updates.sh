#!/bin/bash

#documentroot=/Library/WebServer/Documents/
#. documentroot
#cd $documentroot

uptime=8 #update interval in hours
let interval=3600*$uptime

while :
do
    . config
    let interval=3600*$uptime
    echo 'The time is ' `date '+%Y.%m.%d %H:%M:%S'`

    youtube-dl -U
    while read LINE
    do
        echo "Checking feed '"$LINE"' for updates..."
        bash update.sh $LINE 1
    done < feeds

    hr=10#$(expr $(date +%H) % $uptime)
    let mins=10#$(date +%M)+60*$hr
    let secs=10#$(date +%S)+60*$mins
    let sleeptime=$interval-$secs
    let sleepsecs=$sleeptime%60
    let sleepmins=$sleeptime/60%60
    let sleephrs=$sleeptime/3600
    echo 'Finished updating at ' `date '+%Y.%m.%d %H:%M:%S'`
    echo 'Will return in' $sleephrs 'hrs' $sleepmins 'mins' $sleepsecs 'secs (ENTER: update now)'
    read -t $sleeptime
done



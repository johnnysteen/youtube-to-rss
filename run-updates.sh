#!/bin/bash

documentroot=/Library/WebServer/Documents/

uptime=8
let interval=3600*$uptime

while :
do
    echo 'The time is ' `date '+%Y.%m.%d %H:%M:%S'`

    youtube-dl -U
    echo 'Updating feeds...'
    while read LINE
    do
        echo $LINE
        cd $documentroot/$LINE
        bash -x ./update.sh
        cd $documentroot
    done < feeds

    hr=$(expr $(date +%H) % $uptime)
    let mins=$(date +%M)+60*$hr
    let secs=$(date +%S)+60*$mins
    let sleeptime=$interval-$secs
    echo 'Will return in ' $sleeptime ' seconds.'
    read -t $sleeptime
done



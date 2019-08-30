#!/bin/bash

documentroot=/Library/WebServer/Documents/
#feeds=( rekieta aydin metokur josh soph gator )

uptime=8

while :
do
    echo 'The time is ' `date +%H:%M:%S`
    hour=`date +%H`
    hour=${hour#0}
    #if [ `date +%H` -eq $uptime ]
    if ! (( hour % uptime )); then
        youtube-dl -U
        echo 'Updating feeds...'
        while read LINE
        do
            echo $LINE
            cd $documentroot/$LINE
            bash -x ./update.sh
            cd $documentroot
        done < feeds
        #for feed in "${feeds[@]}"
        #do
        #    cd $documentroot/$feed
        #    bash -x ./update.sh
        #    cd $documentroot
        #done
    else
        echo 'Will update at' $uptime:`date +%M:%S`
    fi
    echo 'Will return in one hour.'
    sleep 3600
done



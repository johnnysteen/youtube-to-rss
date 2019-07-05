#!/bin/bash

documentroot=/Library/WebServer/Documents/ #Whatever directory has this file in it
feeds=( examplefeed examplefeed2 ) #Edit this with list of directories with feeds you want

uptime=6 #Hour (in 24 hour clock) at which you want to update

while :
do
    echo 'The time is ' `date +%H:%M:%S`
    if [ `date +%H` -eq $uptime ]
    then
        echo 'Updating feeds...'
        for feed in "${feeds[@]}"
        do
            cd $documentroot/$feed
            bash -x ./update.sh
        done
    else
        echo 'Will update at' $uptime:`date +%M:%S`
    fi
    echo 'Will return in one hour.'
    sleep 3600
done

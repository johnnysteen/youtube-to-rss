## Before first use
* Clone this repository to any directory.
* Edit `documentroot` with wherever yours is.
* Change `$URL` in `setup.sh` to whatever base URL you're hosting from. The feed will be at `http://$URL/$feedname/feed.rss`.

## To use
* To use, run `run-updates.sh` (or `sudo ./run-updates.sh`) in a terminal window and leave it open. Or, if you actually know what you're doing and know a better way to leave it running constantly, do that instead.

## To create a feed
* To create a feed, run

> setup.sh feedname

* You will be asked to provide the url and a title for your feed.

* If you don't want to download all of a channel's old videos, then do

> cd feedname
>  youtube-dl --get-ids channel-url > archive

* You may have to add `root/feedname` to your apache2 conf.

* Repeat the above for every feed.

## What the scripts do
* setup.sh creates new feeds.
* update.sh downloads new uploads and adds them to the RSS feed.
* run-updates.sh will run `update.sh` on all of the feeds periodically throughout the day.


## FAQs

### What is this crap? Do you know anything about code development?
No.

### Can you help me troubleshoot this?
No. I wrote this in a day, and I suck. I'm confident you can figure this out.



# youtube-to-rss

* To use, create a directory with the name of your feed.
* In this repository I called it "examplefeed".
* Make a text file called "url" with the url to the channel or playlist.
* Make a blank file and call it "archive". Or, if you don't want to download all of a channel's old videos, instead run
>  youtube-dl --get-ids channel-url > archive
* Edit "feed.head" with the name of your feed and the URL of the root directory.
* Then edit feed/update.sh with the name of the directory and name of the url text file.

* Repeat the above for every feed. Don't forget to add all these new directories to your apache2 conf.

* Edit run-updates.sh and replace the list of feeds with the list of directories you create.
* This package supports an arbitrary number of feeds.

* root/update.sh does the main work.
* feed/update.sh just calls root/update.sh
* run-updates.sh will run all of the feeds' feed/update.sh at 6-7AM every morning.


## FAQs

### What is this crap? Do you know anything about code development?
No.

### Can you help me troubleshoot this?
No. I wrote this in a day, and I suck. I'm confident you can figure this out.

### Do you accept donations?
If you'd like to donate to me, please take that amount and send it here instead:
https://www.gofundme.com/vic-kicks-back
He needs it a lot more than I do.

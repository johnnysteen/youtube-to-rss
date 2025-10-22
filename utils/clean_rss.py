import argparse
import re

argparser = argparse.ArgumentParser()
argparser.add_argument('infile')

options = argparser.parse_args()

bad_toks = [
    r'<enclosure url="http://lepanto.hopto.org/[^/]*/[^/]*\.\*" type="audio/mpeg" length=""></enclosure>'
]

search_pat = '(?:% s)' % '|'.join(bad_toks)

toks = []
keep_this_item = True
with open(options.infile, encoding='utf-8') as f:
    for line in f:
        tok = line.strip()
        if tok == '<item>':
            while len(toks):
                if keep_this_item:
                    print(toks.pop(0).encode('ascii','ignore').decode())
                else:
                    toks.pop()
            keep_this_item=True
        toks.append(line.strip('\n'))
        if re.match(search_pat,tok):
            keep_this_item=False


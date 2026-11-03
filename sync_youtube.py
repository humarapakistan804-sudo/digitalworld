#!/usr/bin/env python3
"""Reads the Digital World YouTube channel (public RSS feeds, no API key) and
writes youtube.json. The website shows these videos in their category.

Category rules, strongest first:
 1. The video is inside a playlist listed in youtube-config.json -> that category.
 2. A new upload that is in no listed playlist:
      - a YouTube Short -> "shorts"
      - title/description contains a keyword from the config -> that category
      - otherwise "default_category" (empty = not shown)
"""
import json, re, os, sys, urllib.request, urllib.error
import xml.etree.ElementTree as ET

NS = {'a': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015',
      'm': 'http://search.yahoo.com/mrss/'}
UA = {'User-Agent': 'Mozilla/5.0 (compatible; DigitalWorldSync/1.0)'}
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def is_short(video_id):
    """A Short opens at /shorts/ID (HTTP 200). A normal video redirects away."""
    try:
        op = urllib.request.build_opener(_NoRedirect)
        req = urllib.request.Request('https://www.youtube.com/shorts/' + video_id, headers=UA)
        return op.open(req, timeout=30).status == 200
    except urllib.error.HTTPError:
        return False
    except Exception:
        return False


def parse_feed(xml_bytes):
    out = []
    for e in ET.fromstring(xml_bytes).findall('a:entry', NS):
        vid = e.find('yt:videoId', NS).text
        title = (e.find('a:title', NS).text or '').strip()
        pub = e.find('a:published', NS).text
        d = e.find('m:group/m:description', NS)
        out.append({'id': vid, 'title': title, 'published': pub,
                    'desc': (d.text or '') if d is not None else ''})
    return out


def playlist_id(v):
    v = (v or '').strip()
    m = re.search(r'[?&]list=([\w-]+)', v)
    return m.group(1) if m else v


def main():
    cfg = json.load(open(os.path.join(HERE, 'youtube-config.json'), encoding='utf-8'))
    out_path = os.path.join(HERE, 'youtube.json')
    try:
        old = json.load(open(out_path, encoding='utf-8')).get('videos', [])
    except Exception:
        old = []
    found = {}                       # (cat, id) -> entry
    in_playlist = set()

    for cat, pl in cfg.get('playlists', {}).items():
        pid = playlist_id(pl)
        if not pid:
            continue
        try:
            items = parse_feed(get('https://www.youtube.com/feeds/videos.xml?playlist_id=' + pid))
        except Exception as e:
            print('playlist', cat, 'failed:', e); continue
        for v in items:
            in_playlist.add(v['id'])
            found[(cat, v['id'])] = v

    try:
        recent = parse_feed(get('https://www.youtube.com/feeds/videos.xml?channel_id=' + cfg['channel_id']))
    except Exception as e:
        print('channel feed failed:', e); recent = []
    known = {x['id'] for x in old}
    for v in recent:
        if v['id'] in in_playlist:
            continue
        cats = []
        if v['id'] not in known and is_short(v['id']):
            cats.append('shorts')
        text = (v['title'] + ' ' + v['desc']).lower()
        for cat, words in cfg.get('keywords', {}).items():
            if cat not in cats and any(w.lower() in text for w in words):
                cats.append(cat); break
        if not cats and cfg.get('default_category'):
            cats.append(cfg['default_category'])
        for c in cats:
            found[(c, v['id'])] = v

    merged = {(x['cat'], x['id']): x for x in old}
    for (cat, vid), v in found.items():
        merged[(cat, vid)] = {'id': vid, 'cat': cat, 'title': v['title'], 'published': v['published'],
                              'thumb': 'https://i.ytimg.com/vi/%s/hqdefault.jpg' % vid}
    videos = sorted(merged.values(), key=lambda x: x.get('published') or '', reverse=True)
    if json.dumps(videos, sort_keys=True) == json.dumps(old, sort_keys=True):
        print('no change'); return
    import datetime
    json.dump({'updated': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'), 'videos': videos},
              open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('wrote', len(videos), 'videos')


if __name__ == '__main__':
    main()

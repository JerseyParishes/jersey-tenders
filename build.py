"""Build static, reusable outputs for the public Jersey tender listings."""

import argparse
import json
import os
import tempfile
from datetime import date, datetime
from email.utils import format_datetime
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPCookieProcessor
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from lxml import html

HOST = 'procontract.due-north.com'
PORTAL = '59ed6324-03e4-e611-80da-005056b64545'
SOURCE = (
    f'https://{HOST}/Opportunities/Index'
    f'?resetFilter=True&applyFilter=True&p={PORTAL}&v=1'
)
JERSEY = ZoneInfo('Europe/Jersey')
HEADERS = ['Title', 'Buyer', 'Expression Start', 'Expression End', 'Estimated value']


def clean(node):
    return ' '.join(node.text_content().split())


def parse_date(text):
    return datetime.strptime(text, '%d/%m/%Y').date().isoformat()


def scrape():
    opener = build_opener(HTTPCookieProcessor())
    url = SOURCE
    visited = set()
    notices = {}
    while url:
        if url in visited or len(visited) >= 25:
            raise ValueError('Unexpected pagination loop or page count.')
        visited.add(url)
        with opener.open(Request(url, headers={'User-Agent': 'JerseyTenderFeed/0.1'}), timeout=25) as response:
            if urlsplit(response.geturl()).hostname != HOST:
                raise ValueError('Unexpected portal redirect.')
            page = html.fromstring(response.read())
        grids = page.xpath('//*[@id="opportunitiesGrid"]')
        if len(grids) != 1 or list(map(clean, grids[0].xpath('./thead/tr/th'))) != HEADERS:
            raise ValueError('Unexpected listings layout. Check the official portal.')
        rows = grids[0].xpath('./tbody/tr')
        if not rows and 'no opportunities' not in clean(page).lower():
            raise ValueError('Empty listings table. Verify the portal before publishing.')
        for row in rows:
            cells = row.xpath('./td')
            if len(cells) == 1 and 'no opportunities' in clean(cells[0]).lower():
                continue
            if len(cells) != 5:
                raise ValueError('Unexpected notice row.')
            links = cells[0].xpath('./a[@href]')
            if len(links) != 1:
                raise ValueError('Missing official notice link.')
            link = links[0]
            parsed = urlsplit(urljoin(SOURCE, link.get('href')))
            query = parse_qs(parsed.query)
            if (parsed.scheme, parsed.netloc, parsed.path) != ('https', HOST, '/Advert'):
                raise ValueError('Unexpected notice link.')
            if query.get('p') != [PORTAL] or not query.get('advertId'):
                raise ValueError('Unexpected notice identifier or portal.')
            notice_id = query['advertId'][0]
            value = clean(cells[4])
            notices[notice_id] = {
                'id': notice_id,
                'reference': link.get('title'),
                'title': clean(link),
                'buyer': clean(cells[1]),
                'expression_start': parse_date(clean(cells[2])),
                'expression_end': parse_date(clean(cells[3])),
                'estimated_value': None if value == 'N/A' else value,
                'url': parsed.geturl(),
            }

        candidates = page.xpath('//*[@id="divGrid"]//a[@href]')
        url = None
        for link in candidates:
            if clean(link).casefold().rstrip(' >»›') != 'next' and link.get('rel') != 'next':
                continue
            target = urljoin(SOURCE, link.get('href'))
            parsed = urlsplit(target)
            if (parsed.scheme, parsed.netloc, parsed.path) != ('https', HOST, '/Opportunities/Index'):
                raise ValueError('Unexpected next-page link.')
            if parse_qs(parsed.query).get('p') != [PORTAL]:
                raise ValueError('Unexpected next-page portal.')
            url = target
            break
    return list(notices.values())


def display_date(iso):
    when = date.fromisoformat(iso)
    return f'{when.day} {when:%b %Y}'


def rss(items, checked, public_url):
    root = ET.Element('rss', version='2.0')
    channel = ET.SubElement(root, 'channel')
    ET.SubElement(channel, 'title').text = 'Jersey tender opportunities'
    ET.SubElement(channel, 'link').text = public_url or SOURCE
    ET.SubElement(channel, 'description').text = 'Public Jersey procurement notices from ProContract.'
    ET.SubElement(channel, 'language').text = 'en-gb'
    ET.SubElement(channel, 'lastBuildDate').text = format_datetime(checked)
    for notice in sorted(items, key=lambda item: item['expression_start'], reverse=True):
        item = ET.SubElement(channel, 'item')
        ET.SubElement(item, 'guid', isPermaLink='false').text = 'procontract:' + notice['id']
        ET.SubElement(item, 'title').text = notice['title']
        ET.SubElement(item, 'link').text = notice['url']
        ET.SubElement(item, 'description').text = (
            f"{notice['buyer']}. Expression of interest closes "
            f"{display_date(notice['expression_end'])}. See the official notice for the time."
        )
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def widget(items, checked):
    cards = []
    for item in items:
        value = item['estimated_value']
        meta = escape(item['buyer']) + (f' · Estimated value {escape(value)}' if value else '')
        title = escape(item['title'])
        url = escape(item['url'], quote=True)
        end = display_date(item['expression_end'])
        cards.append(f'<li><h2><a href="{url}" target="_blank" rel="noopener">{title}</a></h2>'
                     f'<p>{meta}</p><p>Expression of interest closes <strong>{end}</strong></p></li>')
    body = '<ul>' + ''.join(cards) + '</ul>' if cards else '<p>No current notices in this snapshot.</p>'
    stamp = checked.strftime('%d %b %Y at %H:%M')
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Jersey tender opportunities</title>
<link rel="alternate" type="application/rss+xml" href="tenders.xml" title="Jersey tender opportunities">
html:has(body:target) {{ background: transparent; }}
body:target {{
    margin: 0;
    max-width: none;
    padding: 0;
    color: #222;
    font-family: proxima-nova, Arial, sans-serif;
}}
body:target main > h1,
body:target main > h1 + p {{ display: none; }}
body:target ul {{ margin-top: 0; }}
body:target li {{
    padding: .85rem 0;
    border: 0;
    border-bottom: 1px solid #ddd;
    border-radius: 0;
    background: transparent;
}}
body:target a {{ color: #0E69B4; }}
<style>
@import url("https://use.typekit.net/oes8mgs.css");
:root {{ font-family: system-ui, sans-serif; color: #1a2630; background: #f6f8fa; }}
body {{ margin: 0 auto; max-width: 52rem; padding: clamp(1rem, 4vw, 2rem); }}
h1 {{ margin: 0; font-size: clamp(1.65rem, 5vw, 2.3rem); line-height: 1.1; }}
p {{ line-height: 1.5; margin: .45rem 0; }} a {{ color: #07546e; }}
a:focus-visible {{ outline: 3px solid #07546e; outline-offset: 3px; }}
ul {{ margin: 1.15rem 0; list-style: none; padding: 0; display: grid; gap: .65rem; }}
li {{ padding: .9rem 1rem; background: white; border: 1px solid #d4e0e6; border-radius: .55rem; }}
h2 {{ font-size: 1.08rem; margin: 0; line-height: 1.35; }}
li p, footer {{ font-size: .9rem; }}
</style></head>
<body id="embedded"><main>.
<p>Check the official notice for the closing time and how to respond.</p>
{body}</main>
<footer><p>Source <a href="{escape(SOURCE, quote=True)}" target="_blank" rel="noopener">Channel Islands Tenders</a>
 · Checked {stamp} Jersey time · <a href="tenders.xml">RSS</a></p></footer>
</body></html>""".encode()


def write_file(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(data)
            handle.close()
            temporary.chmod(0o644)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('public'))
    parser.add_argument('--public-url', help='Public URL of the widget page, for the RSS channel link.')
    args = parser.parse_args()
    notices = scrape()
    checked = datetime.now(JERSEY)
    today = checked.date().isoformat()
    items = sorted(
        (item for item in notices if item['expression_start'] <= today <= item['expression_end']),
        key=lambda item: (item['expression_end'], item['title'].casefold()),
    )
    payload = {'source_url': SOURCE, 'checked_at': checked.isoformat(), 'notices': items}
    outputs = {
        'index.html': widget(items, checked),
        'tenders.xml': rss(items, checked, args.public_url),
        'tenders.json': (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode(),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    for filename, data in outputs.items():
        write_file(args.output / filename, data)
    print(f'Read {len(notices)} notices and published {len(items)} current notices to {args.output}.')


if __name__ == '__main__':
    main()

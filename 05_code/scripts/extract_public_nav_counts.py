"""Extract displayed content counts from an already saved public page's navigation."""
import argparse
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

LABELS = {'Курсы': 'course', 'Статьи': 'article', 'Вебинары': 'webinar',
          'Подкасты': 'podcast', 'Шаблоны': 'document'}


class NavParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.field = None
        self.label = []
        self.count = []
        self.found = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = (attributes.get('class') or '').split()
        if tag == 'a' and 'header-menu-dropdown__format' in classes:
            self.active = True
            self.label = []
            self.count = []
        elif self.active and tag == 'span':
            if 'header-menu-dropdown__format-label' in classes:
                self.field = 'label'
            elif 'header-menu-dropdown__format-count' in classes:
                self.field = 'count'

    def handle_data(self, data):
        if self.active and self.field == 'label':
            self.label.append(data)
        elif self.active and self.field == 'count':
            self.count.append(data)

    def handle_endtag(self, tag):
        if tag == 'span':
            self.field = None
        elif tag == 'a' and self.active:
            self.found.append((' '.join(''.join(self.label).split()),
                               ' '.join(''.join(self.count).split())))
            self.active = False


def extract_counts(html):
    parser = NavParser()
    parser.feed(html)
    counts = {}
    for label, text in parser.found:
        if label not in LABELS:
            continue
        match = re.match(r'^(\d+(?:[\s\u00a0]\d{3})*)\s+материал', text)
        if not match:
            raise ValueError('Invalid count in navigation')
        value = int(re.sub(r'\s+', '', match.group(1)))
        kind = LABELS[label]
        if kind in counts and counts[kind] != value:
            raise ValueError('Conflicting navigation counts')
        counts[kind] = value
    if set(counts) != set(LABELS.values()):
        raise ValueError('Missing expected navigation counts')
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--html', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = args.html.read_bytes()
    counts = extract_counts(data.decode('utf-8', 'strict'))
    report = {'counts': counts, 'source_html_sha256': hashlib.sha256(data).hexdigest(),
              'coverage_verified': False,
              'limitations': 'Displayed navigation counts at capture time; definitions, availability, access and completeness are not verified.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

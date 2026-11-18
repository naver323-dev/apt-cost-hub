"""Stream-parse the K-apt XLSX snapshots into compact row lists.

The K-apt weekly files are single-sheet XLSX with inline strings and no
dimension record, so openpyxl cannot page them; we stream the sheet XML.
"""
import zipfile
import xml.etree.ElementTree as ET

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def _cell_value(c):
    t = c.find(NS + 'is')
    if t is not None:
        return ''.join(x.text or '' for x in t.iter(NS + 't'))
    v = c.findtext(NS + 'v')
    return v if v is not None else ''


def rows(path):
    z = zipfile.ZipFile(path)
    name = [n for n in z.namelist() if n.startswith('xl/worksheets/sheet')][0]
    with z.open(name) as f:
        for _, el in ET.iterparse(f, events=('end',)):
            if el.tag != NS + 'row':
                continue
            yield [_cell_value(c) for c in el.findall(NS + 'c')]
            el.clear()

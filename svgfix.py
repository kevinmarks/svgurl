import html5lib
import html5lib.serializer
import html5lib.treewalkers
import openanything

def svgfix(src):
    # Parse SRC as HTML.
    tree_builder = html5lib.treebuilders.getTreeBuilder('dom')
    parser = html5lib.html5parser.HTMLParser(tree = tree_builder)
    dom = parser.parse(src)
    
    svg = dom.getElementsByTagName('svg')[0]
    for s in svg.getElementsByTagName('script'):
        svg.removeChild(s)
    tree_walker = html5lib.treewalkers.getTreeWalker('dom')
    html_serializer = html5lib.serializer.htmlserializer.HTMLSerializer(quote_attr_values=True)
    return u''.join(html_serializer.serialize(tree_walker(svg)))

def urlfix(url):
    return svgfix(openanything.fetch(url).get('data',''))
    
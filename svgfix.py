import html5lib
import html5lib.serializer
import html5lib.treewalkers
import openanything
import logging

maxuse = 36

def svgfix(src):
    # Parse SRC as HTML.
    tree_builder = html5lib.treebuilders.getTreeBuilder('dom')
    parser = html5lib.html5parser.HTMLParser(tree = tree_builder)
    dom = parser.parse(src)
    hadScript = False
    overUse = False
    svg = dom.getElementsByTagName('svg')[0]
    usecount = 0;
    for g in svg.getElementsByTagName('g'):
        for u in g.getElementsByTagName('use'):
            usecount= usecount+1
            if usecount> maxuse:
                g.removeChild(u)
                overUse = True
                logging.info("usecount: '%s' " %(usecount))
    for s in svg.getElementsByTagName('script'):
        svg.removeChild(s)
        hadScript = True
    tree_walker = html5lib.treewalkers.getTreeWalker('dom')
    html_serializer = html5lib.serializer.htmlserializer.HTMLSerializer(quote_attr_values=True)
    return u''.join(html_serializer.serialize(tree_walker(svg))),hadScript or overUse

def urlfix(url):
    return svgfix(openanything.fetch(url).get('data',''))
    
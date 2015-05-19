#!/usr/bin/env python
#

from __future__ import with_statement
import os
import urllib
import jinja2
import webapp2
import increment
import newbase60
import base64
from google.appengine.api import files


siteName = "http://svgur.com"

svgcounter = increment.Increment("svg-id", 10)

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)

from google.appengine.ext import blobstore
from google.appengine.ext.webapp import blobstore_handlers
from google.appengine.ext import ndb
from google.appengine.api import images


class SvgPage(ndb.Model):
    """Models an individual svg page."""
    svgid = ndb.IntegerProperty(indexed=True)
    svgBlob = ndb.BlobKeyProperty(indexed=True)
    pngBlob = ndb.BlobKeyProperty(indexed=True)
    published = ndb.DateTimeProperty(auto_now_add=True)
    name = ndb.StringProperty(indexed=True)
    summary = ndb.StringProperty(indexed=False)
    
class MainHandler(webapp2.RequestHandler):
  def get(self):
    upload_url = blobstore.create_upload_url('/upload')
    template = JINJA_ENVIRONMENT.get_template('homepage.html')
    qry = SvgPage.query().order(-SvgPage.published)
    recentpix=qry.fetch(20)
    pix = [ {"name":"%s" % page.name, "svgid":newbase60.numtosxg(page.svgid),"published":page.published} for page in recentpix]
    self.response.write(template.render({'upload_url':upload_url, 'pix':pix}))

class UploadHandler(blobstore_handlers.BlobstoreUploadHandler):
  def post(self):
    upload_files = self.get_uploads('file')  # 'file' is file upload field in the form
    blob_info = upload_files[0]
    page = SvgPage()
    page.name = self.request.get('name',"")
    page.summary = self.request.get('summary',"")
    page.svgBlob=blob_info.key()
    page.svgid = svgcounter.one()
    pngAsData = self.request.get('pngfield',"")
    if (pngAsData):
        png = base64.b64decode(pngAsData.split("data:image/png;base64,")[1])
        if png:
            # Create the file
            file_name = files.blobstore.create(mime_type='image/png')

            # Open the file and write to it
            with files.open(file_name, 'a') as f:
              f.write(png)

            # Finalize the file. Do this before attempting to read it.
            files.finalize(file_name)

            # Get the file's blob key
            page.pngBlob = files.blobstore.get_blob_key(file_name)
    page.put()
    self.redirect('/s/%s' % newbase60.numtosxg(page.svgid))
    
    
class PngHandler(webapp2.RequestHandler):
  def get(self, filename):
    bits= filename.split('.')
    key = bits[0]
    extension = '.svg'
    if len(bits)>1:
        extension = bits[1] #awaiting conditional code for png/jpg
    resource = int(newbase60.sxgtonum(urllib.unquote(key)))
    qry = SvgPage.query(SvgPage.svgid == resource)
    width = str(self.request.get('width', "0"))
    pages = qry.fetch(1)
    if pages[0].pngBlob:
        self.redirect(images.get_serving_url(pages[0].pngBlob)+"=s"+width+"-c")
    else:
        blob_info = blobstore.BlobInfo.get(pages[0].svgBlob)
        self.send_blob(blob_info)

class ServeHandler(blobstore_handlers.BlobstoreDownloadHandler):
  def get(self, filename):
    bits= filename.split('.')
    key = bits[0]
    extension = '.svg'
    if len(bits)>1:
        extension = bits[1] #awaiting conditional code for png/jpg
    resource = int(newbase60.sxgtonum(urllib.unquote(key)))
    qry = SvgPage.query(SvgPage.svgid == resource)
    pages = qry.fetch(1)
    blob_info = blobstore.BlobInfo.get(pages[0].svgBlob)
    self.send_blob(blob_info)
    
class FrameHandler(blobstore_handlers.BlobstoreDownloadHandler):
  def get(self, filename):
    bits= filename.split('.')
    key = bits[0]
    extension = '.svg'
    if len(bits)>1:
        extension = bits[1] #awaiting conditional code for png/jpg
    resource = int(newbase60.sxgtonum(urllib.unquote(key)))
    qry = SvgPage.query(SvgPage.svgid == resource)
    pages = qry.fetch(1)
    svgStr = newbase60.numtosxg(resource)
    blob_info = blobstore.BlobInfo.get(pages[0].svgBlob)
    template = JINJA_ENVIRONMENT.get_template('iframe.html')
    reader = blobstore.BlobReader(blob_info)
    rawsvg = reader.read().decode('utf-8')
    svgVals = { 'name':pages[0].name,
                'svg': rawsvg
                }
    self.response.write(template.render(svgVals))    


class RawServeHandler(blobstore_handlers.BlobstoreDownloadHandler):
  def get(self, resource):
    resource = str(urllib.unquote(resource))
    blob_info = blobstore.BlobInfo.get(resource)
    self.send_blob(blob_info)

class SvgHandler(webapp2.RequestHandler):
  def get(self, filename):
    resource = int(newbase60.sxgtonum(urllib.unquote(filename)))
    qry = SvgPage.query(SvgPage.svgid == resource)
    pages = qry.fetch(1)
    svgStr = newbase60.numtosxg(resource)
    template = JINJA_ENVIRONMENT.get_template('svgpage.html')
    svgVals = { 'name':pages[0].name,
                'summary':pages[0].summary,
                'published':pages[0].published,
                'url':'/i/'+ svgStr+'.svg',
                'rawurl':'/raw/'+ str(pages[0].svgBlob),
                'image_link':siteName+'/s/'+svgStr,
                'iframe_link':siteName+'/f/'+ svgStr,
                'direct_link':siteName+'/i/'+ svgStr+'.svg'
                }
    self.response.write(template.render(svgVals))    

app = webapp2.WSGIApplication([('/', MainHandler),
                               ('/s/([^/]+)?', SvgHandler),
                               ('/upload', UploadHandler),
                               ('/i/([^/]+)?', ServeHandler),
                               ('/f/([^/]+)?', FrameHandler),
                               ('/p/([^/]+)?', PngHandler),
                               ('/raw/([^/]+)?', RawServeHandler)],
                              debug=True)